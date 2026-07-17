from models.evaluation import build_evaluation_model, compute_scores
import json
from pathlib import Path

import models.project as project_model
from models.project import ProjectConfig, generate_default_prompt


def test_legacy_project_defaults_to_report():
    config = ProjectConfig.from_dict({"name": "기존 프로젝트", "categories": []})
    assert config.project_type == "report"
    assert config.ai_provider == "gemini_api"
    assert config.exam.questions == []


def test_legacy_google_provider_is_migrated():
    config = ProjectConfig.from_dict({
        "id": "legacy",
        "name": "기존 프로젝트",
        "ai_provider": "google",
    })

    assert config.ai_provider == "gemini_api"


def test_openai_is_default_and_legacy_gemini_alias_is_migrated():
    assert ProjectConfig().ai_provider == "openai_api"
    assert ProjectConfig().ai_model == "gpt-5.6-luna"
    config = ProjectConfig.from_dict({
        "name": "이전 모델 프로젝트",
        "ai_model": "gemini-3-flash-preview",
    })
    assert config.ai_model == "gemini-3.5-flash"


def test_removed_web_provider_is_migrated_to_supported_openai_provider():
    config = ProjectConfig.from_dict({
        "name": "정액형 프로젝트",
        "ai_provider": "gemini_web",
        "ai_model": "gemini-3.5-flash",
    })
    assert config.ai_provider == "openai_api"
    assert config.ai_model == "gpt-5.6-luna"


def test_exam_schema_and_score_computation():
    config = ProjectConfig.from_dict({
        "project_type": "exam",
        "exam": {
            "questions": [{
                "id": "q1", "number": "1", "question_text": "설명하시오.",
                "max_score": 5, "model_answer": "모범 답안",
                "scoring_elements": [{"description": "핵심 개념", "points": 3, "required": True}],
            }]
        },
    })
    model = build_evaluation_model(config)
    value = model(
        team_number=1, team_name="학생 1", q1=4,
        q1_has_answer=True,
        q1_answer_summary="핵심 개념을 설명함", q1_reason="한 요소가 부족함",
        q1_confidence=0.8, q1_review_required=False, overall_comment="검토 의견",
    )
    result = compute_scores(config, value.model_dump())
    assert result["total_score"] == 4
    assert result["teacher_status"] == "pending"
    assert result["review_required_count"] == 0


def test_exam_additional_instructions_are_saved_and_added_to_prompt():
    config = ProjectConfig.from_dict({
        "name": "공식 기준 시험",
        "project_type": "exam",
        "exam": {
            "additional_instructions": "단위 누락은 1점 감점",
            "questions": [{
                "number": "1", "question_text": "설명", "max_score": 5,
                "model_answer": "답", "scoring_elements": [{"description": "핵심", "points": 5}],
            }],
        },
    })

    assert config.exam.additional_instructions == "단위 누락은 1점 감점"
    prompt = generate_default_prompt(config)
    assert "교사 추가 채점 지침" in prompt
    assert "단위 누락은 1점 감점" in prompt


def test_exam_source_paths_are_portable_across_windows_accounts(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    monkeypatch.setattr(project_model, "PROJECTS_DIR", projects)
    project_id = "20260715_120000_portable"
    local_source = projects / project_id / "exam_sources" / "questions.pdf"
    local_source.parent.mkdir(parents=True)
    local_source.write_bytes(b"test")

    stale_source = Path(
        rf"C:\Users\user\OneDrive - 학교\코딩\projects\{project_id}"
        rf"\exam_sources\questions.pdf"
    )
    config = ProjectConfig.from_dict({
        "id": project_id,
        "name": "학교에서 만든 프로젝트",
        "project_type": "exam",
        "schema_version": 2,
        "exam": {
            "question_source_path": str(stale_source),
            "source_mode": "combined_answers",
            "expected_question_count": 4,
        },
    })

    project_model.save_project(config)
    raw = json.loads((projects / project_id / "config.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == project_model.CURRENT_SCHEMA_VERSION
    assert raw["exam"]["question_source_path"] == "exam_sources/questions.pdf"
    assert raw["exam"]["source_mode"] == "combined_answers"
    assert raw["exam"]["expected_question_count"] == 4
    assert project_model.resolve_project_path(
        project_id,
        stale_source,
        expected_subdir="exam_sources",
    ) == local_source.resolve()
