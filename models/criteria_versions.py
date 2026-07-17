"""보고서 루브릭과 서술형 문항 기준의 공통 버전 저장소."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from config import PROJECTS_DIR
from models.project import ProjectConfig


FILENAME = "criteria_versions.json"
VERSION_SOURCES = {
    "manual",
    "official",
    "generated",
    "synthesized",
    "compressed",
    "restored",
}


def _path(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / FILENAME


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _payload(config: ProjectConfig) -> dict:
    data = config.to_dict()
    exam = data.get("exam") or {}
    return {
        "workflow_type": config.workflow_type,
        "project_type": config.project_type,
        "total_max_score": config.total_max_score,
        "categories": data.get("categories", []),
        "report_delivery_mode": config.criteria_state.delivery_mode,
        "prompt_template": config.prompt_template if config.project_type != "exam" else "",
        "exam": {
            "grading_mode": exam.get("grading_mode", "strict"),
            "additional_instructions": exam.get("additional_instructions", ""),
            "questions": exam.get("questions", []),
        },
    }


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_versions(project_id: str) -> list[dict]:
    path = _path(project_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    versions = raw.get("versions", []) if isinstance(raw, dict) else []
    return sorted(versions, key=lambda item: int(item.get("version", 0)))


def _save_versions(project_id: str, versions: list[dict]) -> None:
    path = _path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {"schema_version": 1, "versions": versions},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def get_version(project_id: str, version: int) -> dict | None:
    return next(
        (
            item
            for item in load_versions(project_id)
            if int(item.get("version", 0)) == version
        ),
        None,
    )


def snapshot(
    config: ProjectConfig,
    *,
    source: str = "manual",
    note: str = "",
) -> dict:
    versions = load_versions(config.id)
    payload = _payload(config)
    entry = {
        "version": int(versions[-1]["version"]) + 1 if versions else 1,
        "created_at": _now(),
        "source": source if source in VERSION_SOURCES else "manual",
        "note": str(note or "")[:500],
        "approved": False,
        "approved_at": "",
        "fingerprint": _fingerprint(payload),
        "payload": payload,
    }
    versions.append(entry)
    _save_versions(config.id, versions)
    return entry


def approve(project_id: str, version: int) -> dict | None:
    versions = load_versions(project_id)
    target = None
    for entry in versions:
        if int(entry.get("version", 0)) == version:
            entry["approved"] = True
            entry["approved_at"] = _now()
            target = entry
            break
    if target is not None:
        _save_versions(project_id, versions)
    return target


def summary(entry: dict) -> dict:
    payload = entry.get("payload", {})
    exam = payload.get("exam", {})
    questions = exam.get("questions", [])
    parent_ids = {
        str(question.get("parent_id", ""))
        for question in questions
        if question.get("parent_id")
    }
    scored_questions = [
        question
        for question in questions
        if str(question.get("id", "")) not in parent_ids
    ]
    categories = payload.get("categories", [])
    return {
        "version": int(entry.get("version", 0)),
        "created_at": entry.get("created_at", ""),
        "source": entry.get("source", ""),
        "note": entry.get("note", ""),
        "approved": bool(entry.get("approved", False)),
        "approved_at": entry.get("approved_at", ""),
        "project_type": payload.get("project_type", "report"),
        "question_count": len(scored_questions),
        "criterion_count": sum(
            len(category.get("criteria", [])) for category in categories
        ),
        "total_max_score": int(payload.get("total_max_score", 0) or 0),
        "compressed_count": (
            sum(1 for question in questions if question.get("core_criteria"))
            if payload.get("project_type") == "exam"
            else sum(
                1
                for category in categories
                for criterion in category.get("criteria", [])
                if criterion.get("core_criteria")
            )
        ),
    }
