"""
AI 채점 엔진
- Gemini, OpenAI, Anthropic 다중 모델 지원
- SSE 기반 실시간 진행 브로드캐스트
"""
import hashlib
import json
import time
import shutil
from datetime import datetime
from pathlib import Path
from queue import Queue

from models.project import ProjectConfig, load_project, generate_default_prompt
from models.evaluation import build_evaluation_model, compute_scores
from services.file_manager import find_materials, get_participant_files
from config import PROJECTS_DIR, AI_MODELS, OPENAI_AI_MODELS
from services.providers import get_provider
from services.providers.base import ProviderNeedsUserAction


ROUND_META_FILENAME = "round.json"
ROUND_META_SCHEMA_VERSION = 1


class RoundContextMismatch(RuntimeError):
    """같은 회차에 서로 다른 모델·기준을 섞으려 할 때 발생."""


# ─── 전역 상태 ─────────────────────────────────────────────
grading_state = {
    "running": False,
    "should_stop": False,
    "project_id": None,
    "current_team": None,
    "current_step": "",
    "completed_count": 0,
    "total_count": 0,
    "success_count": 0,
    "fail_count": 0,
    "current_round": 1,
    "started_at": None,
    "team_started_at": None,
    "stop_requested_at": None,
    "target_team_numbers": [],
    "run_mode": "",
    "execution_context": {},
}
event_queues: list[Queue] = []


def broadcast_event(event_type: str, data: dict):
    """모든 연결된 클라이언트에 SSE 이벤트 송신"""
    if event_type == "step":
        grading_state["current_step"] = str(data.get("step", ""))
    elif event_type == "team_start":
        grading_state["current_team"] = data.get("team")
        grading_state["team_started_at"] = time.time()
        grading_state["current_step"] = "AI 응답 대기 중..."
    elif event_type == "team_done":
        grading_state["current_step"] = f"{data.get('team')}번 저장 완료"
    elif event_type == "team_error":
        grading_state["current_step"] = f"{data.get('team')}번 실패"
    elif event_type in ("finished", "stopped"):
        grading_state["current_step"] = str(data.get("message", "채점 종료"))
    msg = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    dead = []
    for q in event_queues:
        try:
            q.put(msg, block=False)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in event_queues:
            event_queues.remove(q)


def get_round_dir(project_id: str, round_id: int) -> Path:
    return PROJECTS_DIR / project_id / "results" / f"round_{round_id}"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_round_meta_path(project_id: str, round_id: int) -> Path:
    return get_round_dir(project_id, round_id) / ROUND_META_FILENAME


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_execution_context(config: ProjectConfig) -> dict:
    """회차 안에서 바뀌면 안 되는 공급자·모델·평가기준을 고정한다."""
    data = config.to_dict()
    exam = data.get("exam") or {}
    criteria_payload = {
        "project_type": config.project_type,
        "categories": data.get("categories", []),
        "report_delivery_mode": config.criteria_state.delivery_mode,
        "exam_questions": exam.get("questions", []),
        "exam_grading_mode": exam.get("grading_mode", ""),
        "exam_additional_instructions": exam.get("additional_instructions", ""),
        "prompt_template": config.prompt_template,
    }
    criteria_fingerprint = _hash_payload(criteria_payload)
    signature_payload = {
        "provider": config.ai_provider,
        "model": config.ai_model,
        "temperature": config.temperature,
        "criteria_fingerprint": criteria_fingerprint,
    }
    return {
        "provider": config.ai_provider,
        "model": config.ai_model,
        "temperature": config.temperature,
        "criteria_version": config.criteria_state.active_version,
        "approved_criteria_version": config.criteria_state.approved_version,
        "criteria_status": config.criteria_state.status,
        "criteria_fingerprint": criteria_fingerprint,
        "execution_signature": _hash_payload(signature_payload),
    }


def load_round_metadata(project_id: str, round_id: int) -> dict:
    path = get_round_meta_path(project_id, round_id)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_round_metadata(project_id: str, round_id: int, metadata: dict) -> None:
    round_dir = get_round_dir(project_id, round_id)
    round_dir.mkdir(parents=True, exist_ok=True)
    path = get_round_meta_path(project_id, round_id)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _round_result_numbers(project_id: str, round_id: int) -> set[int]:
    numbers = set()
    round_dir = get_round_dir(project_id, round_id)
    if not round_dir.exists():
        return numbers
    for path in round_dir.glob("team_*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            number = int(value.get("team_number", 0))
            if number > 0:
                numbers.add(number)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return numbers


def _round_has_artifacts(project_id: str, round_id: int) -> bool:
    return bool(
        load_round_metadata(project_id, round_id)
        or _round_result_numbers(project_id, round_id)
    )


def _model_estimate(config: ProjectConfig) -> dict:
    registry = (
        OPENAI_AI_MODELS
        if config.ai_provider == "openai_api"
        else AI_MODELS
    )
    model = registry.get(config.ai_model, {})
    cost = model.get("estimated_cost_krw")
    cost_range = cost.get(config.project_type) if isinstance(cost, dict) else None
    return {
        "seconds_per_request": max(
            1, int(model.get("estimated_seconds_per_request", 60) or 60)
        ),
        "cost_per_student_range_krw": cost_range,
    }


def estimate_grading_run(
    config: ProjectConfig,
    *,
    first_target_count: int,
    repeat_target_count: int,
    repeat_count: int,
    delay: int,
) -> dict:
    repeat_count = max(1, int(repeat_count or 1))
    requests_per_student = 2 if config.project_type == "exam" else 1
    student_rounds = first_target_count + max(0, repeat_count - 1) * repeat_target_count
    expected_requests = student_rounds * requests_per_student
    waits = max(0, first_target_count - 1)
    waits += max(0, repeat_count - 1) * max(0, repeat_target_count - 1)
    model_estimate = _model_estimate(config)
    central_seconds = (
        expected_requests * model_estimate["seconds_per_request"]
        + waits * max(0, int(delay or 0))
    )
    cost_range = model_estimate["cost_per_student_range_krw"]
    total_cost_range = (
        [
            int(cost_range[0]) * student_rounds,
            int(cost_range[1]) * student_rounds,
        ]
        if isinstance(cost_range, list) and len(cost_range) == 2
        else None
    )
    return {
        "student_rounds": student_rounds,
        "requests_per_student": requests_per_student,
        "expected_requests": expected_requests,
        "estimated_minutes_range": [
            max(1, round(central_seconds * 0.6 / 60)) if central_seconds else 0,
            max(1, round(central_seconds * 1.8 / 60)) if central_seconds else 0,
        ],
        "estimated_cost_range_krw": total_cost_range,
        "estimate_note": (
            "파일 쪽 수, 답안 복잡도, 재시도와 실제 토큰 사용량에 따라 크게 달라질 수 있습니다."
        ),
    }


def classify_grading_error(error: Exception | str) -> dict:
    message = str(error)
    lower = message.lower()
    if any(key in lower for key in (
        "api 키", "api key", "authentication", "unauthorized", "401", "login"
    )):
        category = "authentication"
        action = "API 키와 로그인 상태를 확인한 뒤 같은 모델로 실패 학생만 재시도하세요."
        retryable = False
    elif any(key in lower for key in (
        "quota", "쿼터", "크레딧", "credit", "billing", "insufficient"
    )):
        category = "quota"
        action = "결제·일일 한도를 확인하세요. 모델을 바꾸려면 새 회차로 시작해야 합니다."
        retryable = False
    elif any(key in lower for key in ("429", "rate limit", "rate_limit", "요청 한도")):
        category = "rate_limit"
        action = "잠시 기다린 뒤 현재 회차의 실패 학생만 재시도하세요."
        retryable = True
    elif any(key in lower for key in (
        "timeout", "timed out", "시간 초과", "disconnected"
    )):
        category = "timeout"
        action = "네트워크와 파일 크기를 확인한 뒤 실패 학생만 재시도하세요."
        retryable = True
    elif any(key in lower for key in (
        "503", "overloaded", "일시적인 응답 오류", "생성이 취소",
        "something went wrong", "문제가 발생"
    )):
        category = "temporary_provider"
        action = "AI 서비스의 일시 오류입니다. 잠시 뒤 실패 학생만 재시도하세요."
        retryable = True
    elif any(key in lower for key in (
        "파일", "pdf", "upload", "업로드", "변환", "blank", "백지"
    )):
        category = "file"
        action = "해당 학생 파일이 열리는지와 PDF 변환 상태를 확인하세요."
        retryable = False
    elif any(key in lower for key in ("schema", "json", "형식", "parse", "파싱")):
        category = "response_format"
        action = "응답 형식 오류입니다. 같은 모델로 다시 시도하고 반복되면 개발용 오류로 기록하세요."
        retryable = True
    else:
        category = "unknown"
        action = "오류 내용을 확인한 뒤 해당 학생만 다시 시도하세요."
        retryable = False
    return {
        "category": category,
        "message": message[:500],
        "action": action,
        "retryable": retryable,
    }


def build_grading_plan(
    config: ProjectConfig,
    *,
    start_from: int = 1,
    delay: int = 5,
    repeat_count: int = 1,
    new_round: bool = True,
    team_numbers: list[int] | None = None,
    round_id: int | None = None,
    retry_failed: bool = False,
) -> dict:
    """실제 파일을 바꾸지 않고 이번 실행의 회차·대상·요청량을 계산한다."""
    materials = find_materials(config)
    available = sorted({
        int(participant["number"])
        for participant in materials
        if participant.get("files")
        and int(participant["number"]) >= max(1, int(start_from or 1))
    })
    selected = (
        sorted({int(number) for number in team_numbers if int(number) in available})
        if team_numbers
        else list(available)
    )
    latest_round = get_latest_round_id(config.id)

    if retry_failed:
        target_round = int(round_id or latest_round)
        metadata = load_round_metadata(config.id, target_round)
        failed_numbers = {
            int(item.get("team_number", 0))
            for item in metadata.get("failures", [])
            if int(item.get("team_number", 0) or 0) > 0
        }
        selected = [
            number for number in selected
            if number in failed_numbers
        ] if team_numbers else [
            number for number in available if number in failed_numbers
        ]
        mode = "retry_failed"
        repeat_count = 1
    elif new_round:
        target_round = (
            latest_round + 1
            if _round_has_artifacts(config.id, latest_round)
            else latest_round
        )
        metadata = {}
        mode = "new"
    else:
        target_round = int(round_id or latest_round)
        metadata = load_round_metadata(config.id, target_round)
        mode = "resume"
        # 이어하기는 현재 회차 복구만 수행한다. 독립 반복 채점은 새 회차 모드에서만 만든다.
        repeat_count = 1

    completed_numbers = _round_result_numbers(config.id, target_round)
    first_targets = [
        number for number in selected if number not in completed_numbers
    ]
    repeat_targets = list(selected)
    context = build_execution_context(config)
    context_error = ""
    if mode != "new" and completed_numbers and not metadata:
        context_error = (
            "이 기존 회차에는 공급자·모델·기준 기록이 없어 안전하게 이어갈 수 없습니다. "
            "새 회차로 시작하세요."
        )
    elif (
        mode != "new"
        and metadata.get("execution_context", {}).get("execution_signature")
        and metadata["execution_context"]["execution_signature"]
        != context["execution_signature"]
    ):
        previous = metadata["execution_context"]
        context_error = (
            "현재 설정이 이 회차의 실행 조건과 다릅니다. "
            f"기존: {previous.get('provider', '?')} / {previous.get('model', '?')} / "
            f"기준 v{previous.get('criteria_version', 0) or '미저장'}, "
            f"현재: {context['provider']} / {context['model']} / "
            f"기준 v{context['criteria_version'] or '미저장'}. 새 회차로 시작하세요."
        )

    estimate = estimate_grading_run(
        config,
        first_target_count=len(first_targets),
        repeat_target_count=len(repeat_targets),
        repeat_count=repeat_count,
        delay=delay,
    )
    return {
        "round_id": target_round,
        "mode": mode,
        "new_round": mode == "new",
        "start_from": max(1, int(start_from or 1)),
        "delay": max(0, int(delay or 0)),
        "repeat_count": max(1, int(repeat_count or 1)),
        "available_count": len(available),
        "selected_count": len(selected),
        "completed_count": len(completed_numbers),
        "target_count": len(first_targets),
        "target_team_numbers": first_targets,
        "repeat_target_team_numbers": repeat_targets,
        "failed_count": len(metadata.get("failures", [])),
        "execution_context": context,
        "context_error": context_error,
        "can_start": bool(first_targets) and not context_error,
        "estimate": estimate,
    }


def begin_round_attempt(config: ProjectConfig, plan: dict) -> dict:
    round_id = int(plan["round_id"])
    existing = load_round_metadata(config.id, round_id)
    context = build_execution_context(config)
    previous_signature = (
        existing.get("execution_context", {}).get("execution_signature")
    )
    if previous_signature and previous_signature != context["execution_signature"]:
        raise RoundContextMismatch(
            "같은 회차에는 서로 다른 공급자·모델·평가기준을 섞을 수 없습니다. 새 회차로 시작하세요."
        )
    if existing and not previous_signature and _round_result_numbers(config.id, round_id):
        raise RoundContextMismatch(
            "기존 회차에는 실행 조건 기록이 없어 안전하게 이어갈 수 없습니다. 새 회차로 시작하세요."
        )

    now = _now_iso()
    metadata = existing or {
        "schema_version": ROUND_META_SCHEMA_VERSION,
        "round_id": round_id,
        "created_at": now,
        "workflow_type": config.workflow_type,
        "project_type": config.project_type,
        "execution_context": context,
        "target_team_numbers": list(plan["target_team_numbers"]),
        "failures": [],
        "attempts": [],
    }
    if not metadata.get("target_team_numbers"):
        metadata["target_team_numbers"] = list(plan["target_team_numbers"])
    metadata["execution_context"] = context
    metadata["status"] = "running"
    metadata["updated_at"] = now
    metadata["started_at"] = metadata.get("started_at") or now
    metadata["finished_at"] = ""
    metadata["request_plan"] = plan.get("estimate", {})
    metadata["attempts"].append({
        "attempt": len(metadata.get("attempts", [])) + 1,
        "mode": plan.get("mode", "new"),
        "started_at": now,
        "finished_at": "",
        "status": "running",
        "requested_team_numbers": list(plan["target_team_numbers"]),
        "success_count": 0,
        "failure_count": 0,
    })
    save_round_metadata(config.id, round_id, metadata)
    return metadata


def record_round_failure(
    project_id: str,
    round_id: int,
    *,
    team_number: int,
    team_name: str,
    error: Exception | str,
) -> dict:
    metadata = load_round_metadata(project_id, round_id)
    detail = classify_grading_error(error)
    failure = {
        "team_number": int(team_number),
        "team_name": str(team_name),
        **detail,
        "occurred_at": _now_iso(),
    }
    failures = [
        item
        for item in metadata.get("failures", [])
        if int(item.get("team_number", 0) or 0) != int(team_number)
    ]
    failures.append(failure)
    metadata["failures"] = sorted(
        failures, key=lambda item: int(item.get("team_number", 0) or 0)
    )
    metadata["updated_at"] = failure["occurred_at"]
    save_round_metadata(project_id, round_id, metadata)
    return failure


def clear_round_failure(project_id: str, round_id: int, team_number: int) -> None:
    metadata = load_round_metadata(project_id, round_id)
    if not metadata:
        return
    metadata["failures"] = [
        item
        for item in metadata.get("failures", [])
        if int(item.get("team_number", 0) or 0) != int(team_number)
    ]
    metadata["updated_at"] = _now_iso()
    save_round_metadata(project_id, round_id, metadata)


def finish_round_attempt(
    project_id: str,
    round_id: int,
    *,
    stopped: bool = False,
) -> dict:
    metadata = load_round_metadata(project_id, round_id)
    if not metadata:
        return {}
    now = _now_iso()
    completed_numbers = _round_result_numbers(project_id, round_id)
    failures = [
        item
        for item in metadata.get("failures", [])
        if int(item.get("team_number", 0) or 0) not in completed_numbers
    ]
    targets = {
        int(number) for number in metadata.get("target_team_numbers", [])
    }
    if targets and targets <= completed_numbers:
        status = "completed"
    elif stopped:
        status = "stopped"
    elif failures:
        status = "completed_with_errors"
    else:
        status = "partial"
    metadata["status"] = status
    metadata["updated_at"] = now
    metadata["finished_at"] = now
    metadata["failures"] = failures
    metadata["completed_count"] = len(completed_numbers)
    metadata["failure_count"] = len(failures)
    metadata["remaining_count"] = max(0, len(targets - completed_numbers))
    if metadata.get("attempts"):
        attempt = metadata["attempts"][-1]
        attempt["status"] = status
        attempt["finished_at"] = now
        requested = {
            int(number) for number in attempt.get("requested_team_numbers", [])
        }
        attempt["success_count"] = len(requested & completed_numbers)
        attempt["failure_count"] = sum(
            1
            for item in failures
            if int(item.get("team_number", 0) or 0) in requested
        )
    save_round_metadata(project_id, round_id, metadata)
    return metadata


def summarize_round(
    config: ProjectConfig,
    round_id: int,
    *,
    participant_count: int = 0,
    active: bool = False,
) -> dict:
    metadata = load_round_metadata(config.id, round_id)
    completed_numbers = _round_result_numbers(config.id, round_id)
    failures = [
        item
        for item in metadata.get("failures", [])
        if int(item.get("team_number", 0) or 0) not in completed_numbers
    ]
    target_numbers = {
        int(number) for number in metadata.get("target_team_numbers", [])
    }
    target_count = len(target_numbers) or participant_count or len(completed_numbers)
    status = metadata.get("status", "legacy" if completed_numbers else "prepared")
    if status == "running" and not active:
        status = "interrupted"
    context = metadata.get("execution_context", {})
    remaining_count = max(0, target_count - len(completed_numbers))
    return {
        "id": round_id,
        "status": status,
        "count": len(completed_numbers),
        "completed_count": len(completed_numbers),
        "target_count": target_count,
        "remaining_count": remaining_count,
        "failure_count": len(failures),
        "failures": failures,
        "provider": context.get("provider", ""),
        "model": context.get("model", ""),
        "criteria_version": context.get("criteria_version", 0),
        "approved_criteria_version": context.get("approved_criteria_version", 0),
        "criteria_status": context.get("criteria_status", ""),
        "started_at": metadata.get("started_at", ""),
        "finished_at": metadata.get("finished_at", ""),
        "attempt_count": len(metadata.get("attempts", [])),
        "request_plan": metadata.get("request_plan", {}),
        "can_resume": bool(metadata) and remaining_count > 0,
        "can_retry": bool(failures),
        "legacy": not bool(metadata) and bool(completed_numbers),
    }


def list_round_summaries(
    config: ProjectConfig,
    *,
    participant_count: int = 0,
    active_round_id: int | None = None,
) -> list[dict]:
    results_dir = PROJECTS_DIR / config.id / "results"
    if not results_dir.exists():
        return []
    round_ids = []
    for directory in results_dir.glob("round_*"):
        if not directory.is_dir():
            continue
        try:
            round_ids.append(int(directory.name.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return [
        summarize_round(
            config,
            round_id,
            participant_count=participant_count,
            active=round_id == active_round_id,
        )
        for round_id in sorted(set(round_ids))
    ]


def get_latest_round_id(project_id: str) -> int:
    results_dir = PROJECTS_DIR / project_id / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    round_dirs = [d for d in results_dir.iterdir() if d.is_dir() and d.name.startswith("round_")]
    if not round_dirs:
        return 1
    max_id = 1
    for d in round_dirs:
        try:
            num = int(d.name.split("_")[1])
            if num > max_id:
                max_id = num
        except ValueError:
            pass
    return max_id


def load_completed(project_id: str, round_id: int = None) -> dict:
    """완료된 채점 결과 로드"""
    if round_id is None:
        round_id = get_latest_round_id(project_id)
    round_dir = get_round_dir(project_id, round_id)
    completed = {}
    if round_dir.exists():
        for json_file in round_dir.glob("team_*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    team_num = data.get("team_number")
                    if team_num:
                        completed[team_num] = data
            except (json.JSONDecodeError, KeyError):
                continue
    return completed


def save_result(project_id: str, round_id: int, result_data: dict, team_number: int):
    """채점 결과를 원자적으로 저장해 중단 중 기존 성공 결과가 손상되지 않게 한다."""
    round_dir = get_round_dir(project_id, round_id)
    round_dir.mkdir(parents=True, exist_ok=True)
    filepath = round_dir / f"team_{team_number:03d}.json"
    temporary = filepath.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(filepath)


# ─── AI 클라이언트 생성 ─────────────────────────────────────

def create_ai_client(api_key: str):
    """Gemini AI 클라이언트 생성"""
    from google import genai
    return genai.Client(api_key=api_key)


def evaluate_with_gemini(client, model_name: str, config: ProjectConfig, 
                          team_num: int, files: list[dict], prompt: str, eval_model):
    """Gemini로 채점"""
    from google.genai import types
    
    temp_dir = PROJECTS_DIR / config.id / "temp"
    temp_dir.mkdir(exist_ok=True)
    temp_files = []
    uploaded = []
    
    try:
        parts = []
        
        for file_info in files:
            original_path = Path(file_info["path"])
            file_ext = original_path.suffix.lower()
            
            # Gemini가 지원하지 않는 문서(HWP, DOCX 등) → PDF 자동 변환
            if file_ext in (".hwp", ".hwpx", ".docx", ".doc"):
                pdf_path = temp_dir / f"temp_{team_num}_{len(temp_files)}.pdf"
                broadcast_event("step", {"team": team_num, "step": f"{file_info['name']} PDF 변환 중..."})
                _convert_doc_to_pdf(original_path, pdf_path)
                if not pdf_path.exists():
                    raise RuntimeError(f"문서 변환 실패: {file_info['name']}")
                temp_files.append(pdf_path)
                upload_path = pdf_path
            else:
                # ASCII 임시 파일로 복사 (한글 파일명 에러 방지)
                temp_path = temp_dir / f"temp_{team_num}_{len(temp_files)}{file_ext}"
                shutil.copy2(original_path, temp_path)
                temp_files.append(temp_path)
                upload_path = temp_path
            
            broadcast_event("step", {"team": team_num, "step": f"{file_info['name']} 업로드 중..."})
            uploaded_file = client.files.upload(file=str(upload_path))
            uploaded.append(uploaded_file)
            
            # 영상 파일은 처리 대기
            if file_info["type"] == "videos":
                broadcast_event("step", {"team": team_num, "step": f"{file_info['name']} 처리 대기 중..."})
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(5)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                if uploaded_file.state.name == "FAILED":
                    raise RuntimeError(f"파일 처리 실패: {file_info['name']}")
            else:
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(3)
                    uploaded_file = client.files.get(name=uploaded_file.name)
            
            parts.append(types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=uploaded_file.mime_type))
        
        parts.append(types.Part.from_text(text=prompt))
        
        broadcast_event("step", {"team": team_num, "step": "AI 채점 중..."})
        response = client.models.generate_content(
            model=model_name,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=eval_model,
                temperature=config.temperature,
            ),
        )
        
        result = eval_model.model_validate_json(response.text)
        result_dict = result.model_dump()
        result_dict["team_number"] = team_num
        
        # 업로드 파일 정리
        for uf in uploaded:
            try:
                client.files.delete(name=uf.name)
            except Exception:
                pass
        
        return result_dict
        
    finally:
        for tp in temp_files:
            try:
                if tp.exists():
                    tp.unlink()
            except Exception:
                pass


# ─── 채점 워커 ─────────────────────────────────────────────

def build_existence_schema(questions) -> dict:
    """문항별 답 존재 여부와 원문 인용을 받는 검증용 스키마."""
    properties = {}
    for question in questions:
        properties[f"{question.id}_exists"] = {
            "type": "boolean",
            "description": f"{question.number}번 답이 답안지에 실제로 존재하면 true",
        }
        properties[f"{question.id}_quote"] = {
            "type": "string",
            "description": f"{question.number}번 답의 첫 부분(10~20자) 원문 인용. 없으면 빈 문자열",
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
    }


def verify_answer_existence(provider, config: ProjectConfig,
                            files: list[dict], result_dict: dict,
                            on_step=None) -> None:
    """채점과 독립된 2차 호출로 문항별 답 존재 여부를 교차 검증한다.

    채점 모델이 내용을 환각하면 has_answer 판정도 함께 환각할 수 있으므로,
    채점 압박이 없는 존재-판정 전용 호출로 대조해 어긋나는 문항을 바로잡는다.
    """
    questions = list(config.exam.scored_questions())
    if not questions:
        return
    step = on_step or (lambda _message: None)
    numbers = ", ".join(q.number for q in questions)
    prompt = (
        "당신은 채점 검증자입니다. 채점은 하지 마세요.\n"
        "첨부된 파일은 학생 한 명의 답안지입니다. "
        f"각 문항({numbers}번)의 답이 답안지에 실제로 존재하는지만 판정하세요.\n"
        "규칙:\n"
        "1. 답이 있으면 exists=true로 하고, 그 답의 첫 부분(10~20자)을 답안지에 적힌 "
        "원문 그대로 quote에 인용하세요.\n"
        "2. 답란이 비어 있거나 그 번호의 답을 찾을 수 없으면 exists=false, quote는 빈 문자열입니다.\n"
        "3. 다른 문항의 답을 이 문항의 답으로 착각하지 마세요. 문항 번호 표기와 답의 내용을 "
        "함께 확인하고, 어느 문항의 답인지 불확실하면 exists=false로 두세요."
    )
    verification = provider.generate_json(
        prompt,
        schema=build_existence_schema(questions),
        files=[str(item["path"]) for item in files],
        model_name=config.ai_model,
        temperature=0.0,
        on_step=step,
    )
    for question in questions:
        exists = bool(verification.get(f"{question.id}_exists", True))
        quote = str(verification.get(f"{question.id}_quote", "")).strip()
        result_dict[f"{question.id}_evidence"] = quote
        graded_score = int(result_dict.get(question.id, 0) or 0)
        summary = str(result_dict.get(f"{question.id}_answer_summary", "")).strip()
        if not exists and graded_score > 0:
            # 검증 패스가 '답 없음'인데 점수가 있으면 무응답으로 강제한다.
            # has_answer를 false로 두면 compute_scores가 0점 처리를 완성한다.
            result_dict[f"{question.id}_has_answer"] = False
            result_dict[f"{question.id}_reason"] = (
                f"검증 패스에서 {question.number}번 답이 답안지에 없음을 확인. "
                f"AI가 제시했던 {graded_score}점은 무효화됨."
            )
        elif exists and (summary == "무응답" or graded_score == 0 and not summary):
            # 반대로 답이 있는데 무응답 처리됐다면 교사 확인만 요청한다.
            result_dict[f"{question.id}_review_required"] = True
            result_dict[f"{question.id}_reason"] = (
                str(result_dict.get(f"{question.id}_reason", "")).strip()
                + f" [검증 패스에서는 답이 존재한다고 판정됨: '{quote}' - 교사 확인 필요]"
            ).strip()


def evaluate_team(provider, config: ProjectConfig,
                   team_num: int, files: list[dict], eval_model):
    """참가자 1명의 자료를 선택된 AI 제공자로 채점."""
    prompt = config.prompt_template or generate_default_prompt(config)
    return provider.evaluate_submission(
        config,
        team_num,
        files,
        prompt,
        eval_model,
        lambda message: broadcast_event("step", {"team": team_num, "step": message}),
    )


def grading_worker(
    project_id: str,
    api_keys: dict,
    delay: int,
    repeat_count: int,
    first_plan: dict,
):
    """성공 결과를 건너뛰고 회차 메타데이터와 함께 채점하는 백그라운드 작업."""
    global grading_state

    config = load_project(project_id)
    if not config:
        broadcast_event("stopped", {"message": "프로젝트를 찾을 수 없습니다."})
        grading_state["running"] = False
        return

    try:
        provider = get_provider(config, api_keys)
    except Exception as e:
        broadcast_event("stopped", {"message": f"AI 제공자 준비 실패: {e}"})
        grading_state["running"] = False
        return

    eval_model = build_evaluation_model(config)
    materials = find_materials(config)
    if not materials:
        broadcast_event("stopped", {"message": "심사자료가 없습니다."})
        grading_state["running"] = False
        return

    total_success = 0
    total_fail = 0
    fatal_message = None
    active_rounds = []

    for loop_idx in range(repeat_count):
        if grading_state["should_stop"]:
            break

        if loop_idx == 0:
            plan = first_plan
            if not load_round_metadata(project_id, int(plan["round_id"])):
                begin_round_attempt(config, plan)
        else:
            time.sleep(2)
            plan = build_grading_plan(
                config,
                delay=delay,
                repeat_count=1,
                new_round=True,
                team_numbers=first_plan.get("repeat_target_team_numbers", []),
            )
            if not plan["can_start"]:
                break
            begin_round_attempt(config, plan)

        current_round = int(plan["round_id"])
        active_rounds.append(current_round)
        grading_state["current_round"] = current_round
        grading_state["run_mode"] = plan.get("mode", "new")
        grading_state["execution_context"] = plan.get("execution_context", {})
        target_numbers = set(plan.get("target_team_numbers", []))
        completed = load_completed(project_id, current_round)
        target_participants = [
            participant
            for participant in materials
            if participant["number"] in target_numbers
            and participant["number"] not in completed
            and participant.get("files")
        ]

        if not target_participants:
            finish_round_attempt(project_id, current_round)
            continue

        grading_state["total_count"] = len(target_participants)
        grading_state["completed_count"] = 0
        grading_state["success_count"] = 0
        grading_state["fail_count"] = 0
        grading_state["target_team_numbers"] = sorted(target_numbers)

        broadcast_event("step", {
            "team": 0,
            "step": (
                f"[{current_round}회차] {len(target_participants)}명 채점 시작 "
                f"({config.ai_provider} / {config.ai_model})"
            ),
        })

        for idx, participant in enumerate(target_participants):
            if grading_state["should_stop"]:
                break

            team_num = participant["number"]
            team_name = participant["name"]
            grading_state["current_team"] = team_num

            broadcast_event("team_start", {
                "team": team_num,
                "name": team_name,
                "index": idx + 1,
                "total": len(target_participants),
                "round": current_round,
            })

            max_retries = 1
            retry_count = 0
            success = False

            while retry_count <= max_retries:
                try:
                    result_dict = evaluate_team(
                        provider, config,
                        team_num, participant["files"], eval_model
                    )

                    # 서술형 시험은 독립 검증 패스로 무응답 문항을 교차 확인한다.
                    if config.project_type == "exam" and config.exam.scored_questions():
                        try:
                            broadcast_event("step", {"team": team_num, "step": "답 존재 여부 검증 중..."})
                            verify_answer_existence(
                                provider, config, participant["files"], result_dict,
                                lambda message: broadcast_event(
                                    "step", {"team": team_num, "step": f"검증: {message}"}
                                ),
                            )
                        except Exception as verify_error:
                            # 검증 실패는 채점 자체를 무효화하지 않는다.
                            broadcast_event("step", {
                                "team": team_num,
                                "step": f"검증 패스 실패(건너뜀): {str(verify_error)[:120]}",
                            })

                    # 소계/합계 계산 추가
                    result_dict = compute_scores(config, result_dict)
                    result_dict["team_name"] = team_name
                    metadata = load_round_metadata(project_id, current_round)
                    execution_context = metadata.get(
                        "execution_context", build_execution_context(config)
                    )
                    result_dict["grading_run"] = {
                        "round_id": current_round,
                        "attempt": len(metadata.get("attempts", [])) or 1,
                        "provider": execution_context.get("provider", config.ai_provider),
                        "model": execution_context.get("model", config.ai_model),
                        "criteria_version": execution_context.get("criteria_version", 0),
                        "criteria_status": execution_context.get("criteria_status", ""),
                        "criteria_fingerprint": execution_context.get(
                            "criteria_fingerprint", ""
                        ),
                        "completed_at": _now_iso(),
                    }

                    save_result(project_id, current_round, result_dict, team_num)
                    clear_round_failure(project_id, current_round, team_num)

                    grading_state["success_count"] += 1
                    broadcast_event("team_done", {
                        "team": team_num,
                        "name": team_name,
                        "score": result_dict.get("total_score", 0),
                        "round": current_round,
                    })
                    success = True
                    break

                except ProviderNeedsUserAction as e:
                    fatal_message = str(e)
                    grading_state["fail_count"] += 1
                    grading_state["should_stop"] = True
                    failure = record_round_failure(
                        project_id,
                        current_round,
                        team_number=team_num,
                        team_name=team_name,
                        error=e,
                    )
                    broadcast_event("team_error", {
                        "team": team_num,
                        "name": team_name,
                        "error": failure["message"],
                        "category": failure["category"],
                        "action": failure["action"],
                        "round": current_round,
                    })
                    break

                except Exception as e:
                    failure = classify_grading_error(e)
                    if failure["retryable"] and retry_count < max_retries:
                        retry_count += 1
                        wait_sec = 15 * retry_count
                        broadcast_event("step", {
                            "team": team_num,
                            "step": (
                                f"{failure['category']} 오류. {wait_sec}초 후 재시도... "
                                f"({retry_count}/{max_retries})"
                            ),
                        })
                        for _ in range(wait_sec):
                            if grading_state["should_stop"]:
                                break
                            time.sleep(1)
                        if grading_state["should_stop"]:
                            break
                    else:
                        grading_state["fail_count"] += 1
                        failure = record_round_failure(
                            project_id,
                            current_round,
                            team_number=team_num,
                            team_name=team_name,
                            error=e,
                        )
                        broadcast_event("team_error", {
                            "team": team_num,
                            "name": team_name,
                            "error": failure["message"],
                            "category": failure["category"],
                            "action": failure["action"],
                            "round": current_round,
                        })
                        break

            if fatal_message:
                break

            if not success or grading_state["should_stop"]:
                if not success and not grading_state["should_stop"]:
                    pass
                if grading_state["should_stop"]:
                    break

            grading_state["completed_count"] = idx + 1

            if idx < len(target_participants) - 1 and not grading_state["should_stop"]:
                broadcast_event("step", {"team": team_num, "step": f"{delay}초 대기 중..."})
                for _ in range(delay):
                    if grading_state["should_stop"]:
                        break
                    time.sleep(1)

        total_success += grading_state["success_count"]
        total_fail += grading_state["fail_count"]
        finish_round_attempt(
            project_id,
            current_round,
            stopped=grading_state["should_stop"],
        )

        if grading_state["should_stop"]:
            break

    grading_state["running"] = False
    grading_state["current_team"] = None
    grading_state["team_started_at"] = None
    if grading_state["should_stop"]:
        message = (
            f"사용자 확인이 필요해 채점을 중단했습니다: {fatal_message}"
            if fatal_message else
            "사용자 요청으로 채점을 중단했습니다."
        )
        broadcast_event("stopped", {"message": message})
    else:
        broadcast_event("finished", {
            "success": total_success,
            "fail": total_fail,
            "rounds": active_rounds,
        })


def _convert_doc_to_pdf(src_path: Path, pdf_path: Path):
    """한컴오피스 한글 COM으로 문서(HWP/HWPX/DOCX/DOC) → PDF 변환"""
    import win32com.client
    
    hwp = None
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        hwp.XHwpWindows.Item(0).Visible = False
        hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
        try:
            hwp.SetAltMode(0)  # 경고 대화상자 억제
        except Exception:
            pass
        hwp.Open(str(src_path), "HWP", "forceopen:true;versionwarning:false")
        hwp.HAction.GetDefault("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
        hwp.HParameterSet.HFileOpenSave.filename = str(pdf_path)
        hwp.HParameterSet.HFileOpenSave.Format = "PDF"
        hwp.HAction.Execute("FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet)
        
        # PDF 저장 완료 대기
        for _ in range(30):
            time.sleep(0.5)
            if pdf_path.exists() and pdf_path.stat().st_size > 500:
                break
        
        hwp.Clear(False)
    finally:
        if hwp:
            try:
                hwp.Quit()
            except Exception:
                pass
