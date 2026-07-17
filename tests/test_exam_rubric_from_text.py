"""텍스트 지시 기반 문항 생성·수정 엔드포인트 검증."""
import shutil

import pytest

import app as app_module
from config import PROJECTS_DIR


class _FakeProvider:
    def __init__(self, result):
        self.result = result
        self.prompts = []

    def generate_json(self, prompt, *, schema=None, files=None, model_name=None,
                      temperature=0.1, on_step=None):
        self.prompts.append(prompt)
        return self.result


@pytest.fixture
def client(monkeypatch):
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _make_project(client, monkeypatch):
    resp = client.post("/api/projects", json={"name": "텍스트문항 테스트", "project_type": "exam"})
    assert resp.status_code == 200
    return resp.get_json()["id"]


def _cleanup(pid):
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)


def test_create_mode_when_no_questions(client, monkeypatch):
    pid = _make_project(client, monkeypatch)
    try:
        fake = _FakeProvider({"questions": [{
            "number": "1", "question_text": "관성의 법칙을 설명하시오.", "max_score": 5,
            "model_answer": "외력이 없으면 운동 상태 유지", 
            "scoring_elements": [{"description": "개념 서술", "points": 3, "required": True},
                                  {"description": "예시 제시", "points": 2, "required": False}],
            "accepted_answers": [], "common_errors": [],
        }]})
        monkeypatch.setattr(app_module, "get_provider", lambda cfg, keys: fake)

        resp = client.post(f"/api/projects/{pid}/exam/rubric/from-text",
                           json={"text": "물리 1문항, 배점 5점, 관성의 법칙"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["mode"] == "create"
        assert len(data["questions"]) == 1
        assert data["total_max_score"] == 5
        assert "교사 설명" in fake.prompts[0]
        # 저장 확인: 다시 조회하면 문항이 남아 있다
        again = client.get(f"/api/projects/{pid}").get_json()
        assert len(again["exam"]["questions"]) == 1
    finally:
        _cleanup(pid)


def test_revise_mode_passes_current_questions(client, monkeypatch):
    pid = _make_project(client, monkeypatch)
    try:
        create = _FakeProvider({"questions": [{
            "number": "1", "question_text": "문1", "max_score": 5, "model_answer": "답",
            "scoring_elements": [{"description": "전체", "points": 5, "required": True}],
            "accepted_answers": [], "common_errors": [],
        }]})
        monkeypatch.setattr(app_module, "get_provider", lambda cfg, keys: create)
        client.post(f"/api/projects/{pid}/exam/rubric/from-text", json={"text": "1문항 5점"})

        revise = _FakeProvider({"questions": [{
            "number": "1", "question_text": "문1", "max_score": 5, "model_answer": "답",
            "scoring_elements": [{"description": "식 세우기", "points": 3, "required": True},
                                  {"description": "계산", "points": 2, "required": True}],
            "accepted_answers": [], "common_errors": [],
        }]})
        monkeypatch.setattr(app_module, "get_provider", lambda cfg, keys: revise)
        resp = client.post(f"/api/projects/{pid}/exam/rubric/from-text",
                           json={"text": "1번 부분점을 식 3점, 계산 2점으로 나눠줘"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["mode"] == "revise"
        assert "현재 문항 목록" in revise.prompts[0]
        assert len(data["questions"][0]["scoring_elements"]) == 2
    finally:
        _cleanup(pid)


def test_empty_text_rejected(client, monkeypatch):
    pid = _make_project(client, monkeypatch)
    try:
        resp = client.post(f"/api/projects/{pid}/exam/rubric/from-text", json={"text": "  "})
        assert resp.status_code == 400
    finally:
        _cleanup(pid)
