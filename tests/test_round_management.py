from pathlib import Path

import app as app_module
import models.project as project_model
import services.file_manager as file_manager
import services.grading as grading
import services.overview as overview
import services.pdf_splitter as splitter
import services.submissions as submissions
from models.project import Category, Criterion


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


def make_report_project(projects):
    config = project_model.create_project(
        "회차 복구 테스트",
        workflow_type="report",
    )
    config.categories = [Category(
        name="내용",
        criteria=[Criterion(
            id="c1",
            name="정확성",
            description="핵심 내용이 정확함",
            scale=[5, 4, 3],
            scale_labels=["우수", "보통", "미흡"],
            core_criteria=["핵심 개념이 정확한가"],
        )],
    )]
    config.criteria_state.active_version = 3
    config.criteria_state.approved_version = 3
    config.criteria_state.status = "approved"
    project_model.save_project(config)
    materials = projects / config.id / "materials"
    (materials / "1. 가.pdf").write_bytes(b"%PDF-test")
    (materials / "2. 나.pdf").write_bytes(b"%PDF-test")
    return config


def test_round_plan_preserves_success_and_rejects_mixed_context(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    config = make_report_project(projects)

    first = grading.build_grading_plan(
        config,
        repeat_count=2,
        new_round=True,
    )
    assert first["round_id"] == 1
    assert first["target_team_numbers"] == [1, 2]
    assert first["estimate"]["student_rounds"] == 4
    assert first["estimate"]["expected_requests"] == 4
    assert first["estimate"]["estimated_cost_range_krw"] == [80, 400]
    assert first["execution_context"]["criteria_version"] == 3

    metadata = grading.begin_round_attempt(config, first)
    assert metadata["execution_context"]["model"] == "gpt-5.6-luna"
    assert metadata["target_team_numbers"] == [1, 2]

    grading.save_result(
        config.id,
        1,
        {"team_number": 1, "team_name": "가", "total_score": 4},
        1,
    )
    resumed = grading.build_grading_plan(
        config,
        new_round=False,
        round_id=1,
    )
    assert resumed["target_team_numbers"] == [2]
    assert resumed["completed_count"] == 1
    assert resumed["repeat_count"] == 1
    assert resumed["can_start"] is True

    failure = grading.record_round_failure(
        config.id,
        1,
        team_number=2,
        team_name="나",
        error="429 rate limit",
    )
    assert failure["category"] == "rate_limit"
    assert failure["retryable"] is True
    retry = grading.build_grading_plan(
        config,
        new_round=False,
        round_id=1,
        retry_failed=True,
    )
    assert retry["mode"] == "retry_failed"
    assert retry["target_team_numbers"] == [2]

    config.ai_model = "gpt-5.6-terra"
    mixed = grading.build_grading_plan(
        config,
        new_round=False,
        round_id=1,
    )
    assert mixed["can_start"] is False
    assert "새 회차" in mixed["context_error"]


def test_worker_records_result_context_and_clears_failure(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    config = make_report_project(projects)
    # 한 명만 실행해 결과 안의 실행 이력을 검증한다.
    plan = grading.build_grading_plan(
        config,
        new_round=True,
        team_numbers=[1],
    )
    grading.begin_round_attempt(config, plan)
    grading.record_round_failure(
        config.id,
        1,
        team_number=1,
        team_name="가",
        error="timeout",
    )

    class FakeProvider:
        def evaluate_submission(self, *_args, **_kwargs):
            return {
                "team_number": 1,
                "team_name": "가",
                "c1": 4,
                "c1_reason": "핵심 내용이 대체로 정확함",
                "overall_comment": "양호함",
                "seteuk": "핵심 개념을 설명함.",
            }

    monkeypatch.setattr(grading, "get_provider", lambda *_args, **_kwargs: FakeProvider())
    grading.grading_state.update({
        "running": True,
        "should_stop": False,
        "project_id": config.id,
        "current_round": 1,
        "completed_count": 0,
        "total_count": 1,
        "success_count": 0,
        "fail_count": 0,
    })
    grading.grading_worker(config.id, {"openai": "test"}, 0, 1, plan)

    result = grading.load_completed(config.id, 1)[1]
    assert result["total_score"] == 4
    assert result["grading_run"]["round_id"] == 1
    assert result["grading_run"]["model"] == "gpt-5.6-luna"
    assert result["grading_run"]["criteria_version"] == 3
    summary = grading.summarize_round(config, 1, participant_count=1)
    assert summary["status"] == "completed"
    assert summary["failure_count"] == 0
    assert grading.grading_state["running"] is False


def test_regrade_candidates_and_round_ui(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    config = make_report_project(projects)
    client = app_module.app.test_client()

    grading.save_result(
        config.id,
        1,
        {"team_number": 1, "team_name": "가", "total_score": 3},
        1,
    )
    grading.save_result(
        config.id,
        2,
        {
            "team_number": 1,
            "team_name": "가",
            "total_score": 7,
            "review_required_count": 1,
        },
        1,
    )
    response = client.get(
        f"/api/projects/{config.id}/regrade-candidates"
        "?std_threshold=1&range_threshold=2"
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["rounds"] == [1, 2]
    assert data["candidates"][0]["team_number"] == 1
    assert data["candidates"][0]["score_range"] == 4
    assert "AI 검토 필요 표시" in data["candidates"][0]["reasons"]

    html = client.get("/").get_data(as_text=True)
    assert 'id="gradingRunMode"' in html
    assert 'id="gradingRoundList"' in html
    assert 'id="regradeCandidateList"' in html
    assert 'id="repeatCount" type="number" value="2"' in html
    assert 'id="newRound"' not in html


def test_error_categories_give_recovery_actions():
    assert grading.classify_grading_error("quota exceeded")["category"] == "quota"
    assert grading.classify_grading_error("문제가 발생했습니다 (1155)")["category"] == "temporary_provider"
    assert grading.classify_grading_error("PDF 업로드 실패")["category"] == "file"
    assert grading.classify_grading_error("invalid JSON schema")["category"] == "response_format"
