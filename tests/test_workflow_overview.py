from pathlib import Path

import app as app_module
import models.project as project_model
import services.file_manager as file_manager
import services.grading as grading
import services.overview as overview
import services.pdf_splitter as splitter
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
    ):
        monkeypatch.setattr(module, "PROJECTS_DIR", projects)
    projects.mkdir()
    return projects


def test_legacy_projects_infer_visible_workflow_without_changing_engine():
    report = ProjectConfig.from_dict({"name": "기존 보고서", "project_type": "report"})
    exam = ProjectConfig.from_dict({"name": "기존 시험", "project_type": "exam"})

    assert report.workflow_type == "report"
    assert report.project_type == "report"
    assert exam.workflow_type == "exam"
    assert exam.project_type == "exam"


def test_competition_workflow_uses_report_engine_and_round_trips(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()

    created = client.post(
        "/api/projects",
        json={
            "name": "과학 탐구 심사",
            "workflow_type": "competition",
            "setup": {
                "target": "전교생",
                "assessment_name": "과학 탐구 발표대회",
                "participant_mode": "group",
                "expected_count": 12,
                "materials_status": "rubric_ready",
                "ai_setup_mode": "recommended",
            },
        },
    )
    assert created.status_code == 200
    project_id = created.get_json()["id"]

    detail = client.get(f"/api/projects/{project_id}").get_json()
    assert detail["workflow_type"] == "competition"
    assert detail["project_type"] == "report"
    assert detail["setup"]["participant_mode"] == "group"
    assert detail["setup"]["expected_count"] == 12

    listed = client.get("/api/projects").get_json()
    assert listed[0]["workflow_type"] == "competition"
    assert listed[0]["project_type"] == "report"


def test_overview_recommends_the_next_incomplete_stage(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()

    created = client.post(
        "/api/projects",
        json={
            "name": "단계 안내",
            "workflow_type": "competition",
            "setup": {"expected_count": 2},
        },
    )
    project_id = created.get_json()["id"]

    first = client.get(f"/api/projects/{project_id}/overview").get_json()
    assert first["next_action"]["stage"] == "criteria"

    client.put(
        f"/api/projects/{project_id}",
        json={
            "categories": [{
                "name": "내용",
                "criteria": [{
                    "id": "c1",
                    "name": "정확성",
                    "description": "내용이 정확함",
                    "scale": [5, 4, 3],
                    "scale_labels": ["우수", "보통", "미흡"],
                }],
            }],
        },
    )
    second = client.get(f"/api/projects/{project_id}/overview").get_json()
    assert second["next_action"]["stage"] == "submissions"

    materials_dir = projects / project_id / "materials"
    materials_dir.mkdir(exist_ok=True)
    (materials_dir / "1. 가.pdf").write_bytes(b"%PDF-test")
    (materials_dir / "2. 나.pdf").write_bytes(b"%PDF-test")
    third = client.get(f"/api/projects/{project_id}/overview").get_json()
    assert third["submissions"]["participant_count"] == 2
    assert third["next_action"]["stage"] == "grading"

    grading.save_result(
        project_id,
        1,
        {"team_number": 1, "team_name": "가", "total_score": 4},
        1,
    )
    grading.save_result(
        project_id,
        1,
        {"team_number": 2, "team_name": "나", "total_score": 5},
        2,
    )
    finished = client.get(f"/api/projects/{project_id}/overview").get_json()
    assert finished["grading"]["latest_completed_count"] == 2
    assert finished["next_action"]["stage"] == "analysis"


def test_app_shell_exposes_three_workflows_and_six_workspace_stages():
    client = app_module.app.test_client()
    html = client.get("/").get_data(as_text=True)

    for workflow in ("report", "competition", "exam"):
        assert f'data-workflow-type="{workflow}"' in html
    for stage in ("overview", "criteria", "submissions", "grading", "review", "analysis"):
        assert f'data-stage="{stage}"' in html
