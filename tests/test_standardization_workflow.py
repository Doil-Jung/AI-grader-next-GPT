import json

import app as app_module
import models.criteria_versions as criteria_versions
import models.project as project_model
import services.grading as grading
import services.standardization as standardization
from models.project import (
    Category,
    Criterion,
    ExamConfig,
    ExamQuestion,
    ProjectConfig,
    ScoringElement,
)
from services import review


class FakeStandardizationProvider:
    def __init__(self, *, invalid_exam_points=False):
        self.prompts = []
        self.invalid_exam_points = invalid_exam_points

    def generate_json(self, prompt, schema, model_name, temperature):
        self.prompts.append(prompt)
        if "questions" in schema["properties"]:
            return {
                "questions": [{
                    "id": "q1",
                    "number": "1",
                    "model_answer": "힘과 가속도의 관계를 식과 문장으로 설명한다.",
                    "scoring_elements": [
                        {
                            "description": "관계를 올바르게 설명함",
                            "points": 4 if self.invalid_exam_points else 3,
                            "required": True,
                        },
                        {
                            "description": "단위와 방향이 정확함",
                            "points": 2,
                            "required": False,
                        },
                    ],
                    "accepted_answers": ["동치인 벡터식"],
                    "common_errors": ["방향을 반대로 표시"],
                    "core_criteria": ["관계식", "방향과 단위"],
                    "boundary_cases": ["식만 있고 설명이 없는 답"],
                    "teacher_notes": "동치식은 인정",
                    "change_summary": "실제 대안식을 인정 범위에 추가",
                    "rationale": "여러 답안에서 동치식이 반복됨",
                    "evidence_strength": "strong",
                }],
                "overall_note": "실제 답안의 반복 패턴을 중심으로 정리함",
            }
        return {
            "criteria": [{
                "id": "c1",
                "name": "정확성",
                "description": "주장과 자료의 연결이 정확하고 타당하다.",
                "required_elements": ["자료에 근거한 주장"],
                "deduction_rules": ["근거 없는 결론은 한 단계 감점"],
                "exceptions": ["동치인 표현 인정"],
                "feedback_focus": "근거와 결론의 연결",
                "core_criteria": ["자료 근거", "논리적 연결"],
                "boundary_cases": ["결론은 맞지만 근거가 약한 경우"],
                "change_summary": "자료 근거의 구체성을 명시",
                "rationale": "중간 점수대에서 근거 유무가 차이를 만듦",
                "evidence_strength": "moderate",
            }],
            "overall_note": "척도는 유지하고 판정 문구만 구체화함",
        }


def configure_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    for module in (
        app_module,
        project_model,
        criteria_versions,
        grading,
        standardization,
    ):
        if hasattr(module, "PROJECTS_DIR"):
            monkeypatch.setattr(module, "PROJECTS_DIR", projects)
    return projects


def save_round(config, round_id, scores, *, fingerprint="base", version=0):
    for team_number, score in scores.items():
        grading.save_result(
            config.id,
            round_id,
            {
                "team_number": team_number,
                "team_name": "홍길동" if team_number == 1 else f"학생{team_number}",
                "q1_has_answer": True,
                "q1": score,
                "q1_answer_summary": (
                    f"홍길동은 힘과 가속도의 관계를 설명함"
                    if team_number == 1 else "관계를 일부 설명함"
                ),
                "q1_reason": (
                    f"홍길동 답안은 핵심 관계를 {'충족' if score >= 4 else '일부 충족'}함"
                    if team_number == 1 else "핵심 관계를 일부 충족함"
                ),
                "q1_confidence": 0.92,
                "q1_review_required": team_number == 3,
                "total_score": score,
            },
            team_number,
        )
    grading.save_round_metadata(
        config.id,
        round_id,
        {
            "schema_version": 1,
            "round_id": round_id,
            "status": "completed",
            "target_team_numbers": sorted(scores),
            "completed_count": len(scores),
            "execution_context": {
                "provider": "openai_api",
                "model": "test-model",
                "criteria_version": version,
                "criteria_status": "approved" if version else "unversioned",
                "criteria_fingerprint": fingerprint,
            },
            "attempts": [],
            "failures": [],
        },
    )


def make_exam_project(projects):
    config = ProjectConfig(
        id="exam-standardization",
        name="서술형 기준화",
        project_type="exam",
        workflow_type="exam",
        ai_provider="openai_api",
        ai_model="test-model",
        exam=ExamConfig(
            grading_mode="autonomous",
            questions=[ExamQuestion(
                id="q1",
                number="1",
                question_text="힘과 가속도의 관계를 설명하시오.",
                max_score=5,
                model_answer="기존 참고 답",
                scoring_elements=[ScoringElement("관계식", 5, True)],
            )],
        ),
        total_max_score=5,
    )
    project_model.save_project(config)
    return config


def make_report_project(projects):
    config = ProjectConfig(
        id="report-standardization",
        name="보고서 기준화",
        project_type="report",
        workflow_type="report",
        ai_provider="openai_api",
        ai_model="test-model",
        categories=[Category(
            name="내용",
            criteria=[Criterion(
                id="c1",
                name="정확성",
                description="내용이 정확함",
                scale=[5, 3, 1],
                scale_labels=["우수", "보통", "미흡"],
            )],
        )],
        total_max_score=5,
    )
    project_model.save_project(config)
    for round_id, scores in ((1, {1: 5, 2: 3, 3: 1}), (2, {1: 5, 2: 1, 3: 1})):
        for team, score in scores.items():
            grading.save_result(
                config.id,
                round_id,
                {
                    "team_number": team,
                    "team_name": f"학생{team}",
                    "c1": score,
                    "c1_reason": "자료 근거의 구체성에 따라 판정함",
                    "total_score": score,
                },
                team,
            )
        grading.save_round_metadata(
            config.id,
            round_id,
            {
                "round_id": round_id,
                "status": "completed",
                "target_team_numbers": sorted(scores),
                "execution_context": {
                    "provider": "openai_api",
                    "model": "test-model",
                    "criteria_version": 0,
                    "criteria_status": "unversioned",
                    "criteria_fingerprint": "report-base",
                },
                "attempts": [],
                "failures": [],
            },
        )
    return config


def test_exam_draft_is_anonymized_and_does_not_change_active_criteria(
    tmp_path, monkeypatch
):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_exam_project(projects)
    save_round(config, 1, {1: 5, 2: 3, 3: 1})
    save_round(config, 2, {1: 4, 2: 3, 3: 0})
    review.set_manual_score(
        config, 1, total_score=4, item_scores={"q1": 4}
    )
    provider = FakeStandardizationProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda *_: provider)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "key"})

    client = app_module.app.test_client()
    response = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1, 2], "teacher_instruction": "대안식을 확인"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    session = payload["session"]
    assert session["status"] == "draft"
    assert session["source_round_ids"] == [1, 2]
    assert session["student_count"] == 3
    assert session["recommended_sample_teams"]
    assert session["draft"]["questions"][0]["model_answer"].startswith("힘과")
    assert "A001" in provider.prompts[0]
    assert "홍길동" not in provider.prompts[0]

    unchanged = project_model.load_project(config.id)
    assert unchanged.exam.questions[0].model_answer == "기존 참고 답"
    assert unchanged.criteria_state.active_version == 0
    assert (projects / config.id / "standardizations.json").exists()
    assert grading.load_completed(config.id, 1)[1]["q1"] == 5


def test_prompt_evidence_uses_all_stats_but_caps_round_text(tmp_path, monkeypatch):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_exam_project(projects)
    for round_id, score in enumerate([1, 2, 3, 4, 2], 1):
        save_round(config, round_id, {1: score})
    evidence = standardization.collect_evidence(
        config, [1, 2, 3, 4, 5]
    )
    item = evidence["items"][0]
    assert item["observation_count"] == 5
    assert item["score_stats"]["range"] == 3
    sent_rounds = item["representative_answers"][0]["rounds"]
    assert len(sent_rounds) == 3
    assert {value["score"] for value in sent_rounds} >= {1, 4}
    assert sent_rounds[-1]["round_id"] == 5


def test_teacher_approval_creates_approved_version_and_comparison(
    tmp_path, monkeypatch
):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_exam_project(projects)
    save_round(config, 1, {1: 5, 2: 3, 3: 1})
    save_round(config, 2, {1: 4, 2: 3, 3: 0})
    review.set_manual_score(
        config, 1, total_score=4, item_scores={"q1": 4}
    )
    review.set_manual_score(
        config, 2, total_score=3, item_scores={"q1": 3}
    )
    review.set_manual_score(
        config, 3, total_score=1, item_scores={"q1": 1}
    )
    provider = FakeStandardizationProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda *_: provider)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "key"})
    client = app_module.app.test_client()
    session = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1, 2]},
    ).get_json()["session"]

    approved = client.post(
        f"/api/projects/{config.id}/standardizations/{session['id']}/approve",
        json={
            "draft": session["draft"],
            "delivery_mode": "core",
            "teacher_note": "표본 확인 후 승인",
        },
    )
    assert approved.status_code == 200
    data = approved.get_json()
    assert data["session"]["status"] == "approved"
    assert data["version"]["version"] == 1
    assert data["version"]["approved"] is True

    changed = project_model.load_project(config.id)
    assert changed.exam.grading_mode == "core"
    assert changed.exam.questions[0].model_answer.startswith("힘과")
    assert changed.exam.questions[0].core_criteria == ["관계식", "방향과 단위"]
    assert changed.criteria_state.active_version == 1
    assert changed.criteria_state.approved_version == 1
    assert changed.criteria_state.status == "approved"

    save_round(
        changed,
        3,
        {1: 4, 2: 3, 3: 1},
        fingerprint="approved-v1",
        version=1,
    )
    workspace = client.get(
        f"/api/projects/{config.id}/standardizations"
    ).get_json()
    comparison = workspace["sessions"][0]["comparison"]
    assert comparison["status"] == "ready"
    assert comparison["approved_version"] == 1
    assert comparison["baseline_round_ids"] == [1, 2]
    assert comparison["validation_round_ids"] == [3]
    assert comparison["summary"]["student_count"] == 3
    assert comparison["summary"]["after"]["manual_mae"] == 0
    assert grading.load_completed(config.id, 1)[1]["q1"] == 5

    repeated = client.post(
        f"/api/projects/{config.id}/standardizations/{session['id']}/approve",
        json={"draft": session["draft"]},
    )
    assert repeated.status_code == 409


def test_invalid_points_block_approval_and_mixed_rounds_are_rejected(
    tmp_path, monkeypatch
):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_exam_project(projects)
    save_round(config, 1, {1: 5, 2: 3}, fingerprint="one")
    save_round(config, 2, {1: 4, 2: 2}, fingerprint="two")
    provider = FakeStandardizationProvider(invalid_exam_points=True)
    monkeypatch.setattr(app_module, "get_provider", lambda *_: provider)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "key"})
    client = app_module.app.test_client()

    mixed = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1, 2]},
    )
    assert mixed.status_code == 400
    assert "서로 다른 평가기준" in mixed.get_json()["error"]
    assert provider.prompts == []

    draft_response = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1]},
    )
    assert draft_response.status_code == 200
    session = draft_response.get_json()["session"]
    assert session["draft_validation"]["valid"] is False
    assert "초과" in "\n".join(session["draft_validation"]["errors"])
    approval = client.post(
        f"/api/projects/{config.id}/standardizations/{session['id']}/approve",
        json={"draft": session["draft"]},
    )
    assert approval.status_code == 409
    unchanged = project_model.load_project(config.id)
    assert unchanged.exam.questions[0].model_answer == "기존 참고 답"
    assert unchanged.criteria_state.active_version == 0


def test_report_standardization_preserves_scale_and_requires_approval(
    tmp_path, monkeypatch
):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_report_project(projects)
    provider = FakeStandardizationProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda *_: provider)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "key"})
    client = app_module.app.test_client()

    generated = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1, 2]},
    )
    assert generated.status_code == 200
    session = generated.get_json()["session"]
    before = project_model.load_project(config.id)
    assert before.categories[0].criteria[0].description == "내용이 정확함"

    approved = client.post(
        f"/api/projects/{config.id}/standardizations/{session['id']}/approve",
        json={
            "draft": session["draft"],
            "delivery_mode": "core",
        },
    )
    assert approved.status_code == 200
    after = project_model.load_project(config.id)
    criterion = after.categories[0].criteria[0]
    assert criterion.scale == [5, 3, 1]
    assert criterion.description.startswith("주장과 자료")
    assert criterion.core_criteria == ["자료 근거", "논리적 연결"]
    assert after.criteria_state.delivery_mode == "core"
    assert after.criteria_state.status == "approved"


def test_draft_can_be_saved_and_discarded(tmp_path, monkeypatch):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_exam_project(projects)
    save_round(config, 1, {1: 5, 2: 3})
    provider = FakeStandardizationProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda *_: provider)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "key"})
    client = app_module.app.test_client()
    session = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1]},
    ).get_json()["session"]
    session["draft"]["questions"][0]["teacher_notes"] = "교사가 수정함"

    saved = client.put(
        f"/api/projects/{config.id}/standardizations/{session['id']}/draft",
        json={"draft": session["draft"]},
    )
    assert saved.status_code == 200
    assert saved.get_json()["session"]["draft"]["questions"][0]["teacher_notes"] == "교사가 수정함"
    discarded = client.post(
        f"/api/projects/{config.id}/standardizations/{session['id']}/discard",
        json={"reason": "새 선채점 후 다시 생성"},
    )
    assert discarded.status_code == 200
    assert discarded.get_json()["session"]["status"] == "discarded"
    cannot_edit = client.put(
        f"/api/projects/{config.id}/standardizations/{session['id']}/draft",
        json={"draft": session["draft"]},
    )
    assert cannot_edit.status_code == 409


def test_draft_is_blocked_when_active_criteria_changed(tmp_path, monkeypatch):
    projects = configure_projects(tmp_path, monkeypatch)
    config = make_exam_project(projects)
    save_round(config, 1, {1: 5, 2: 3})
    provider = FakeStandardizationProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda *_: provider)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "key"})
    client = app_module.app.test_client()
    session = client.post(
        f"/api/projects/{config.id}/standardizations",
        json={"round_ids": [1]},
    ).get_json()["session"]

    changed = project_model.load_project(config.id)
    changed.exam.questions[0].model_answer = "초안 생성 뒤 교사가 직접 바꾼 답"
    project_model.save_project(changed)
    workspace = client.get(
        f"/api/projects/{config.id}/standardizations"
    ).get_json()
    assert workspace["sessions"][0]["criteria_changed"] is True

    approval = client.post(
        f"/api/projects/{config.id}/standardizations/{session['id']}/approve",
        json={"draft": session["draft"]},
    )
    assert approval.status_code == 409
    assert approval.get_json()["criteria_changed"] is True
    assert project_model.load_project(config.id).criteria_state.active_version == 0


def test_standardization_ui_exposes_safe_workflow():
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert 'id="reportStandardizationCard"' in html
    assert 'id="examStandardizationCard"' in html
    assert "교사 승인 및 새 기준 버전 적용" in html
    assert "표본 재채점 시작" in html
    assert "교사가 승인하기 전에는 실제 채점 기준이 바뀌지 않습니다" in html
