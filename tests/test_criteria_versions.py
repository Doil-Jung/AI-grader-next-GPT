import app as app_module
import models.criteria_versions as criteria_versions
import models.project as project_model
from models.project import ProjectConfig, generate_default_prompt


def configure_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    for module in (app_module, project_model, criteria_versions):
        monkeypatch.setattr(module, "PROJECTS_DIR", projects)
    return projects


def report_categories(description="정확한 설명"):
    return [{
        "name": "내용",
        "criteria": [{
            "id": "c1",
            "name": "정확성",
            "description": description,
            "scale": [5, 3, 1],
            "scale_labels": ["우수", "보통", "미흡"],
            "required_elements": ["핵심 개념"],
            "deduction_rules": ["근거 없으면 감점"],
            "exceptions": ["동치 표현 인정"],
            "feedback_focus": "개념 연결",
            "core_criteria": ["핵심 개념이 정확한가"],
        }],
    }]


def test_report_detailed_and_compact_criteria_round_trip():
    config = ProjectConfig.from_dict({
        "name": "보고서",
        "criteria_state": {"delivery_mode": "core"},
        "categories": report_categories(),
    })

    criterion = config.all_criteria[0]
    assert criterion.required_elements == ["핵심 개념"]
    assert criterion.deduction_rules == ["근거 없으면 감점"]
    assert criterion.exceptions == ["동치 표현 인정"]
    prompt = generate_default_prompt(config)
    assert "AI 핵심 기준" in prompt
    assert "핵심 개념이 정확한가" in prompt

    config.criteria_state.delivery_mode = "strict"
    strict_prompt = generate_default_prompt(config)
    assert "피드백 관점: 개념 연결" in strict_prompt


def test_project_creation_keeps_detailed_report_criteria(tmp_path, monkeypatch):
    configure_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    created = client.post(
        "/api/projects",
        json={"name": "상세 기준", "categories": report_categories()},
    )
    project = client.get(
        f"/api/projects/{created.get_json()['id']}"
    ).get_json()

    criterion = project["categories"][0]["criteria"][0]
    assert criterion["required_elements"] == ["핵심 개념"]
    assert criterion["deduction_rules"] == ["근거 없으면 감점"]
    assert criterion["core_criteria"] == ["핵심 개념이 정확한가"]


def test_report_versions_can_be_saved_approved_and_restored(tmp_path, monkeypatch):
    configure_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    project_id = client.post(
        "/api/projects", json={"name": "보고서 버전"}
    ).get_json()["id"]
    client.put(
        f"/api/projects/{project_id}",
        json={"categories": report_categories("처음 기준")},
    )

    created = client.post(
        f"/api/projects/{project_id}/criteria-versions",
        json={"source": "manual"},
    )
    assert created.status_code == 200
    assert created.get_json()["version"]["version"] == 1

    approved = client.post(
        f"/api/projects/{project_id}/criteria-versions/1/approve"
    )
    assert approved.status_code == 200
    assert approved.get_json()["state"]["status"] == "approved"

    client.put(
        f"/api/projects/{project_id}",
        json={"categories": report_categories("수정된 기준")},
    )
    listing = client.get(
        f"/api/projects/{project_id}/criteria-versions"
    ).get_json()
    assert listing["state"]["active_version"] == 0
    assert listing["state"]["status"] == "modified"

    restored = client.post(
        f"/api/projects/{project_id}/criteria-versions/1/restore"
    )
    assert restored.status_code == 200
    project = restored.get_json()["project"]
    assert project["categories"][0]["criteria"][0]["description"] == "처음 기준"
    assert project["criteria_state"]["status"] == "approved"


def test_exam_score_mismatch_blocks_approval(tmp_path, monkeypatch):
    configure_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    project_id = client.post(
        "/api/projects",
        json={"name": "배점 오류", "project_type": "exam"},
    ).get_json()["id"]
    client.put(
        f"/api/projects/{project_id}",
        json={"exam": {"questions": [
            {"id": "q1", "number": "1", "max_score": 10, "question_text": "공통"},
            {
                "id": "q1a", "number": "1-(1)", "max_score": 4,
                "question_text": "가", "model_answer": "답",
                "parent_id": "q1", "sub_index": 1,
            },
            {
                "id": "q1b", "number": "1-(2)", "max_score": 5,
                "question_text": "나", "model_answer": "답",
                "parent_id": "q1", "sub_index": 2,
            },
        ]}},
    )
    created = client.post(
        f"/api/projects/{project_id}/criteria-versions", json={}
    ).get_json()
    assert created["validation"]["valid"] is False

    approved = client.post(
        f"/api/projects/{project_id}/criteria-versions/1/approve"
    )
    assert approved.status_code == 409
    assert "소문항 합" in "\n".join(
        approved.get_json()["validation"]["errors"]
    )


def test_criteria_version_ui_is_present():
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert 'id="reportCriteriaVersionCard"' in html
    assert 'id="examCriteriaVersionCard"' in html
    assert "현재 기준을 새 버전으로 저장" in html
