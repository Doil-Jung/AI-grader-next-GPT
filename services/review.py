"""다회차 AI 점수, 교사 수동 점수와 최종 확정 점수를 분리해 관리한다."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime
from pathlib import Path

from models.project import ProjectConfig
from services import grading as grading_service
from services.grading import list_round_summaries, load_completed


REVIEW_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _project_path(project_id: str, filename: str) -> Path:
    return grading_service.PROJECTS_DIR / project_id / filename


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value, *, allow_none: bool = False) -> float | None:
    if value in (None, "") and allow_none:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        if allow_none:
            return None
        raise ValueError("점수는 숫자로 입력하세요.")
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("점수는 유한한 숫자로 입력하세요.")
    return round(result, 4)


def scoring_items(config: ProjectConfig) -> list[dict]:
    if config.project_type == "exam":
        return [
            {
                "id": question.id,
                "label": f"{question.number}번",
                "name": question.question_text,
                "max_score": float(question.max_score),
            }
            for question in config.exam.scored_questions()
        ]
    return [
        {
            "id": criterion.id,
            "label": criterion.name,
            "name": f"{category.name} · {criterion.description}",
            "max_score": float(criterion.max_score),
        }
        for category in config.categories
        for criterion in category.criteria
    ]


def project_max_score(config: ProjectConfig) -> float:
    item_total = sum(item["max_score"] for item in scoring_items(config))
    return item_total if item_total > 0 else float(config.total_max_score or 0)


def load_manual_scores(project_id: str) -> dict[int, dict]:
    """구형 ``번호: 점수``와 새 상세 수동 점수 형식을 모두 읽는다."""
    path = _project_path(project_id, "manual_scores.json")
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("students"), dict):
        payload = payload["students"]

    normalized = {}
    for raw_number, value in payload.items():
        try:
            team_number = int(raw_number)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            item_scores = {}
            for item_id, score in (value.get("item_scores") or {}).items():
                parsed = _number(score, allow_none=True)
                if parsed is not None:
                    item_scores[str(item_id)] = parsed
            total_score = _number(value.get("total_score"), allow_none=True)
            if total_score is None and item_scores:
                total_score = round(sum(item_scores.values()), 4)
            normalized[team_number] = {
                "total_score": total_score,
                "item_scores": item_scores,
                "source": str(value.get("source", "manual")),
                "updated_at": str(value.get("updated_at", "")),
            }
        else:
            total_score = _number(value, allow_none=True)
            if total_score is not None:
                normalized[team_number] = {
                    "total_score": total_score,
                    "item_scores": {},
                    "source": "legacy",
                    "updated_at": "",
                }
    return normalized


def save_manual_scores(project_id: str, scores: dict[int, dict]) -> None:
    payload = {
        str(team_number): {
            "total_score": value.get("total_score"),
            "item_scores": value.get("item_scores", {}),
            "source": value.get("source", "manual"),
            "updated_at": value.get("updated_at", ""),
        }
        for team_number, value in sorted(scores.items())
    }
    _atomic_json_write(_project_path(project_id, "manual_scores.json"), payload)


def load_review_state(project_id: str) -> dict:
    path = _project_path(project_id, "review_state.json")
    if not path.exists():
        return {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "updated_at": "",
            "students": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", REVIEW_SCHEMA_VERSION)
    payload.setdefault("updated_at", "")
    payload.setdefault("students", {})
    return payload


def save_review_state(project_id: str, state: dict) -> None:
    state["schema_version"] = REVIEW_SCHEMA_VERSION
    state["updated_at"] = _now_iso()
    _atomic_json_write(_project_path(project_id, "review_state.json"), state)


def _validate_scores(
    config: ProjectConfig,
    *,
    total_score,
    item_scores: dict | None,
    require_total: bool,
) -> tuple[float | None, dict[str, float]]:
    items = {item["id"]: item for item in scoring_items(config)}
    normalized_items = {}
    for item_id, value in (item_scores or {}).items():
        if item_id not in items:
            raise ValueError(f"알 수 없는 평가 항목입니다: {item_id}")
        score = _number(value)
        maximum = items[item_id]["max_score"]
        if score < 0 or score > maximum:
            raise ValueError(
                f"{items[item_id]['label']} 점수는 0~{maximum:g}점이어야 합니다."
            )
        normalized_items[item_id] = score

    normalized_total = _number(total_score, allow_none=not require_total)
    if normalized_total is None and normalized_items:
        normalized_total = round(sum(normalized_items.values()), 4)
    if require_total and normalized_total is None:
        raise ValueError("최종 확정 총점을 입력하세요.")
    maximum_total = project_max_score(config)
    if (
        normalized_total is not None
        and (normalized_total < 0 or normalized_total > maximum_total)
    ):
        raise ValueError(f"총점은 0~{maximum_total:g}점이어야 합니다.")
    if (
        normalized_items
        and len(normalized_items) == len(items)
        and normalized_total is not None
    ):
        item_total = round(sum(normalized_items.values()), 4)
        if abs(item_total - normalized_total) > 0.01:
            raise ValueError(
                f"항목별 점수 합계 {item_total:g}점과 총점 "
                f"{normalized_total:g}점이 다릅니다."
            )
    return normalized_total, normalized_items


def set_manual_score(
    config: ProjectConfig,
    team_number: int,
    *,
    total_score=None,
    item_scores: dict | None = None,
    source: str = "direct",
) -> dict:
    total, items = _validate_scores(
        config,
        total_score=total_score,
        item_scores=item_scores,
        require_total=False,
    )
    if total is None and not items:
        raise ValueError("수동 총점 또는 항목별 점수를 하나 이상 입력하세요.")
    scores = load_manual_scores(config.id)
    before = scores.get(int(team_number))
    entry = {
        "total_score": total,
        "item_scores": items,
        "source": source,
        "updated_at": _now_iso(),
    }
    scores[int(team_number)] = entry
    save_manual_scores(config.id, scores)

    state = load_review_state(config.id)
    student = state["students"].setdefault(str(int(team_number)), {})
    audit = student.setdefault("audit_log", [])
    audit.append({
        "timestamp": entry["updated_at"],
        "action": "manual_score_saved",
        "before": before,
        "after": entry,
    })
    save_review_state(config.id, state)
    return entry


def import_manual_totals(
    config: ProjectConfig,
    values: dict[int, float],
    *,
    source: str = "excel",
) -> dict[int, dict]:
    existing = load_manual_scores(config.id)
    state = load_review_state(config.id)
    now = _now_iso()
    maximum = project_max_score(config)
    imported = {}
    for team_number, value in values.items():
        score = _number(value)
        if score < 0 or score > maximum:
            continue
        previous = existing.get(int(team_number))
        entry = {
            "total_score": score,
            "item_scores": (previous or {}).get("item_scores", {}),
            "source": source,
            "updated_at": now,
        }
        existing[int(team_number)] = entry
        imported[int(team_number)] = entry
        student = state["students"].setdefault(str(int(team_number)), {})
        student.setdefault("audit_log", []).append({
            "timestamp": now,
            "action": "manual_score_imported",
            "before": previous,
            "after": entry,
        })
    save_manual_scores(config.id, existing)
    if imported:
        save_review_state(config.id, state)
    return imported


def _round_score(result: dict, key: str = "total_score"):
    original = result.get("ai_original")
    if isinstance(original, dict) and key in original:
        return original.get(key)
    return result.get(key)


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _score_stats(values: list[float]) -> dict:
    if not values:
        return {
            "average": None,
            "median": None,
            "std_dev": 0.0,
            "score_range": 0.0,
        }
    return {
        "average": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "std_dev": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
        "score_range": round(max(values) - min(values), 2),
    }


def build_review_dashboard(
    config: ProjectConfig,
    *,
    round_ids: list[int] | None = None,
    participant_numbers: list[int] | None = None,
    std_threshold: float = 1.5,
    range_threshold: float = 2.0,
    manual_diff_threshold: float = 2.0,
) -> dict:
    round_summaries = [
        summary
        for summary in list_round_summaries(config)
        if summary["completed_count"] > 0
    ]
    available_round_ids = [summary["id"] for summary in round_summaries]
    if round_ids is None:
        selected_round_ids = available_round_ids
    else:
        selected_round_ids = sorted({
            int(round_id)
            for round_id in round_ids
            if int(round_id) in available_round_ids
        })

    results_by_round = {
        round_id: load_completed(config.id, round_id)
        for round_id in selected_round_ids
    }
    manuals = load_manual_scores(config.id)
    state = load_review_state(config.id)
    configured_numbers = {int(value) for value in (participant_numbers or [])}
    team_numbers = set(configured_numbers) | set(manuals)
    for completed in results_by_round.values():
        team_numbers.update(int(number) for number in completed)
    team_numbers.update(
        int(number)
        for number in state.get("students", {})
        if str(number).isdigit()
    )

    item_definitions = scoring_items(config)
    students = []
    for team_number in sorted(team_numbers):
        name = f"참가자 {team_number}"
        scores_by_round = {}
        adjusted_scores_by_round = {}
        item_round_values = {item["id"]: {} for item in item_definitions}
        provider_review_count = 0
        low_confidence_count = 0
        for round_id, completed in results_by_round.items():
            result = completed.get(team_number)
            if not result:
                continue
            name = result.get("team_name") or name
            raw_total = _number(_round_score(result), allow_none=True)
            adjusted_total = _number(result.get("total_score"), allow_none=True)
            if raw_total is not None:
                scores_by_round[round_id] = raw_total
            if (
                adjusted_total is not None
                and raw_total is not None
                and abs(adjusted_total - raw_total) > 0.001
            ):
                adjusted_scores_by_round[round_id] = adjusted_total
            for item in item_definitions:
                score = _number(_round_score(result, item["id"]), allow_none=True)
                if score is not None:
                    item_round_values[item["id"]][round_id] = score
                if bool(result.get(f"{item['id']}_review_required", False)):
                    provider_review_count += 1
                confidence = _number(
                    result.get(f"{item['id']}_confidence"), allow_none=True
                )
                if confidence is not None and confidence < 0.6:
                    low_confidence_count += 1

        total_values = list(scores_by_round.values())
        total_stats = _score_stats(total_values)
        manual = manuals.get(team_number, {
            "total_score": None,
            "item_scores": {},
            "source": "",
            "updated_at": "",
        })
        manual_total = manual.get("total_score")
        ai_manual_difference = (
            round(total_stats["average"] - manual_total, 2)
            if total_stats["average"] is not None and manual_total is not None
            else None
        )
        reasons = []
        if len(total_values) < 2:
            reasons.append({
                "code": "insufficient_rounds",
                "label": f"독립 채점 {len(total_values)}/2회",
            })
        missing_rounds = [
            round_id
            for round_id in selected_round_ids
            if round_id not in scores_by_round
        ]
        if missing_rounds:
            reasons.append({
                "code": "missing_rounds",
                "label": "미채점 회차 " + ", ".join(map(str, missing_rounds)),
            })
        if total_stats["std_dev"] >= max(0.0, std_threshold):
            reasons.append({
                "code": "high_std_dev",
                "label": f"표준편차 {total_stats['std_dev']:.2f}점",
            })
        if total_stats["score_range"] >= max(0.0, range_threshold):
            reasons.append({
                "code": "high_range",
                "label": f"회차 차이 {total_stats['score_range']:.2f}점",
            })
        if (
            ai_manual_difference is not None
            and abs(ai_manual_difference) >= max(0.0, manual_diff_threshold)
        ):
            reasons.append({
                "code": "manual_difference",
                "label": f"AI-수동 차이 {ai_manual_difference:+.2f}점",
            })
        if provider_review_count:
            reasons.append({
                "code": "provider_review",
                "label": f"AI 확인 필요 {provider_review_count}건",
            })
        if low_confidence_count:
            reasons.append({
                "code": "low_confidence",
                "label": f"낮은 확신도 {low_confidence_count}건",
            })

        item_rows = []
        for item in item_definitions:
            values_by_round = item_round_values[item["id"]]
            stats = _score_stats(list(values_by_round.values()))
            manual_item = manual.get("item_scores", {}).get(item["id"])
            item_rows.append({
                **item,
                "scores_by_round": values_by_round,
                "ai_average": stats["average"],
                "ai_median": stats["median"],
                "std_dev": stats["std_dev"],
                "score_range": stats["score_range"],
                "manual_score": manual_item,
                "ai_manual_difference": (
                    round(stats["average"] - manual_item, 2)
                    if stats["average"] is not None and manual_item is not None
                    else None
                ),
                "suggested_score": stats["median"],
            })
        item_suggestions = [
            item["suggested_score"]
            for item in item_rows
            if item["suggested_score"] is not None
        ]
        ai_suggested_score = (
            round(sum(item_suggestions), 2)
            if item_rows and len(item_suggestions) == len(item_rows)
            else total_stats["median"]
        )

        student_state = state.get("students", {}).get(str(team_number), {})
        decision = dict(student_state.get("decision") or {"status": "pending"})
        source_payload = {
            "round_ids": selected_round_ids,
            "scores_by_round": scores_by_round,
            "manual_total_score": manual_total,
            "manual_item_scores": manual.get("item_scores", {}),
        }
        source_fingerprint = _fingerprint(source_payload)
        decision_basis = {
            int(round_id)
            for round_id in decision.get("basis_rounds", [])
        }
        selected_basis = set(selected_round_ids)
        comparable_to_approval = (
            not decision_basis
            or decision_basis.issubset(selected_basis)
        )
        decision_stale = bool(
            decision.get("status") == "approved"
            and comparable_to_approval
            and decision.get("source_fingerprint")
            and decision.get("source_fingerprint") != source_fingerprint
        )
        if decision_stale:
            reasons.append({
                "code": "approved_data_changed",
                "label": "확정 후 비교 자료 변경",
            })
        critical_codes = {"manual_difference", "approved_data_changed"}
        priority = (
            "critical"
            if any(reason["code"] in critical_codes for reason in reasons)
            else ("attention" if reasons else "normal")
        )
        final_item_scores = decision.get("item_scores", {})
        for item in item_rows:
            item["final_score"] = final_item_scores.get(item["id"])

        students.append({
            "team_number": team_number,
            "team_name": name,
            "scores_by_round": scores_by_round,
            "adjusted_scores_by_round": adjusted_scores_by_round,
            "round_count": len(total_values),
            "ai_average": total_stats["average"],
            "ai_median": total_stats["median"],
            "ai_suggested_score": ai_suggested_score,
            "std_dev": total_stats["std_dev"],
            "score_range": total_stats["score_range"],
            "manual_score": manual_total,
            "manual_source": manual.get("source", ""),
            "manual_updated_at": manual.get("updated_at", ""),
            "ai_manual_difference": ai_manual_difference,
            "items": item_rows,
            "review_reasons": reasons,
            "review_required": bool(reasons),
            "priority": priority,
            "decision": decision,
            "decision_stale": decision_stale,
            "source_fingerprint": source_fingerprint,
            "audit_log": student_state.get("audit_log", []),
        })

    priority_order = {"critical": 0, "attention": 1, "normal": 2}
    students.sort(key=lambda item: (
        item.get("decision", {}).get("status") == "approved",
        priority_order[item["priority"]],
        item["team_number"],
    ))
    approved_count = sum(
        1
        for student in students
        if student.get("decision", {}).get("status") == "approved"
    )
    stale_count = sum(1 for student in students if student["decision_stale"])
    return {
        "project_id": config.id,
        "project_type": config.project_type,
        "rounds": round_summaries,
        "selected_round_ids": selected_round_ids,
        "thresholds": {
            "std_dev": max(0.0, std_threshold),
            "score_range": max(0.0, range_threshold),
            "manual_difference": max(0.0, manual_diff_threshold),
        },
        "max_score": project_max_score(config),
        "students": students,
        "summary": {
            "student_count": len(students),
            "approved_count": approved_count,
            "effective_approved_count": max(0, approved_count - stale_count),
            "pending_count": len(students) - approved_count,
            "attention_count": sum(
                1 for student in students if student["review_required"]
            ),
            "manual_count": sum(
                1 for student in students if student["manual_score"] is not None
            ),
            "stale_count": stale_count,
        },
    }


def approve_final_score(
    config: ProjectConfig,
    team_number: int,
    *,
    final_total_score,
    item_scores: dict | None,
    teacher_note: str,
    decision_source: str,
    basis_rounds: list[int] | None,
    participant_numbers: list[int] | None = None,
) -> dict:
    total, normalized_items = _validate_scores(
        config,
        total_score=final_total_score,
        item_scores=item_scores,
        require_total=True,
    )
    dashboard = build_review_dashboard(
        config,
        round_ids=basis_rounds,
        participant_numbers=participant_numbers,
    )
    student = next(
        (
            value
            for value in dashboard["students"]
            if value["team_number"] == int(team_number)
        ),
        None,
    )
    if student is None:
        raise ValueError("확정할 학생의 채점 또는 수동 점수 자료가 없습니다.")
    allowed_sources = {"ai_suggested", "manual", "custom"}
    source = decision_source if decision_source in allowed_sources else "custom"
    if source == "ai_suggested":
        suggested = student.get("ai_suggested_score")
        if suggested is None:
            raise ValueError("AI 종합 제안 점수가 없어 이 근거로 확정할 수 없습니다.")
        if abs(total - suggested) > 0.01:
            raise ValueError(
                "AI 제안과 다른 점수입니다. 확정 근거를 '교사 직접 결정'으로 선택하세요."
            )
    elif source == "manual":
        manual = student.get("manual_score")
        if manual is None:
            raise ValueError("저장된 교사 수동 점수가 없습니다.")
        if abs(total - manual) > 0.01:
            raise ValueError(
                "수동 점수와 다른 값입니다. 확정 근거를 '교사 직접 결정'으로 선택하세요."
            )
    now = _now_iso()
    state = load_review_state(config.id)
    student_state = state["students"].setdefault(str(int(team_number)), {})
    previous = student_state.get("decision")
    decision = {
        "status": "approved",
        "total_score": total,
        "item_scores": normalized_items,
        "decision_source": source,
        "teacher_note": str(teacher_note or ""),
        "basis_rounds": dashboard["selected_round_ids"],
        "approved_at": now,
        "source_fingerprint": student["source_fingerprint"],
        "snapshot": {
            "ai_average": student["ai_average"],
            "ai_median": student["ai_median"],
            "ai_suggested_score": student["ai_suggested_score"],
            "manual_score": student["manual_score"],
            "std_dev": student["std_dev"],
            "score_range": student["score_range"],
        },
    }
    student_state["decision"] = decision
    student_state.setdefault("audit_log", []).append({
        "timestamp": now,
        "action": "final_score_approved",
        "before": previous,
        "after": decision,
    })
    save_review_state(config.id, state)
    return decision


def reopen_final_score(
    config: ProjectConfig,
    team_number: int,
    *,
    reason: str = "",
) -> dict:
    state = load_review_state(config.id)
    student = state["students"].setdefault(str(int(team_number)), {})
    previous = student.get("decision")
    if not previous or previous.get("status") != "approved":
        raise ValueError("이미 확정 대기 상태입니다.")
    now = _now_iso()
    decision = {
        **previous,
        "status": "pending",
        "reopened_at": now,
        "reopen_reason": str(reason or ""),
    }
    student["decision"] = decision
    student.setdefault("audit_log", []).append({
        "timestamp": now,
        "action": "final_score_reopened",
        "reason": str(reason or ""),
        "before": previous,
        "after": decision,
    })
    save_review_state(config.id, state)
    return decision
