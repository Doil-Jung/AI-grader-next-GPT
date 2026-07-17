"""
AI 채점 엔진
- Gemini, OpenAI, Anthropic 다중 모델 지원
- SSE 기반 실시간 진행 브로드캐스트
"""
import json
import time
import shutil
import threading
import traceback
from pathlib import Path
from queue import Queue

from models.project import ProjectConfig, load_project, generate_default_prompt
from models.evaluation import build_evaluation_model, compute_scores
from services.file_manager import find_materials, get_participant_files
from config import PROJECTS_DIR
from services.providers import get_provider
from services.providers.base import ProviderNeedsUserAction


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
    """채점 결과 저장"""
    round_dir = get_round_dir(project_id, round_id)
    round_dir.mkdir(parents=True, exist_ok=True)
    filepath = round_dir / f"team_{team_number:03d}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)


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


def grading_worker(project_id: str, api_keys: dict, start_from: int, delay: int, repeat_count: int, team_numbers: list[int] = None):
    """백그라운드 채점 쓰레드"""
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
    
    # 동적 Pydantic 모델 생성
    eval_model = build_evaluation_model(config)
    
    # 심사자료 로드
    materials = find_materials(config)
    if not materials:
        broadcast_event("stopped", {"message": "심사자료가 없습니다."})
        grading_state["running"] = False
        return
    
    total_success = 0
    total_fail = 0
    fatal_message = None
    
    for loop_idx in range(repeat_count):
        if grading_state["should_stop"]:
            broadcast_event("stopped", {"message": "사용자에 의해 중단됨"})
            break
        
        if loop_idx > 0:
            next_id = grading_state["current_round"] + 1
            grading_state["current_round"] = next_id
            get_round_dir(project_id, next_id).mkdir(parents=True, exist_ok=True)
            time.sleep(2)
        
        completed = load_completed(project_id, grading_state["current_round"])
        
        # 채점 대상 필터
        if team_numbers:
            # 특정 번호가 지정된 경우 (개별/선택 채점)
            target_participants = [
                p for p in materials
                if p["number"] in team_numbers
                and len(p["files"]) > 0
            ]
        else:
            # 전체 채점 (start_from 이후, 미완료 대상)
            target_participants = [
                p for p in materials
                if p["number"] not in completed
                and p["number"] >= start_from
                and len(p["files"]) > 0
            ]
        
        if not target_participants:
            continue
        
        grading_state["total_count"] = len(target_participants)
        grading_state["completed_count"] = 0
        grading_state["success_count"] = 0
        grading_state["fail_count"] = 0
        
        broadcast_event("step", {"team": 0, "step": f"[{grading_state['current_round']}회차] 채점 시작..."})
        
        for idx, participant in enumerate(target_participants):
            if grading_state["should_stop"]:
                broadcast_event("stopped", {"message": "사용자에 의해 중단됨"})
                break
            
            team_num = participant["number"]
            team_name = participant["name"]
            grading_state["current_team"] = team_num
            
            broadcast_event("team_start", {
                "team": team_num,
                "name": team_name,
                "index": idx + 1,
                "total": len(target_participants),
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
                    
                    save_result(project_id, grading_state["current_round"], result_dict, team_num)
                    
                    grading_state["success_count"] += 1
                    broadcast_event("team_done", {
                        "team": team_num,
                        "name": team_name,
                        "score": result_dict.get("total_score", 0),
                    })
                    success = True
                    break

                except ProviderNeedsUserAction as e:
                    # 로그인 만료나 웹 사용량 제한은 뒤 학생에게도 동일하게
                    # 발생하므로, 한 명씩 계속 실패시키지 않고 즉시 멈춘다.
                    fatal_message = str(e)
                    grading_state["fail_count"] += 1
                    grading_state["should_stop"] = True
                    broadcast_event("team_error", {
                        "team": team_num,
                        "name": team_name,
                        "error": fatal_message[:300],
                    })
                    break

                except Exception as e:
                    error_str = str(e)
                    retryable = any(k in error_str.lower() for k in [
                        "503", "429", "quota", "disconnected", "timeout", "timed out",
                        "시간 초과", "overloaded", "일시적인 응답 오류", "생성이 취소",
                        "something went wrong", "문제가 발생",
                    ])
                    
                    if retryable and retry_count < max_retries:
                        retry_count += 1
                        wait_sec = 15 * retry_count
                        broadcast_event("step", {
                            "team": team_num,
                            "step": f"AI 처리 오류. {wait_sec}초 후 재시도... ({retry_count}/{max_retries})"
                        })
                        for _ in range(wait_sec):
                            if grading_state["should_stop"]:
                                break
                            time.sleep(1)
                        if grading_state["should_stop"]:
                            break
                    else:
                        grading_state["fail_count"] += 1
                        broadcast_event("team_error", {
                            "team": team_num,
                            "name": team_name,
                            "error": error_str[:200],
                        })
                        break
            
            if fatal_message:
                break

            if not success or grading_state["should_stop"]:
                if not success and not grading_state["should_stop"]:
                    # 복구불가 에러 시 다음 팀으로 넘어감 (중단하지 않음)
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
        broadcast_event("finished", {"success": total_success, "fail": total_fail})


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
