from pathlib import Path

import app as app_module
import models.project as project_model
import services.file_manager as file_manager
import services.grading as grading
import services.overview as overview
import services.pdf_splitter as splitter
import services.submissions as submissions
from models.project import ProjectConfig


def configure_temp_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    for module in (
        app_module,
        project_model,
        file_manager,
        grading,
        overview,
        splitter,
        submissions,
    ):
        monkeypatch.setattr(module, "PROJECTS_DIR", projects)
    projects.mkdir()
    return projects


def test_legacy_exam_roster_migrates_to_common_submissions():
    config = ProjectConfig.from_dict({
        "name": "기존 시험",
        "project_type": "exam",
        "exam": {
            "students": [
                {"number": 1, "name": "가"},
                {"number": 2, "name": "나"},
            ],
        },
    })

    assert [(student.number, student.name) for student in config.roster_students] == [
        (1, "가"),
        (2, "나"),
    ]
    assert config.to_dict()["submissions"]["students"][1]["name"] == "나"


def test_roster_status_and_manual_file_reassignment(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    created = client.post(
        "/api/projects",
        json={"name": "답안 연결", "workflow_type": "report"},
    )
    project_id = created.get_json()["id"]

    roster = [
        {"number": 1, "name": "가"},
        {"number": 2, "name": "나"},
    ]
    saved = client.put(f"/api/projects/{project_id}/roster", json={"students": roster})
    assert saved.status_code == 200

    materials_dir = projects / project_id / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    (materials_dir / "1. 가.pdf").write_bytes(b"%PDF-test")
    extra = materials_dir / "9. 다른이름.pdf"
    extra.write_bytes(b"%PDF-test")

    before = client.get(f"/api/projects/{project_id}/submissions").get_json()
    assert before["summary"]["ready"] == 1
    assert before["summary"]["missing"] == 1
    assert before["summary"]["unregistered"] == 1
    assert before["all_ready"] is False

    extra_path = next(
        file["path"]
        for entry in before["entries"]
        if entry["number"] == 9
        for file in entry["files"]
    )
    changed = client.put(
        f"/api/projects/{project_id}/submissions/link",
        json={"file_path": extra_path, "student_number": 2},
    )
    assert changed.status_code == 200
    after = changed.get_json()["status"]
    assert after["summary"]["missing"] == 0
    assert after["summary"]["unregistered"] == 0
    assert after["all_ready"] is True
    linked_file = next(
        file
        for entry in after["entries"]
        if entry["number"] == 2
        for file in entry["files"]
    )
    assert linked_file["manual_link"] is True
    assert linked_file["auto_number"] == 9

    reset = client.delete(
        f"/api/projects/{project_id}/submissions/link",
        json={"file_path": str(extra)},
    )
    assert reset.status_code == 200
    assert reset.get_json()["status"]["summary"]["missing"] == 1


def test_roster_rejects_duplicate_numbers(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    project_id = client.post(
        "/api/projects", json={"name": "중복 명렬"}
    ).get_json()["id"]

    response = client.put(
        f"/api/projects/{project_id}/roster",
        json={"students": [
            {"number": 1, "name": "가"},
            {"number": 1, "name": "나"},
        ]},
    )

    assert response.status_code == 400
    assert "중복" in response.get_json()["error"]


def test_mixed_unmatched_file_is_visible_for_manual_linking(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    project_id = client.post(
        "/api/projects", json={"name": "미인식 파일"}
    ).get_json()["id"]
    client.put(
        f"/api/projects/{project_id}/roster",
        json={"students": [{"number": 1, "name": "가"}]},
    )
    materials_dir = projects / project_id / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    (materials_dir / "1. 가.pdf").write_bytes(b"%PDF-test")
    (materials_dir / "추가답안.pdf").write_bytes(b"%PDF-test")

    status = client.get(f"/api/projects/{project_id}/submissions").get_json()

    assert status["summary"]["file_count"] == 2
    assert status["summary"]["unregistered"] == 1
    assert any(
        file["name"] == "추가답안.pdf"
        for entry in status["entries"]
        for file in entry["files"]
    )


def test_submission_ui_exposes_common_roster_and_split_output():
    client = app_module.app.test_client()
    html = client.get("/").get_data(as_text=True)

    for element_id in ("rosterInput", "submissionSummary", "examSplitOutput"):
        assert f'id="{element_id}"' in html
    assert 'id="examStudents"' not in html
