"""프로젝트 개요 화면에 필요한 준비·회차·검토 상태를 계산한다."""

from __future__ import annotations

from config import PROJECTS_DIR  # 기존 테스트·확장 모듈의 경로 주입 호환성 유지
from models.project import ProjectConfig
from services.grading import load_completed, list_round_summaries
from services.submissions import build_submission_status


WORKFLOW_LABELS = {
    "report": "보고서·수행평가",
    "competition": "대회·탐구 심사",
    "exam": "정기고사 서술형",
}


def _round_summaries(
    config: ProjectConfig, participant_count: int
) -> list[dict]:
    summaries = list_round_summaries(
        config, participant_count=participant_count
    )
    for summary in summaries:
        completed = load_completed(config.id, summary["id"])
        values = list(completed.values())
        summary.update({
            "approved_count": sum(
                1 for item in values if item.get("teacher_status") == "approved"
            ),
            "pending_count": sum(
                1 for item in values if item.get("teacher_status") == "pending"
            ),
            "review_required_count": sum(
                1
                for item in values
                if item.get("review_required_count", 0)
                or any(
                    key.endswith("_review_required") and value is True
                    for key, value in item.items()
                )
            ),
        })
    return summaries


def build_project_overview(config: ProjectConfig) -> dict:
    """기존 프로젝트 파일을 변경하지 않고 개요용 파생 상태를 만든다."""
    submission_status = build_submission_status(config)
    submission_summary = submission_status["summary"]
    participant_count = submission_summary["participant_count"]
    material_file_count = submission_summary["file_count"]

    if config.project_type == "exam":
        criteria_count = len(config.exam.scored_questions())
        expected_count = len(config.roster_students) or config.setup.expected_count
        criteria_label = (
            f"{criteria_count}개 문항 준비됨" if criteria_count else "문항·채점기준이 필요함"
        )
    else:
        criteria_count = len(config.all_criteria)
        expected_count = config.setup.expected_count
        criteria_label = (
            f"{criteria_count}개 평가항목 준비됨" if criteria_count else "평가기준이 필요함"
        )

    if criteria_count:
        if config.criteria_state.status == "approved":
            criteria_label += f" · v{config.criteria_state.approved_version} 교사 승인"
        elif config.criteria_state.status in {"generated", "modified", "draft"}:
            criteria_label += " · 승인 필요"
        elif config.criteria_state.status == "unversioned":
            criteria_label += " · 기존 기준"

    rounds = _round_summaries(config, participant_count)
    latest_round = rounds[-1] if rounds else None
    completed_count = latest_round["completed_count"] if latest_round else 0
    approved_count = latest_round["approved_count"] if latest_round else 0
    pending_count = latest_round["pending_count"] if latest_round else 0
    review_required_count = latest_round["review_required_count"] if latest_round else 0

    criteria_ready = criteria_count > 0
    submissions_ready = submission_status["all_ready"]
    grading_started = bool(rounds)
    completed_full_rounds = [
        item
        for item in rounds
        if participant_count
        and item["completed_count"] >= participant_count
        and item.get("failure_count", 0) == 0
    ]
    # AI 신뢰도 비교를 위해 전체 대상 독립 채점 2회를 기본 완료 조건으로 둔다.
    grading_complete = len(completed_full_rounds) >= 2
    if config.project_type == "exam":
        review_complete = grading_complete and completed_count > 0 and approved_count >= completed_count
    else:
        # 보고서 엔진의 교사 승인 모델은 후속 단계에서 추가한다.
        review_complete = grading_complete

    if not criteria_ready:
        next_action = {
            "stage": "criteria",
            "label": "평가기준 준비하기",
            "reason": "채점에 사용할 기준이 아직 없습니다.",
        }
    elif not submissions_ready:
        next_action = {
            "stage": "submissions",
            "label": "학생·답안 준비하기",
            "reason": "채점할 학생 또는 제출 자료를 연결하세요.",
        }
    elif not grading_complete:
        if latest_round and latest_round.get("failure_count", 0):
            reason = (
                f"{latest_round['id']}회차에서 {latest_round['failure_count']}명이 실패했습니다. "
                "성공 결과는 보존되어 있으니 실패 학생만 재시도하세요."
            )
        elif completed_full_rounds:
            reason = (
                f"전체 대상 독립 채점 {len(completed_full_rounds)}/2회 완료. "
                "AI 점수 신뢰도 비교를 위해 다음 회차를 실행하세요."
            )
        elif grading_started:
            target_count = latest_round.get("target_count", participant_count)
            reason = (
                f"최근 {latest_round['id']}회차에서 "
                f"{completed_count}/{target_count}명 성공했습니다."
            )
        else:
            reason = "준비가 끝났습니다. 기본 2회 독립 채점을 시작하세요."
        next_action = {
            "stage": "grading",
            "label": "AI 채점 진행하기",
            "reason": reason,
        }
    elif config.project_type == "exam" and not review_complete:
        next_action = {
            "stage": "review",
            "label": "검토·확정하기",
            "reason": f"{pending_count or (completed_count - approved_count)}명의 교사 확인이 남았습니다.",
        }
    else:
        next_action = {
            "stage": "analysis",
            "label": "결과 분석·내보내기",
            "reason": "현재 회차의 채점과 기본 검토가 완료됐습니다.",
        }

    milestone_flags = [
        criteria_ready,
        submissions_ready,
        grading_complete,
        review_complete,
    ]

    return {
        "project": {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "workflow_type": config.workflow_type,
            "workflow_label": WORKFLOW_LABELS.get(
                config.workflow_type, WORKFLOW_LABELS["report"]
            ),
            "project_type": config.project_type,
            "target": config.setup.target,
            "assessment_name": config.setup.assessment_name,
            "total_max_score": config.total_max_score,
            "updated_at": config.updated_at,
        },
        "progress_percent": round(sum(milestone_flags) / len(milestone_flags) * 100),
        "criteria": {
            "ready": criteria_ready,
            "count": criteria_count,
            "label": criteria_label,
        },
        "submissions": {
            "ready": submissions_ready,
            "participant_count": participant_count,
            "expected_count": expected_count,
            "file_count": material_file_count,
            "attention_count": submission_summary["attention_count"],
            "label": (
                (
                    f"{participant_count}명·{material_file_count}개 파일"
                    + (
                        f" · 확인 {submission_summary['attention_count']}건"
                        if submission_summary["attention_count"]
                        else ""
                    )
                )
                if participant_count
                else "연결된 답안 자료 없음"
            ),
        },
        "grading": {
            "started": grading_started,
            "complete": grading_complete,
            "round_count": len(rounds),
            "completed_full_round_count": len(completed_full_rounds),
            "recommended_full_round_count": 2,
            "latest_completed_count": completed_count,
            "label": (
                (
                    f"기본 독립 채점 {len(completed_full_rounds)}/2회 완료"
                    f" · 최근 {completed_count}/{latest_round.get('target_count', participant_count)}명"
                )
                if rounds
                else "아직 채점하지 않음 · 기본 2회 권장"
            ),
        },
        "review": {
            "complete": review_complete,
            "approved_count": approved_count,
            "pending_count": pending_count,
            "review_required_count": review_required_count,
            "label": (
                f"{approved_count}/{completed_count}명 확정"
                if config.project_type == "exam" and completed_count
                else (
                    f"검토할 결과 {completed_count}명"
                    if completed_count
                    else "채점 결과 없음"
                )
            ),
        },
        "rounds": rounds,
        "next_action": next_action,
    }
