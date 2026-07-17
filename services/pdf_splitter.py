"""통합 시험지 PDF를 학생별 PDF로 안전하게 분할한다."""
from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from config import PROJECTS_DIR
from models.project import (
    ProjectConfig, ScanSplitConfig, StudentRecord, portable_project_path,
    resolve_project_path, save_project,
)


class SplitValidationError(ValueError):
    """분할 설정을 교사가 수정해야 할 때 발생한다."""


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (value or "").strip())
    return cleaned[:80] or "학생"


def _read_page_count(source_path: Path) -> int:
    if not source_path.exists() or source_path.suffix.lower() != ".pdf":
        raise SplitValidationError("통합 스캔 PDF를 먼저 업로드하세요.")
    try:
        return len(PdfReader(str(source_path)).pages)
    except Exception as exc:
        raise SplitValidationError(f"PDF를 읽을 수 없습니다: {exc}") from exc


def build_split_plan(
    source_path: Path,
    students: list[StudentRecord],
    start_page: int = 1,
    pages_per_student: int = 0,
    boundaries: list[int] | None = None,
) -> dict:
    """파일을 쓰지 않고 1-based 페이지 분할 계획을 계산한다."""
    total_pages = _read_page_count(source_path)
    if not students:
        raise SplitValidationError("학생 명렬을 한 명 이상 입력하세요.")

    student_numbers = [student.number for student in students]
    if len(student_numbers) != len(set(student_numbers)):
        raise SplitValidationError("학생 번호가 중복되었습니다. 명렬을 확인하세요.")

    start_page = max(1, int(start_page or 1))
    if start_page > total_pages:
        raise SplitValidationError("시작 페이지가 PDF 전체 페이지 수보다 큽니다.")

    usable_pages = total_pages - start_page + 1
    starts = sorted({int(v) for v in (boundaries or []) if int(v) >= start_page})
    ranges: list[tuple[int, int]] = []
    mode = "fixed"

    if starts:
        mode = "boundaries"
        if len(starts) != len(students):
            raise SplitValidationError(
                f"경계 시작 페이지는 학생 수와 같은 {len(students)}개여야 합니다."
            )
        if starts[0] != start_page or starts[-1] > total_pages:
            raise SplitValidationError("첫 경계는 시작 페이지와 같고 마지막 경계는 PDF 범위 안이어야 합니다.")
        for idx, page_start in enumerate(starts):
            page_end = starts[idx + 1] - 1 if idx + 1 < len(starts) else total_pages
            if page_end < page_start:
                raise SplitValidationError("페이지 경계가 올바르지 않습니다.")
            ranges.append((page_start, page_end))
    else:
        pages_per_student = int(pages_per_student or 0)
        if pages_per_student <= 0:
            if usable_pages % len(students) != 0:
                raise SplitValidationError(
                    f"사용할 {usable_pages}쪽을 학생 {len(students)}명에게 동일하게 나눌 수 없습니다. "
                    "학생당 쪽 수 또는 경계 시작 페이지를 입력하세요."
                )
            pages_per_student = usable_pages // len(students)

        required = pages_per_student * len(students)
        if required > usable_pages:
            raise SplitValidationError(
                f"설정상 {required}쪽이 필요하지만 사용할 수 있는 페이지는 {usable_pages}쪽입니다."
            )
        for idx in range(len(students)):
            page_start = start_page + idx * pages_per_student
            ranges.append((page_start, page_start + pages_per_student - 1))

    unused_pages = []
    last_used = ranges[-1][1]
    if last_used < total_pages:
        unused_pages = list(range(last_used + 1, total_pages + 1))

    entries = []
    for student, (page_start, page_end) in zip(students, ranges):
        filename = f"{student.number:03d}. {_safe_name(student.name)}.pdf"
        entries.append({
            "number": student.number,
            "name": student.name,
            "start_page": page_start,
            "end_page": page_end,
            "page_count": page_end - page_start + 1,
            "filename": filename,
        })

    return {
        "source_path": str(source_path),
        "total_pages": total_pages,
        "usable_pages": usable_pages,
        "mode": mode,
        "pages_per_student": pages_per_student if mode == "fixed" else 0,
        "entries": entries,
        "unused_pages": unused_pages,
    }


def split_integrated_pdf(
    config: ProjectConfig,
    start_page: int = 1,
    pages_per_student: int = 0,
    boundaries: list[int] | None = None,
) -> dict:
    """검증된 계획대로 PDF를 원자적으로 분할하고 프로젝트 설정을 갱신한다."""
    if config.project_type != "exam":
        raise SplitValidationError("정기고사 프로젝트에서만 통합 PDF를 분할할 수 있습니다.")

    source_path = resolve_project_path(
        config.id, config.exam.scan_split.source_path, expected_subdir="exam_sources"
    )
    plan = build_split_plan(
        source_path,
        config.roster_students,
        start_page=start_page,
        pages_per_student=pages_per_student,
        boundaries=boundaries,
    )

    project_dir = (PROJECTS_DIR / config.id).resolve()
    materials_dir = (project_dir / "materials").resolve()
    final_dir = (materials_dir / "student_answers").resolve()
    temp_dir = (project_dir / "temp" / f"split_{uuid.uuid4().hex}").resolve()
    backup_dir = (project_dir / "temp" / f"split_backup_{uuid.uuid4().hex}").resolve()
    if project_dir not in final_dir.parents or project_dir not in temp_dir.parents:
        raise RuntimeError("분할 출력 경로가 프로젝트 폴더 밖입니다.")

    temp_dir.mkdir(parents=True, exist_ok=False)
    reader = PdfReader(str(source_path))
    try:
        for entry in plan["entries"]:
            writer = PdfWriter()
            for page_number in range(entry["start_page"], entry["end_page"] + 1):
                writer.add_page(reader.pages[page_number - 1])
            output_path = temp_dir / entry["filename"]
            with open(output_path, "wb") as stream:
                writer.write(stream)
            if len(PdfReader(str(output_path)).pages) != entry["page_count"]:
                raise RuntimeError(f"분할 검증 실패: {entry['filename']}")

        materials_dir.mkdir(parents=True, exist_ok=True)
        had_previous_output = final_dir.exists()
        if had_previous_output:
            os.replace(final_dir, backup_dir)
        try:
            os.replace(temp_dir, final_dir)
        except Exception:
            if had_previous_output and backup_dir.exists() and not final_dir.exists():
                os.replace(backup_dir, final_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        if backup_dir.exists() and not final_dir.exists():
            os.replace(backup_dir, final_dir)
        raise

    completed_at = datetime.now().isoformat()
    config.exam.scan_split = ScanSplitConfig(
        source_path=str(source_path),
        start_page=max(1, int(start_page or 1)),
        pages_per_student=plan["pages_per_student"],
        boundaries=[entry["start_page"] for entry in plan["entries"]]
        if plan["mode"] == "boundaries" else [],
        completed_at=completed_at,
    )
    config.materials.source_type = "upload"
    config.materials.file_types = ["pdf"]
    config.materials.naming_pattern = r"(\d+)\.\s*(.+)"
    config.submissions.split_output_dir = portable_project_path(config.id, final_dir)
    save_project(config)

    plan["output_dir"] = str(final_dir)
    plan["completed_at"] = completed_at
    return plan
