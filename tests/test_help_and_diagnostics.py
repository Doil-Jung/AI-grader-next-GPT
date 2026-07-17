import re

import app as app_module
import models.project as project_model
import services.diagnostics as diagnostics
import services.file_manager as file_manager
import services.grading as grading
import services.overview as overview
import services.pdf_splitter as splitter
import services.review as review
import services.submissions as submissions


def configure_temp_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    for module in (
        app_module,
        project_model,
        diagnostics,
        file_manager,
        grading,
        overview,
        splitter,
        submissions,
    ):
        monkeypatch.setattr(module, "PROJECTS_DIR", projects)
    monkeypatch.setattr(app_module, "API_KEY_FILE", tmp_path / ".api_keys.json")
    projects.mkdir()
    return projects


def test_sample_project_contains_virtual_full_workflow(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()

    response = client.post("/api/sample-project")

    assert response.status_code == 200
    project = response.get_json()["project"]
    config = project_model.load_project(project["id"])
    assert config.name.startswith("샘플 -")
    assert len(config.roster_students) == 5
    assert all(student.name.startswith("가상학생") for student in config.roster_students)
    materials = file_manager.find_materials(config)
    assert len(materials) == 5
    assert sum(len(item["files"]) for item in materials) == 5
    rounds = grading.list_round_summaries(config, participant_count=5)
    assert len(rounds) == 2
    assert all(item["completed_count"] == 5 for item in rounds)
    dashboard = review.build_review_dashboard(
        config, participant_numbers=[1, 2, 3, 4, 5]
    )
    assert dashboard["summary"]["manual_count"] == 5
    assert dashboard["summary"]["effective_approved_count"] == 5
    assert not any(path.suffix.lower() == ".pdf" for path in projects.rglob("*"))


def test_diagnostics_reports_environment_without_exposing_keys(
    tmp_path, monkeypatch
):
    configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    sample = client.post("/api/sample-project").get_json()["project"]
    app_module.save_api_keys({
        "openai": "sk-test-secret-do-not-expose",
        "google": "AIza-test-secret-do-not-expose",
    })

    response = client.get(
        f"/api/diagnostics?project_id={sample['id']}"
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["app_version"] == diagnostics.APP_VERSION
    assert data["projects_writable"] is True
    assert data["api_keys"] == {"google": True, "openai": True}
    assert data["project"]["participant_count"] == 5
    assert data["project"]["full_round_count"] == 2
    assert data["project"]["approved_count"] == 5
    assert "secret-do-not-expose" not in response.get_data(as_text=True)


def test_help_ui_and_bundled_manual_routes(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()

    root = client.get("/")
    html = root.get_data(as_text=True)
    assert root.status_code == 200
    for value in (
        "helpModal",
        "helpCurrentTitle",
        "sampleProjectButton",
        "helpDiagnostics",
        "교사용 도움말",
    ):
        assert value in html
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))

    quick = client.get("/api/manual/quick-start")
    trouble = client.get("/api/manual/troubleshooting")
    checklist = client.get("/api/manual/release-checklist")
    assert quick.status_code == trouble.status_code == checklist.status_code == 200
    assert "공통 순서" in quick.get_data(as_text=True)
    assert "쿼터" in trouble.get_data(as_text=True)
    assert "EXE 빌드" in checklist.get_data(as_text=True)
    assert client.get("/api/manual/unknown").status_code == 404
