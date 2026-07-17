"""공통 명렬과 제출 파일의 자동·수동 연결 상태를 계산한다."""

from __future__ import annotations

import re

from config import PROJECTS_DIR
from models.project import ProjectConfig, resolve_project_path
from services.file_manager import find_materials


STATUS_LABELS = {
    "ready": "준비 완료",
    "missing": "파일 없음",
    "name_mismatch": "이름 불일치",
    "multiple_files": "여러 파일 연결",
    "unregistered": "명렬에 없음",
}


def _normalized_name(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", (value or "")).casefold()


def _split_output_info(config: ProjectConfig) -> dict:
    default_dir = (PROJECTS_DIR / config.id / "materials" / "student_answers").resolve()
    configured = config.submissions.split_output_dir
    output_dir = (
        resolve_project_path(config.id, configured, expected_subdir="materials")
        if configured
        else default_dir
    )
    exists = output_dir.exists() and output_dir.is_dir()
    return {
        "output_dir": str(output_dir),
        "exists": exists,
        "file_count": len(list(output_dir.glob("*.pdf"))) if exists else 0,
        "completed_at": config.exam.scan_split.completed_at if config.project_type == "exam" else "",
    }


def build_submission_status(config: ProjectConfig) -> dict:
    """파일을 변경하지 않고 학생·답안 연결 상태를 만든다."""
    participants = find_materials(config)
    by_number = {item["number"]: item for item in participants}
    roster = config.roster_students
    roster_by_number = {student.number: student for student in roster}
    has_roster = bool(roster)
    entries = []

    if has_roster:
        for student in roster:
            participant = by_number.get(student.number)
            files = list(participant.get("files", [])) if participant else []
            discovered_name = participant.get("name", "") if participant else ""
            manually_confirmed = any(file.get("manual_link") for file in files)
            mismatch = bool(
                files
                and student.name
                and discovered_name
                and _normalized_name(student.name) != _normalized_name(discovered_name)
                and not manually_confirmed
            )
            if not files:
                status = "missing"
            elif mismatch:
                status = "name_mismatch"
            elif len(files) > 1:
                status = "multiple_files"
            else:
                status = "ready"
            entries.append({
                "number": student.number,
                "name": student.name,
                "discovered_name": discovered_name,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "files": files,
                "registered": True,
            })

        for participant in participants:
            if participant["number"] in roster_by_number:
                continue
            entries.append({
                "number": participant["number"],
                "name": participant.get("name", ""),
                "discovered_name": participant.get("name", ""),
                "status": "unregistered",
                "status_label": STATUS_LABELS["unregistered"],
                "files": list(participant.get("files", [])),
                "registered": False,
            })
    else:
        for participant in participants:
            files = list(participant.get("files", []))
            status = "multiple_files" if len(files) > 1 else "ready"
            entries.append({
                "number": participant["number"],
                "name": participant.get("name", ""),
                "discovered_name": participant.get("name", ""),
                "status": status,
                "status_label": STATUS_LABELS[status],
                "files": files,
                "registered": False,
                "inferred": True,
            })

    counts = {
        status: sum(1 for entry in entries if entry["status"] == status)
        for status in STATUS_LABELS
    }
    file_count = sum(len(entry["files"]) for entry in entries)
    attention_count = (
        counts["missing"]
        + counts["name_mismatch"]
        + counts["multiple_files"]
        + counts["unregistered"]
    )
    ready_count = counts["ready"] + counts["multiple_files"]

    return {
        "roster": [
            {
                "number": student.number,
                "name": student.name,
                "grade": student.grade,
                "class_name": student.class_name,
                "student_id": student.student_id,
            }
            for student in roster
        ],
        "roster_source": "saved" if has_roster else ("files" if participants else "none"),
        "entries": sorted(entries, key=lambda item: item["number"]),
        "summary": {
            "roster_count": len(roster),
            "participant_count": len(participants),
            "file_count": file_count,
            "ready_count": ready_count,
            "attention_count": attention_count,
            **counts,
        },
        "all_ready": bool(participants) and counts["missing"] == 0
        and counts["name_mismatch"] == 0 and counts["unregistered"] == 0,
        "split": _split_output_info(config),
    }
