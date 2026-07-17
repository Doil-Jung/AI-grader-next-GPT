"""선채점 결과로 평가기준 초안을 만들고 승인·표본 검증 이력을 보존한다.

AI가 생성한 초안은 이 저장소에만 기록하며 프로젝트의 실제 평가기준을 바꾸지 않는다.
교사가 별도 승인한 경우에만 app 계층이 초안을 새 평가기준 버전으로 적용한다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import statistics
import uuid
from datetime import datetime
from pathlib import Path

from models.project import ProjectConfig, ScoringElement, generate_default_prompt
from services import grading as grading_service
from services.grading import list_round_summaries, load_completed
from services.review import load_manual_scores, scoring_items


STANDARDIZATION_SCHEMA_VERSION = 1
FILENAME = "standardizations.json"
SESSION_STATUSES = {"draft", "approved", "discarded"}
EVIDENCE_LIMIT_PER_ITEM = 12
PROMPT_ROUNDS_PER_STUDENT = 3
PROMPT_TEXT_LIMIT = 320


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _path(project_id: str) -> Path:
    return grading_service.PROJECTS_DIR / project_id / FILENAME


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _fingerprint(payload) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 4)


def _unique_text(values, *, limit: int = 30) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text[:1000])
        if len(result) >= limit:
            break
    return result


def load_store(project_id: str) -> dict:
    path = _path(project_id)
    if not path.exists():
        return {
            "schema_version": STANDARDIZATION_SCHEMA_VERSION,
            "updated_at": "",
            "sessions": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sessions = [
        session
        for session in payload.get("sessions", [])
        if isinstance(session, dict) and session.get("id")
    ]
    return {
        "schema_version": STANDARDIZATION_SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at", "")),
        "sessions": sessions,
    }


def save_store(project_id: str, store: dict) -> None:
    store["schema_version"] = STANDARDIZATION_SCHEMA_VERSION
    store["updated_at"] = _now_iso()
    _atomic_json_write(_path(project_id), store)


def get_session(project_id: str, session_id: str) -> dict | None:
    return next(
        (
            session
            for session in load_store(project_id)["sessions"]
            if session.get("id") == session_id
        ),
        None,
    )


def session_summary(session: dict) -> dict:
    return {
        "id": session.get("id", ""),
        "created_at": session.get("created_at", ""),
        "updated_at": session.get("updated_at", ""),
        "project_type": session.get("project_type", ""),
        "status": session.get("status", "draft"),
        "source_round_ids": session.get("source_round_ids", []),
        "source_criteria_versions": session.get("source_criteria_versions", []),
        "student_count": int(session.get("student_count", 0) or 0),
        "observation_count": int(session.get("observation_count", 0) or 0),
        "teacher_instruction": session.get("teacher_instruction", ""),
        "approved_at": session.get("approved_at", ""),
        "approved_version": int(session.get("approved_version", 0) or 0),
        "teacher_note": session.get("teacher_note", ""),
        "recommended_sample_teams": session.get(
            "recommended_sample_teams", []
        ),
        "draft_validation": session.get("draft_validation", {}),
    }


def _raw_result(result: dict) -> dict:
    original = result.get("ai_original")
    return original if isinstance(original, dict) else result


def _anonymized_text(value, result: dict, alias: str) -> str:
    text = str(value or "").strip()
    names = {
        str(result.get("team_name", "")).strip(),
        str(_raw_result(result).get("team_name", "")).strip(),
    }
    for name in sorted((name for name in names if name), key=len, reverse=True):
        text = text.replace(name, alias)
    return text


def _score_stats(values: list[float]) -> dict:
    if not values:
        return {
            "average": None,
            "median": None,
            "std_dev": 0.0,
            "range": 0.0,
        }
    return {
        "average": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "std_dev": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
        "range": round(max(values) - min(values), 2),
    }


def _round_contexts(config: ProjectConfig, round_ids: list[int]) -> list[dict]:
    summaries = {
        int(summary["id"]): summary
        for summary in list_round_summaries(config)
    }
    return [
        {
            "round_id": round_id,
            "provider": summaries.get(round_id, {}).get("provider", ""),
            "model": summaries.get(round_id, {}).get("model", ""),
            "criteria_version": int(
                summaries.get(round_id, {}).get("criteria_version", 0) or 0
            ),
            "criteria_status": summaries.get(round_id, {}).get(
                "criteria_status", ""
            ),
            "criteria_fingerprint": grading_service.load_round_metadata(
                config.id, round_id
            ).get("execution_context", {}).get("criteria_fingerprint", ""),
        }
        for round_id in round_ids
    ]


def _normalize_round_ids(config: ProjectConfig, round_ids) -> list[int]:
    available = {
        int(summary["id"])
        for summary in list_round_summaries(config)
        if int(summary.get("completed_count", 0) or 0) > 0
    }
    normalized = []
    for value in round_ids or []:
        try:
            round_id = int(value)
        except (TypeError, ValueError):
            continue
        if round_id in available and round_id not in normalized:
            normalized.append(round_id)
    normalized.sort()
    if not normalized:
        raise ValueError("기준화에 사용할 완료 회차를 하나 이상 선택하세요.")
    return normalized


def _pick_representative_teams(
    totals_by_team: dict[int, list[float]],
    review_counts: dict[int, int],
    manuals: dict[int, dict],
    *,
    limit: int = 5,
) -> list[dict]:
    if not totals_by_team:
        return []
    medians = {
        team: statistics.median(scores)
        for team, scores in totals_by_team.items()
        if scores
    }
    ordered = sorted(medians, key=lambda team: (medians[team], team))
    reasons: dict[int, list[str]] = {}

    def add(team: int | None, reason: str) -> None:
        if team is None or team not in medians:
            return
        reasons.setdefault(team, [])
        if reason not in reasons[team]:
            reasons[team].append(reason)

    if ordered:
        add(ordered[0], "낮은 점수대 대표")
        add(ordered[len(ordered) // 2], "중간 점수대 대표")
        add(ordered[-1], "높은 점수대 대표")

    disagreement = sorted(
        totals_by_team,
        key=lambda team: (
            max(totals_by_team[team]) - min(totals_by_team[team])
            if len(totals_by_team[team]) > 1
            else 0,
            review_counts.get(team, 0),
        ),
        reverse=True,
    )
    if disagreement:
        spread = (
            max(totals_by_team[disagreement[0]])
            - min(totals_by_team[disagreement[0]])
        )
        if spread > 0:
            add(disagreement[0], f"회차 차이 {spread:g}점")

    manual_candidates = []
    for team, scores in totals_by_team.items():
        manual = _number(manuals.get(team, {}).get("total_score"))
        if manual is None or not scores:
            continue
        manual_candidates.append(
            (abs(statistics.median(scores) - manual), team)
        )
    if manual_candidates:
        difference, team = max(manual_candidates)
        if difference > 0:
            add(team, f"AI-수동 차이 {difference:g}점")

    flagged = max(
        review_counts,
        key=lambda team: review_counts.get(team, 0),
        default=None,
    )
    if flagged is not None and review_counts.get(flagged, 0):
        add(flagged, f"AI 확인 필요 {review_counts[flagged]}건")

    priority = sorted(
        reasons,
        key=lambda team: (
            any("회차 차이" in reason for reason in reasons[team]),
            any("AI-수동" in reason for reason in reasons[team]),
            any("AI 확인" in reason for reason in reasons[team]),
            len(reasons[team]),
            -team,
        ),
        reverse=True,
    )
    for team in ordered:
        if team not in priority:
            priority.append(team)
    return [
        {"team_number": team, "reasons": reasons.get(team, ["점수대 대표"])}
        for team in priority[:limit]
    ]


def _representative_team_numbers(team_evidence: list[dict]) -> set[int]:
    if len(team_evidence) <= EVIDENCE_LIMIT_PER_ITEM:
        return {int(item["team_number"]) for item in team_evidence}

    selected = set()
    ranked = sorted(
        team_evidence,
        key=lambda item: (
            bool(item.get("manual_score") is not None),
            bool(item.get("teacher_adjustments")),
            int(item.get("review_count", 0)),
            float(item.get("score_range", 0)),
        ),
        reverse=True,
    )
    selected.update(
        int(item["team_number"])
        for item in ranked[: max(6, EVIDENCE_LIMIT_PER_ITEM // 2)]
    )
    by_score = sorted(
        team_evidence,
        key=lambda item: (
            item.get("median_score")
            if item.get("median_score") is not None
            else float("-inf")
        ),
    )
    if by_score:
        indexes = {
            0,
            len(by_score) // 4,
            len(by_score) // 2,
            (len(by_score) * 3) // 4,
            len(by_score) - 1,
        }
        selected.update(
            int(by_score[index]["team_number"])
            for index in indexes
        )
    for item in ranked:
        if len(selected) >= EVIDENCE_LIMIT_PER_ITEM:
            break
        selected.add(int(item["team_number"]))
    return selected


def _representative_observations(observations: list[dict]) -> list[dict]:
    if len(observations) <= PROMPT_ROUNDS_PER_STUDENT:
        return observations
    selected_indexes = {
        min(range(len(observations)), key=lambda index: observations[index]["score"]),
        max(range(len(observations)), key=lambda index: observations[index]["score"]),
        len(observations) - 1,
    }
    if len(selected_indexes) < PROMPT_ROUNDS_PER_STUDENT:
        selected_indexes.add(len(observations) // 2)
    return [
        observations[index]
        for index in sorted(selected_indexes)[:PROMPT_ROUNDS_PER_STUDENT]
    ]


def collect_evidence(config: ProjectConfig, round_ids) -> dict:
    """여러 회차를 같은 학생 단위로 묶고 AI 분석용 가명 증거를 만든다."""
    selected_round_ids = _normalize_round_ids(config, round_ids)
    contexts = _round_contexts(config, selected_round_ids)
    fingerprints = {
        context["criteria_fingerprint"]
        for context in contexts
        if context["criteria_fingerprint"]
    }
    versions = sorted({
        int(context["criteria_version"])
        for context in contexts
    })
    if len(fingerprints) > 1:
        raise ValueError(
            "서로 다른 평가기준으로 실행한 회차가 섞여 있습니다. "
            "같은 기준으로 채점한 회차만 선택하세요."
        )

    results_by_round = {
        round_id: load_completed(config.id, round_id)
        for round_id in selected_round_ids
    }
    team_numbers = sorted({
        int(team)
        for completed in results_by_round.values()
        for team in completed
    })
    if not team_numbers:
        raise ValueError("선택한 회차에 분석할 학생 결과가 없습니다.")
    aliases = {
        team: f"A{index:03d}"
        for index, team in enumerate(team_numbers, 1)
    }
    manuals = load_manual_scores(config.id)
    items = scoring_items(config)
    totals_by_team: dict[int, list[float]] = {
        team: [] for team in team_numbers
    }
    review_counts = {team: 0 for team in team_numbers}
    item_evidence = []
    observation_count = 0

    for team in team_numbers:
        for round_id, completed in results_by_round.items():
            result = completed.get(team)
            if not result:
                continue
            raw = _raw_result(result)
            total = _number(raw.get("total_score"))
            if total is not None:
                totals_by_team[team].append(total)
            if config.project_type == "exam":
                review_counts[team] += sum(
                    1
                    for item in items
                    if bool(raw.get(f"{item['id']}_review_required", False))
                )

    for item in items:
        teams = []
        all_scores = []
        for team in team_numbers:
            observations = []
            teacher_adjustments = []
            item_review_count = 0
            for round_id, completed in results_by_round.items():
                result = completed.get(team)
                if not result:
                    continue
                raw = _raw_result(result)
                raw_score = _number(raw.get(item["id"]))
                if raw_score is None:
                    continue
                all_scores.append(raw_score)
                observation_count += 1
                adjusted_score = _number(result.get(item["id"]))
                if adjusted_score is not None and adjusted_score != raw_score:
                    teacher_adjustments.append({
                        "round_id": round_id,
                        "ai_score": raw_score,
                        "teacher_adjusted_score": adjusted_score,
                    })
                review_required = bool(
                    raw.get(f"{item['id']}_review_required", False)
                )
                item_review_count += int(review_required)
                observation = {
                    "round_id": round_id,
                    "score": raw_score,
                    "reason": _anonymized_text(
                        raw.get(f"{item['id']}_reason", ""),
                        result,
                        aliases[team],
                    )[:PROMPT_TEXT_LIMIT],
                }
                if config.project_type == "exam":
                    observation.update({
                        "answer_summary": _anonymized_text(
                            raw.get(f"{item['id']}_answer_summary", ""),
                            result,
                            aliases[team],
                        )[:PROMPT_TEXT_LIMIT],
                        "confidence": _number(
                            raw.get(f"{item['id']}_confidence")
                        ),
                        "review_required": review_required,
                    })
                observations.append(observation)
            if not observations:
                continue
            scores = [value["score"] for value in observations]
            manual_score = _number(
                manuals.get(team, {}).get("item_scores", {}).get(item["id"])
            )
            teams.append({
                "team_number": team,
                "alias": aliases[team],
                "rounds": observations,
                "median_score": round(statistics.median(scores), 2),
                "score_range": round(max(scores) - min(scores), 2),
                "review_count": item_review_count,
                "teacher_adjustments": teacher_adjustments,
                "manual_score": manual_score,
            })

        representatives = _representative_team_numbers(teams)
        prompt_teams = []
        for team in teams:
            if int(team["team_number"]) not in representatives:
                continue
            prompt_team = {
                key: value
                for key, value in team.items()
                if key != "team_number"
            }
            prompt_team["rounds"] = _representative_observations(
                prompt_team["rounds"]
            )
            prompt_teams.append(prompt_team)
        item_evidence.append({
            **item,
            "score_stats": _score_stats(all_scores),
            "student_count": len(teams),
            "observation_count": len(all_scores),
            "representative_answers": prompt_teams,
            "representative_count": len(prompt_teams),
        })

    sample = _pick_representative_teams(
        totals_by_team, review_counts, manuals
    )
    warnings = []
    if len(selected_round_ids) < 2:
        warnings.append(
            "한 회차만 선택했습니다. 가능하면 같은 기준의 독립 2회차를 함께 분석하세요."
        )
    if any(context["criteria_status"] == "modified" for context in contexts):
        warnings.append("미승인 수정 기준으로 실행된 회차가 포함되어 있습니다.")
    return {
        "round_ids": selected_round_ids,
        "round_contexts": contexts,
        "criteria_versions": versions,
        "criteria_fingerprints": sorted(fingerprints),
        "student_count": len(team_numbers),
        "observation_count": observation_count,
        "items": item_evidence,
        "recommended_sample_teams": sample,
        "warnings": warnings,
    }


def _current_criteria_payload(config: ProjectConfig) -> dict:
    if config.project_type == "exam":
        return {
            "grading_mode": config.exam.grading_mode,
            "questions": [
                {
                    "id": question.id,
                    "number": question.number,
                    "question_text": question.question_text,
                    "max_score": question.max_score,
                    "answer_type": question.answer_type,
                    "model_answer": question.model_answer,
                    "scoring_elements": [
                        {
                            "description": element.description,
                            "points": element.points,
                            "required": element.required,
                        }
                        for element in question.scoring_elements
                    ],
                    "accepted_answers": question.accepted_answers,
                    "common_errors": question.common_errors,
                    "core_criteria": question.core_criteria,
                    "teacher_notes": question.teacher_notes,
                }
                for question in config.exam.scored_questions()
            ],
        }
    return {
        "delivery_mode": config.criteria_state.delivery_mode,
        "criteria": [
            {
                "id": criterion.id,
                "category": category.name,
                "name": criterion.name,
                "description": criterion.description,
                "scale": criterion.scale,
                "scale_labels": criterion.scale_labels,
                "required_elements": criterion.required_elements,
                "deduction_rules": criterion.deduction_rules,
                "exceptions": criterion.exceptions,
                "feedback_focus": criterion.feedback_focus,
                "core_criteria": criterion.core_criteria,
            }
            for category in config.categories
            for criterion in category.criteria
        ],
    }


def criteria_fingerprint(config: ProjectConfig) -> str:
    return _fingerprint(_current_criteria_payload(config))


def generation_schema(project_type: str) -> dict:
    strength = {
        "type": "string",
        "enum": ["strong", "moderate", "weak"],
    }
    if project_type == "exam":
        item = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "number": {"type": "string"},
                "model_answer": {"type": "string"},
                "scoring_elements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "points": {"type": "integer"},
                            "required": {"type": "boolean"},
                        },
                        "required": ["description", "points", "required"],
                    },
                },
                "accepted_answers": {
                    "type": "array", "items": {"type": "string"}
                },
                "common_errors": {
                    "type": "array", "items": {"type": "string"}
                },
                "core_criteria": {
                    "type": "array", "items": {"type": "string"}
                },
                "boundary_cases": {
                    "type": "array", "items": {"type": "string"}
                },
                "teacher_notes": {"type": "string"},
                "change_summary": {"type": "string"},
                "rationale": {"type": "string"},
                "evidence_strength": strength,
            },
            "required": [
                "id", "number", "model_answer", "scoring_elements",
                "accepted_answers", "common_errors", "core_criteria",
                "boundary_cases", "teacher_notes", "change_summary",
                "rationale", "evidence_strength",
            ],
        }
        return {
            "type": "object",
            "properties": {
                "questions": {"type": "array", "items": item},
                "overall_note": {"type": "string"},
            },
            "required": ["questions", "overall_note"],
        }

    item = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "required_elements": {
                "type": "array", "items": {"type": "string"}
            },
            "deduction_rules": {
                "type": "array", "items": {"type": "string"}
            },
            "exceptions": {
                "type": "array", "items": {"type": "string"}
            },
            "feedback_focus": {"type": "string"},
            "core_criteria": {
                "type": "array", "items": {"type": "string"}
            },
            "boundary_cases": {
                "type": "array", "items": {"type": "string"}
            },
            "change_summary": {"type": "string"},
            "rationale": {"type": "string"},
            "evidence_strength": strength,
        },
        "required": [
            "id", "name", "description", "required_elements",
            "deduction_rules", "exceptions", "feedback_focus",
            "core_criteria", "boundary_cases", "change_summary",
            "rationale", "evidence_strength",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "criteria": {"type": "array", "items": item},
            "overall_note": {"type": "string"},
        },
        "required": ["criteria", "overall_note"],
    }


def build_generation_prompt(
    config: ProjectConfig,
    evidence: dict,
    *,
    teacher_instruction: str = "",
) -> str:
    project_label = (
        "정기고사 서술형 문항"
        if config.project_type == "exam"
        else "보고서·수행평가 루브릭"
    )
    evidence_for_prompt = {
        "rounds": evidence["round_contexts"],
        "student_count": evidence["student_count"],
        "items": evidence["items"],
    }
    return "\n".join([
        f"당신은 {project_label}을 실제 선채점 결과로 기준화하는 교사 보조자입니다.",
        "아래 자료에는 학생 이름 대신 A001 형식의 임시 별칭만 들어 있습니다.",
        "",
        "반드시 지킬 원칙:",
        "1. 현재 배점·척도·문항 ID는 바꾸지 마세요.",
        "2. 여러 답안에서 반복되거나 교사 수동·보정 점수가 뒷받침하는 패턴을 우선하세요.",
        "3. 소수의 특이 답안을 자동으로 정답 범위에 편입하지 말고 경계 사례로 남기세요.",
        "4. 관찰되지 않은 답안이나 오류를 실제 사례인 것처럼 지어내지 마세요.",
        "5. 교사용 상세 기준과 AI에게 전달할 3~5개 핵심 기준을 함께 제안하세요.",
        "6. 제안은 초안일 뿐이며 교사가 승인하기 전에는 채점에 적용되지 않습니다.",
        "7. evidence_strength는 strong/moderate/weak 중 하나로 표시하세요.",
        (
            "8. 부분점 합은 각 문항 배점을 넘지 않게 하세요."
            if config.project_type == "exam"
            else "8. 기존 점수 척도에 실제로 적용 가능한 판정 문구를 쓰세요."
        ),
        "",
        "교사 추가 지시:",
        teacher_instruction.strip() or "(없음)",
        "",
        "현재 평가기준:",
        json.dumps(
            _current_criteria_payload(config),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "",
        "선채점 근거:",
        json.dumps(
            evidence_for_prompt,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    ])


def _normalize_scoring_elements(values) -> list[dict]:
    result = []
    for value in values or []:
        if not isinstance(value, dict):
            continue
        description = str(value.get("description", "")).strip()
        try:
            points = int(value.get("points", 0) or 0)
        except (TypeError, ValueError):
            continue
        if description and points > 0:
            result.append({
                "description": description[:1000],
                "points": points,
                "required": bool(value.get("required", True)),
            })
    return result[:20]


def normalize_draft(config: ProjectConfig, generated: dict) -> dict:
    strength_values = {"strong", "moderate", "weak"}
    overall_note = str(generated.get("overall_note", "")).strip()[:3000]
    if config.project_type == "exam":
        supplied = {
            str(item.get("id", "")).strip(): item
            for item in generated.get("questions", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        }
        supplied_by_number = {
            str(item.get("number", "")).strip(): item
            for item in generated.get("questions", [])
            if isinstance(item, dict) and str(item.get("number", "")).strip()
        }
        questions = []
        for question in config.exam.scored_questions():
            suggestion = supplied.get(question.id) or supplied_by_number.get(
                str(question.number).strip(), {}
            )
            strength = str(
                suggestion.get("evidence_strength", "weak")
            ).strip().lower()
            questions.append({
                "id": question.id,
                "number": question.number,
                "question_text": question.question_text,
                "max_score": question.max_score,
                "model_answer": str(
                    suggestion.get("model_answer", question.model_answer)
                ).strip()[:5000],
                "scoring_elements": _normalize_scoring_elements(
                    suggestion.get(
                        "scoring_elements",
                        [
                            {
                                "description": element.description,
                                "points": element.points,
                                "required": element.required,
                            }
                            for element in question.scoring_elements
                        ],
                    )
                ),
                "accepted_answers": _unique_text(
                    suggestion.get(
                        "accepted_answers", question.accepted_answers
                    )
                ),
                "common_errors": _unique_text(
                    suggestion.get("common_errors", question.common_errors)
                ),
                "core_criteria": _unique_text(
                    suggestion.get("core_criteria", question.core_criteria),
                    limit=8,
                ),
                "boundary_cases": _unique_text(
                    suggestion.get("boundary_cases", []), limit=20
                ),
                "teacher_notes": str(
                    suggestion.get("teacher_notes", question.teacher_notes)
                ).strip()[:3000],
                "change_summary": str(
                    suggestion.get("change_summary", "")
                ).strip()[:1500],
                "rationale": str(
                    suggestion.get("rationale", "")
                ).strip()[:3000],
                "evidence_strength": (
                    strength if strength in strength_values else "weak"
                ),
            })
        return {"questions": questions, "overall_note": overall_note}

    supplied = {
        str(item.get("id", "")).strip(): item
        for item in generated.get("criteria", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    criteria = []
    for category in config.categories:
        for criterion in category.criteria:
            suggestion = supplied.get(criterion.id, {})
            strength = str(
                suggestion.get("evidence_strength", "weak")
            ).strip().lower()
            criteria.append({
                "id": criterion.id,
                "category": category.name,
                "name": criterion.name,
                "scale": list(criterion.scale),
                "scale_labels": list(criterion.scale_labels),
                "description": str(
                    suggestion.get("description", criterion.description)
                ).strip()[:5000],
                "required_elements": _unique_text(
                    suggestion.get(
                        "required_elements", criterion.required_elements
                    )
                ),
                "deduction_rules": _unique_text(
                    suggestion.get(
                        "deduction_rules", criterion.deduction_rules
                    )
                ),
                "exceptions": _unique_text(
                    suggestion.get("exceptions", criterion.exceptions)
                ),
                "feedback_focus": str(
                    suggestion.get(
                        "feedback_focus", criterion.feedback_focus
                    )
                ).strip()[:3000],
                "core_criteria": _unique_text(
                    suggestion.get(
                        "core_criteria", criterion.core_criteria
                    ),
                    limit=8,
                ),
                "boundary_cases": _unique_text(
                    suggestion.get("boundary_cases", []), limit=20
                ),
                "change_summary": str(
                    suggestion.get("change_summary", "")
                ).strip()[:1500],
                "rationale": str(
                    suggestion.get("rationale", "")
                ).strip()[:3000],
                "evidence_strength": (
                    strength if strength in strength_values else "weak"
                ),
            })
    return {"criteria": criteria, "overall_note": overall_note}


def validate_draft(config: ProjectConfig, draft: dict) -> dict:
    errors = []
    warnings = []
    expected = {item["id"]: item for item in scoring_items(config)}
    key = "questions" if config.project_type == "exam" else "criteria"
    supplied = {
        str(item.get("id", "")): item
        for item in draft.get(key, [])
        if isinstance(item, dict)
    }
    missing = [item["label"] for item_id, item in expected.items() if item_id not in supplied]
    if missing:
        errors.append("초안에 빠진 평가 단위: " + ", ".join(missing))
    unknown = sorted(set(supplied) - set(expected))
    if unknown:
        errors.append("현재 기준에 없는 ID가 포함됨: " + ", ".join(unknown))
    if config.project_type == "exam":
        for item_id, item in supplied.items():
            maximum = expected.get(item_id, {}).get("max_score")
            if maximum is None:
                continue
            total = sum(
                int(element.get("points", 0) or 0)
                for element in item.get("scoring_elements", [])
                if isinstance(element, dict)
            )
            if total > maximum:
                errors.append(
                    f"{expected[item_id]['label']} 부분점 합 {total}점이 "
                    f"배점 {maximum:g}점을 초과합니다."
                )
            elif item.get("scoring_elements") and total < maximum:
                warnings.append(
                    f"{expected[item_id]['label']} 부분점 합이 배점보다 "
                    f"{maximum - total:g}점 적습니다."
                )
            if not str(item.get("model_answer", "")).strip():
                warnings.append(
                    f"{expected[item_id]['label']} 모범답안이 비어 있습니다."
                )
            if not item.get("core_criteria"):
                warnings.append(
                    f"{expected[item_id]['label']} AI용 핵심 기준이 비어 있습니다."
                )
    else:
        for item_id, item in supplied.items():
            if item_id not in expected:
                continue
            if not str(item.get("description", "")).strip():
                errors.append(
                    f"{expected[item_id]['label']} 상세 설명이 비어 있습니다."
                )
            if not item.get("core_criteria"):
                warnings.append(
                    f"{expected[item_id]['label']} AI용 핵심 기준이 비어 있습니다."
                )
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def create_session(
    config: ProjectConfig,
    *,
    evidence: dict,
    generated: dict,
    teacher_instruction: str = "",
) -> dict:
    draft = normalize_draft(config, generated)
    validation = validate_draft(config, draft)
    now = _now_iso()
    session = {
        "id": f"std-{uuid.uuid4().hex[:12]}",
        "created_at": now,
        "updated_at": now,
        "project_type": config.project_type,
        "status": "draft",
        "source_round_ids": evidence["round_ids"],
        "source_round_contexts": evidence["round_contexts"],
        "source_criteria_versions": evidence["criteria_versions"],
        "source_criteria_fingerprints": evidence[
            "criteria_fingerprints"
        ],
        "base_criteria_fingerprint": criteria_fingerprint(config),
        "student_count": evidence["student_count"],
        "observation_count": evidence["observation_count"],
        "teacher_instruction": str(teacher_instruction or "").strip()[:3000],
        "warnings": evidence["warnings"],
        "evidence_summary": [
            {
                "id": item["id"],
                "label": item["label"],
                "student_count": item["student_count"],
                "observation_count": item["observation_count"],
                "score_stats": item["score_stats"],
                "representative_count": item["representative_count"],
            }
            for item in evidence["items"]
        ],
        "recommended_sample_teams": evidence[
            "recommended_sample_teams"
        ],
        "draft": draft,
        "draft_fingerprint": _fingerprint(draft),
        "draft_validation": validation,
        "approved_at": "",
        "approved_version": 0,
        "teacher_note": "",
        "audit_log": [{
            "timestamp": now,
            "action": "draft_created",
            "round_ids": evidence["round_ids"],
        }],
    }
    store = load_store(config.id)
    store["sessions"].append(session)
    save_store(config.id, store)
    return session


def update_draft(
    config: ProjectConfig,
    session_id: str,
    draft: dict,
) -> dict:
    store = load_store(config.id)
    session = next(
        (
            item for item in store["sessions"]
            if item.get("id") == session_id
        ),
        None,
    )
    if not session:
        raise LookupError("기준화 초안을 찾을 수 없습니다.")
    if session.get("status") != "draft":
        raise ValueError("승인 또는 폐기된 기준화 초안은 수정할 수 없습니다.")
    normalized = normalize_draft(config, draft or {})
    validation = validate_draft(config, normalized)
    now = _now_iso()
    before = session.get("draft_fingerprint", "")
    session["draft"] = normalized
    session["draft_fingerprint"] = _fingerprint(normalized)
    session["draft_validation"] = validation
    session["updated_at"] = now
    session.setdefault("audit_log", []).append({
        "timestamp": now,
        "action": "draft_updated",
        "before_fingerprint": before,
        "after_fingerprint": session["draft_fingerprint"],
    })
    save_store(config.id, store)
    return session


def apply_draft_to_config(
    config: ProjectConfig,
    draft: dict,
    *,
    delivery_mode: str = "core",
) -> ProjectConfig:
    """원본 config를 건드리지 않고 초안을 반영한 복사본을 반환한다."""
    candidate = copy.deepcopy(config)
    if candidate.project_type == "exam":
        by_id = {
            str(item.get("id", "")): item
            for item in draft.get("questions", [])
            if isinstance(item, dict)
        }
        for question in candidate.exam.scored_questions():
            item = by_id.get(question.id)
            if not item:
                continue
            question.model_answer = str(item.get("model_answer", "")).strip()
            question.scoring_elements = [
                ScoringElement(
                    description=element["description"],
                    points=int(element["points"]),
                    required=bool(element.get("required", True)),
                )
                for element in _normalize_scoring_elements(
                    item.get("scoring_elements", [])
                )
            ]
            question.accepted_answers = _unique_text(
                item.get("accepted_answers", [])
            )
            question.common_errors = _unique_text(
                item.get("common_errors", [])
            )
            question.core_criteria = _unique_text(
                item.get("core_criteria", []), limit=8
            )
            boundary_cases = _unique_text(
                item.get("boundary_cases", []), limit=20
            )
            note_parts = [
                str(item.get("teacher_notes", "")).strip(),
                (
                    "기준화 경계 사례: " + "; ".join(boundary_cases)
                    if boundary_cases else ""
                ),
            ]
            question.teacher_notes = "\n".join(
                value for value in note_parts if value
            )
        candidate.exam.grading_mode = (
            delivery_mode
            if delivery_mode in {"autonomous", "core", "strict"}
            else "core"
        )
    else:
        by_id = {
            str(item.get("id", "")): item
            for item in draft.get("criteria", [])
            if isinstance(item, dict)
        }
        for category in candidate.categories:
            for criterion in category.criteria:
                item = by_id.get(criterion.id)
                if not item:
                    continue
                criterion.description = str(
                    item.get("description", "")
                ).strip()
                criterion.required_elements = _unique_text(
                    item.get("required_elements", [])
                )
                criterion.deduction_rules = _unique_text(
                    item.get("deduction_rules", [])
                )
                criterion.exceptions = _unique_text(
                    [
                        *item.get("exceptions", []),
                        *[
                            f"경계 사례: {value}"
                            for value in item.get("boundary_cases", [])
                        ],
                    ]
                )
                criterion.feedback_focus = str(
                    item.get("feedback_focus", "")
                ).strip()
                criterion.core_criteria = _unique_text(
                    item.get("core_criteria", []), limit=8
                )
        candidate.criteria_state.delivery_mode = (
            delivery_mode if delivery_mode in {"core", "strict"} else "core"
        )
    candidate.prompt_template = generate_default_prompt(candidate)
    return candidate


def mark_approved(
    project_id: str,
    session_id: str,
    *,
    approved_version: int,
    teacher_note: str = "",
) -> dict:
    store = load_store(project_id)
    session = next(
        (
            item for item in store["sessions"]
            if item.get("id") == session_id
        ),
        None,
    )
    if not session:
        raise LookupError("기준화 초안을 찾을 수 없습니다.")
    if session.get("status") != "draft":
        raise ValueError("이미 승인 또는 폐기된 기준화 초안입니다.")
    now = _now_iso()
    session["status"] = "approved"
    session["approved_at"] = now
    session["approved_version"] = int(approved_version)
    session["teacher_note"] = str(teacher_note or "").strip()[:3000]
    session["updated_at"] = now
    session.setdefault("audit_log", []).append({
        "timestamp": now,
        "action": "teacher_approved",
        "approved_version": int(approved_version),
    })
    save_store(project_id, store)
    return session


def discard_session(
    project_id: str,
    session_id: str,
    *,
    reason: str = "",
) -> dict:
    store = load_store(project_id)
    session = next(
        (
            item for item in store["sessions"]
            if item.get("id") == session_id
        ),
        None,
    )
    if not session:
        raise LookupError("기준화 초안을 찾을 수 없습니다.")
    if session.get("status") != "draft":
        raise ValueError("초안 상태의 기준화만 폐기할 수 있습니다.")
    now = _now_iso()
    session["status"] = "discarded"
    session["updated_at"] = now
    session.setdefault("audit_log", []).append({
        "timestamp": now,
        "action": "draft_discarded",
        "reason": str(reason or "").strip()[:1000],
    })
    save_store(project_id, store)
    return session


def _round_values(
    config: ProjectConfig,
    round_ids: list[int],
) -> tuple[dict[int, dict], dict[str, dict[int, list[float]]]]:
    totals: dict[int, list[float]] = {}
    items = {
        item["id"]: {} for item in scoring_items(config)
    }
    for round_id in round_ids:
        for team, result in load_completed(config.id, round_id).items():
            raw = _raw_result(result)
            total = _number(raw.get("total_score"))
            if total is not None:
                totals.setdefault(int(team), []).append(total)
            for item_id in items:
                score = _number(raw.get(item_id))
                if score is not None:
                    items[item_id].setdefault(int(team), []).append(score)
    return totals, items


def _metric_summary(
    values: dict[int, list[float]],
    manuals: dict[int, float | None],
) -> dict:
    student_medians = {
        team: statistics.median(scores)
        for team, scores in values.items()
        if scores
    }
    within_std = [
        statistics.pstdev(scores)
        for scores in values.values()
        if len(scores) > 1
    ]
    within_range = [
        max(scores) - min(scores)
        for scores in values.values()
        if len(scores) > 1
    ]
    manual_differences = [
        abs(score - manuals[team])
        for team, score in student_medians.items()
        if manuals.get(team) is not None
    ]
    return {
        "student_count": len(student_medians),
        "mean_score": (
            round(statistics.fmean(student_medians.values()), 2)
            if student_medians else None
        ),
        "mean_within_student_std": (
            round(statistics.fmean(within_std), 2) if within_std else None
        ),
        "mean_within_student_range": (
            round(statistics.fmean(within_range), 2) if within_range else None
        ),
        "manual_comparison_count": len(manual_differences),
        "manual_mae": (
            round(statistics.fmean(manual_differences), 2)
            if manual_differences else None
        ),
    }


def compare_session(
    config: ProjectConfig,
    session: dict,
) -> dict:
    baseline_round_ids = [
        int(value) for value in session.get("source_round_ids", [])
    ]
    approved_version = int(session.get("approved_version", 0) or 0)
    validation_round_ids = [
        int(summary["id"])
        for summary in list_round_summaries(config)
        if int(summary.get("completed_count", 0) or 0) > 0
        and int(summary.get("criteria_version", 0) or 0) == approved_version
        and int(summary["id"]) not in baseline_round_ids
    ] if approved_version else []
    result = {
        "baseline_round_ids": baseline_round_ids,
        "validation_round_ids": validation_round_ids,
        "approved_version": approved_version,
        "status": "not_started",
        "verdict": "insufficient",
        "verdict_reasons": [],
        "summary": {},
        "students": [],
        "items": [],
    }
    if session.get("status") != "approved" or not approved_version:
        result["verdict_reasons"].append(
            "기준화 초안을 먼저 교사 승인해야 합니다."
        )
        return result
    if not validation_round_ids:
        result["verdict_reasons"].append(
            f"승인 기준 v{approved_version}으로 실행한 표본 회차가 아직 없습니다."
        )
        return result

    before_totals, before_items = _round_values(
        config, baseline_round_ids
    )
    after_totals, after_items = _round_values(
        config, validation_round_ids
    )
    overlap = sorted(set(before_totals) & set(after_totals))
    manuals_full = load_manual_scores(config.id)
    total_manuals = {
        team: _number(value.get("total_score"))
        for team, value in manuals_full.items()
    }
    before_metrics = _metric_summary(
        {team: before_totals[team] for team in overlap}, total_manuals
    )
    after_metrics = _metric_summary(
        {team: after_totals[team] for team in overlap}, total_manuals
    )
    students = []
    for team in overlap:
        before = round(statistics.median(before_totals[team]), 2)
        after = round(statistics.median(after_totals[team]), 2)
        students.append({
            "team_number": team,
            "before": before,
            "after": after,
            "delta": round(after - before, 2),
            "manual_score": total_manuals.get(team),
        })

    item_definitions = {item["id"]: item for item in scoring_items(config)}
    item_comparisons = []
    for item_id, definition in item_definitions.items():
        item_overlap = sorted(
            set(before_items[item_id]) & set(after_items[item_id])
        )
        item_manuals = {
            team: _number(
                manuals_full.get(team, {}).get(
                    "item_scores", {}
                ).get(item_id)
            )
            for team in item_overlap
        }
        before_item_metrics = _metric_summary(
            {
                team: before_items[item_id][team]
                for team in item_overlap
            },
            item_manuals,
        )
        after_item_metrics = _metric_summary(
            {
                team: after_items[item_id][team]
                for team in item_overlap
            },
            item_manuals,
        )
        item_comparisons.append({
            "id": item_id,
            "label": definition["label"],
            "before": before_item_metrics,
            "after": after_item_metrics,
        })

    result.update({
        "status": "ready",
        "summary": {
            "student_count": len(overlap),
            "before": before_metrics,
            "after": after_metrics,
            "mean_score_delta": (
                round(
                    after_metrics["mean_score"]
                    - before_metrics["mean_score"],
                    2,
                )
                if (
                    after_metrics["mean_score"] is not None
                    and before_metrics["mean_score"] is not None
                )
                else None
            ),
        },
        "students": students,
        "items": item_comparisons,
    })

    improvements = []
    regressions = []
    before_mae = before_metrics["manual_mae"]
    after_mae = after_metrics["manual_mae"]
    if before_mae is not None and after_mae is not None:
        if after_mae < before_mae:
            improvements.append(
                f"수동 점수 평균 오차가 {before_mae:g}→{after_mae:g}점으로 감소"
            )
        elif after_mae > before_mae:
            regressions.append(
                f"수동 점수 평균 오차가 {before_mae:g}→{after_mae:g}점으로 증가"
            )
    before_std = before_metrics["mean_within_student_std"]
    after_std = after_metrics["mean_within_student_std"]
    if before_std is not None and after_std is not None:
        if after_std < before_std:
            improvements.append(
                f"회차 간 평균 표준편차가 {before_std:g}→{after_std:g}점으로 감소"
            )
        elif after_std > before_std:
            regressions.append(
                f"회차 간 평균 표준편차가 {before_std:g}→{after_std:g}점으로 증가"
            )
    if len(overlap) < 3:
        result["verdict_reasons"].append(
            "비교 가능한 표본이 3명 미만이라 결론을 내리기 어렵습니다."
        )
    result["verdict_reasons"].extend(improvements)
    result["verdict_reasons"].extend(regressions)
    if len(overlap) >= 3 and improvements and not regressions:
        result["verdict"] = "improved"
    elif regressions and not improvements:
        result["verdict"] = "worse"
    elif improvements or regressions:
        result["verdict"] = "mixed"
    else:
        result["verdict_reasons"].append(
            "수동 점수 또는 독립 표본 회차가 부족해 신뢰도 개선을 측정할 수 없습니다."
        )
    return result


def build_workspace(config: ProjectConfig) -> dict:
    rounds = []
    for summary in list_round_summaries(config):
        if int(summary.get("completed_count", 0) or 0) <= 0:
            continue
        metadata = grading_service.load_round_metadata(
            config.id, int(summary["id"])
        )
        rounds.append({
            **summary,
            "criteria_fingerprint": metadata.get(
                "execution_context", {}
            ).get("criteria_fingerprint", ""),
        })
    store = load_store(config.id)
    sessions = []
    current_fingerprint = criteria_fingerprint(config)
    for session in reversed(store["sessions"]):
        detail = session_summary(session)
        detail["criteria_changed"] = (
            session.get("status") == "draft"
            and bool(session.get("base_criteria_fingerprint"))
            and session.get("base_criteria_fingerprint")
            != current_fingerprint
        )
        detail["comparison"] = compare_session(config, session)
        sessions.append(detail)
    return {
        "project_type": config.project_type,
        "criteria_state": vars(config.criteria_state),
        "rounds": rounds,
        "sessions": sessions,
    }
