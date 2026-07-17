"""독립 검증 패스(답 존재 교차 확인) 동작 검증."""
from models.evaluation import compute_scores
from models.project import ExamQuestion, ProjectConfig
from services.grading import build_existence_schema, verify_answer_existence


def _exam_config():
    config = ProjectConfig(id="t1", name="검증 테스트")
    config.project_type = "exam"
    config.exam.questions = [
        ExamQuestion(id="q1", number="1", question_text="문1", max_score=5),
        ExamQuestion(id="q2", number="2", question_text="문2", max_score=10),
    ]
    return config


class _FakeProvider:
    def __init__(self, verification):
        self.verification = verification
        self.calls = []

    def generate_json(self, prompt, *, schema=None, files=None, model_name=None,
                      temperature=0.1, on_step=None):
        self.calls.append({"prompt": prompt, "schema": schema, "files": files})
        return self.verification


def test_existence_schema_has_exists_and_quote():
    schema = build_existence_schema(_exam_config().exam.questions)
    assert "q1_exists" in schema["properties"]
    assert "q2_quote" in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"].keys())


def test_hallucinated_score_is_zeroed_by_verification():
    config = _exam_config()
    # 채점 모델이 2번(무응답)에 has_answer=true + 10점을 환각한 상황.
    result = {
        "q1_has_answer": True, "q1": 4, "q1_answer_summary": "관성 설명",
        "q1_reason": "핵심 개념", "q1_confidence": 0.9, "q1_review_required": False,
        "q2_has_answer": True, "q2": 10, "q2_answer_summary": "가속도 법칙 서술",
        "q2_reason": "완전한 답", "q2_confidence": 0.8, "q2_review_required": False,
    }
    provider = _FakeProvider({
        "q1_exists": True, "q1_quote": "물체는 외력이 없으면",
        "q2_exists": False, "q2_quote": "",
    })

    verify_answer_existence(provider, config, [{"path": "a.pdf"}], result)
    final = compute_scores(config, result)

    assert final["q2"] == 0
    assert final["q2_answer_summary"] == "무응답"
    assert final["q2_review_required"] is True
    assert "검증 패스" in result["q2_reason"]
    assert final["total_score"] == 4
    # 검증 인용은 근거 자료로 저장된다.
    assert final["q1_evidence"] == "물체는 외력이 없으면"


def test_missed_answer_gets_review_flag_not_score_change():
    config = _exam_config()
    # 채점은 무응답 처리했는데 검증 패스는 답이 있다고 판정한 상황.
    result = {
        "q1_has_answer": True, "q1": 4, "q1_answer_summary": "관성 설명",
        "q1_reason": "핵심 개념", "q1_confidence": 0.9, "q1_review_required": False,
        "q2_has_answer": False, "q2": 0, "q2_answer_summary": "무응답",
        "q2_reason": "답 없음", "q2_confidence": 0.9, "q2_review_required": True,
    }
    provider = _FakeProvider({
        "q1_exists": True, "q1_quote": "물체는 외력이 없으면",
        "q2_exists": True, "q2_quote": "F=ma에 따라",
    })

    verify_answer_existence(provider, config, [{"path": "a.pdf"}], result)
    final = compute_scores(config, result)

    assert final["q2"] == 0  # 점수는 올리지 않는다 (교사 판단)
    assert final["q2_review_required"] is True
    assert "교사 확인 필요" in result["q2_reason"]
