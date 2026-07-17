from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import models.project as project_model
import services.pdf_splitter as splitter
from models.project import ExamConfig, ProjectConfig, ScanSplitConfig, StudentRecord


def make_pdf(path: Path, pages: int):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with open(path, "wb") as stream:
        writer.write(stream)


def test_build_plan_auto_and_non_divisible(tmp_path):
    source = tmp_path / "class.pdf"
    make_pdf(source, 8)
    students = [StudentRecord(1, "가"), StudentRecord(2, "나")]
    plan = splitter.build_split_plan(source, students)
    assert [(e["start_page"], e["end_page"]) for e in plan["entries"]] == [(1, 4), (5, 8)]

    make_pdf(source, 7)
    with pytest.raises(splitter.SplitValidationError):
        splitter.build_split_plan(source, students)

    with pytest.raises(splitter.SplitValidationError):
        splitter.build_split_plan(
            source,
            [StudentRecord(1, "가"), StudentRecord(1, "나")],
            pages_per_student=3,
        )


def test_split_pdf_writes_verified_student_files(tmp_path, monkeypatch):
    monkeypatch.setattr(splitter, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(project_model, "PROJECTS_DIR", tmp_path / "projects")
    source = tmp_path / "class.pdf"
    make_pdf(source, 6)
    config = ProjectConfig(
        id="exam1", name="시험", project_type="exam",
        exam=ExamConfig(
            students=[StudentRecord(1, "가"), StudentRecord(2, "나"), StudentRecord(3, "다")],
            scan_split=ScanSplitConfig(source_path=str(source)),
        ),
    )
    result = splitter.split_integrated_pdf(config, pages_per_student=2)
    assert len(result["entries"]) == 3
    outputs = sorted((tmp_path / "projects" / "exam1" / "materials" / "student_answers").glob("*.pdf"))
    assert len(outputs) == 3
    assert all(len(PdfReader(str(path)).pages) == 2 for path in outputs)


def test_split_failure_restores_previous_outputs(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    monkeypatch.setattr(splitter, "PROJECTS_DIR", projects)
    monkeypatch.setattr(project_model, "PROJECTS_DIR", projects)
    source = tmp_path / "class.pdf"
    make_pdf(source, 2)
    config = ProjectConfig(
        id="exam1", name="시험", project_type="exam",
        exam=ExamConfig(
            students=[StudentRecord(1, "가")],
            scan_split=ScanSplitConfig(source_path=str(source)),
        ),
    )
    previous_dir = projects / "exam1" / "materials" / "student_answers"
    previous_dir.mkdir(parents=True)
    marker = previous_dir / "previous.txt"
    marker.write_text("keep", encoding="utf-8")

    real_replace = splitter.os.replace

    def fail_when_publishing(source_path, destination_path):
        source_path = Path(source_path)
        destination_path = Path(destination_path)
        if source_path.name.startswith("split_") and "backup" not in source_path.name \
                and destination_path.name == "student_answers":
            raise OSError("simulated publish failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(splitter.os, "replace", fail_when_publishing)
    with pytest.raises(OSError, match="simulated publish failure"):
        splitter.split_integrated_pdf(config, pages_per_student=2)

    assert marker.read_text(encoding="utf-8") == "keep"
