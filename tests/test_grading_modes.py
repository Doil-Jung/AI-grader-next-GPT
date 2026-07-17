"""채점 방식(자율/핵심/엄격) 프롬프트 분기와 압축 엔드포인트 검증."""
import shutil

import pytest

import app as app_module
from config import PROJECTS_DIR
from models.project import (
    ExamQuestion, ProjectConfig, ScoringElement, generate_exam_prompt,
)


def _config(mode):
    config = ProjectConfig(id="tm", name="모드 테스트")
    config.project_type = "exam"
    config.exam.grading_mode = mode
    config.exam.questions = [ExamQuestion(
        id="q1", number="1", question_text="관성의 법칙을 설명하시오.", max_score=10,
        model_answer="외력이 없으면 운동 상태 유지",
        scoring_elements=[ScoringElement("개념 서술", 6), ScoringElement("예시 제시", 4, required=False)],
        accepted_answers=["뉴턴 제1법칙 서술"],
        common_errors=["관성과 관성력 혼동"],
        core_criteria=["외력 부재 조건 명시 여부", "운동 상태 유지 개념 포함 여부"],
    )]
    return config


def test_autonomous_mode_sends_minimum():
    prompt = generate_exam_prompt(_config("autonomous"))
    assert "모범 답안" in prompt
    assert "스스로 합리적이고 일관되게" in prompt
    # 상세 기준은 전달되지 않는다
    assert "개념 서술" not in prompt
    assert "허용 답안" not in prompt
    assert "주요 감점 사례" not in prompt
    assert "핵심 확인 요소" not in prompt
    # 무응답 규칙은 모든 모드에서 유지된다
    assert "무응답 판정 규칙" in prompt


def test_core_mode_sends_core_criteria_only():
    prompt = generate_exam_prompt(_config("core"))
    assert "핵심 확인 요소" in prompt
    assert "외력 부재 조건 명시 여부" in prompt
    assert "개념 서술" not in prompt      # 상세 부분점 제외
    assert "주요 감점 사례" not in prompt
    assert "무응답 판정 규칙" in prompt


def test_strict_mode_sends_everything_plus_guard():
    prompt = generate_exam_prompt(_config("strict"))
    assert "개념 서술: 6점" in prompt
    assert "허용 답안" in prompt
    assert "주요 감점 사례" in prompt
    assert "기준을 벗어나는 답" in prompt
    assert "무응답 판정 규칙" in prompt


def test_legacy_project_without_mode_reads_as_strict():
    config = _config("strict")
    data = config.to_dict()
    del data["exam"]["grading_mode"]
    loaded = ProjectConfig.from_dict(data)
    assert loaded.exam.grading_mode == "strict"
    # 새 프로젝트 기본값은 자율 선채점
    assert ProjectConfig().exam.grading_mode == "autonomous"


class _FakeProvider:
    def __init__(self, result):
        self.result = result

    def generate_json(self, prompt, *, schema=None, files=None, model_name=None,
                      temperature=0.1, on_step=None):
        return self.result


def test_compress_endpoint_fills_core_criteria(monkeypatch):
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    resp = client.post("/api/projects", json={"name": "압축 테스트", "project_type": "exam"})
    pid = resp.get_json()["id"]
    try:
        create = _FakeProvider({"questions": [{
            "number": "1", "question_text": "문1", "max_score": 10, "model_answer": "답",
            "scoring_elements": [{"description": "개념", "points": 6, "required": True}],
            "accepted_answers": [], "common_errors": [],
        }]})
        monkeypatch.setattr(app_module, "get_provider", lambda cfg, keys: create)
        client.post(f"/api/projects/{pid}/exam/rubric/from-text", json={"text": "1문항 10점"})

        compress = _FakeProvider({"questions": [{
            "number": "1", "core_criteria": ["개념 포함 여부", "논리 전개 타당성"],
        }]})
        monkeypatch.setattr(app_module, "get_provider", lambda cfg, keys: compress)
        resp = client.post(f"/api/projects/{pid}/exam/compress-criteria")
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["updated"] == 1
        assert data["questions"][0]["core_criteria"] == ["개념 포함 여부", "논리 전개 타당성"]
    finally:
        shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)
