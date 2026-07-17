"""무응답 문항 0점 강제(has_answer) 검증."""
from models.evaluation import build_evaluation_model, compute_scores
from models.project import ExamQuestion, ProjectConfig


def _exam_config():
    config = ProjectConfig(id="t1", name="테스트 시험")
    config.project_type = "exam"
    config.exam.questions = [
        ExamQuestion(id="q1", number="1", question_text="문1", max_score=5),
        ExamQuestion(id="q7", number="7", question_text="문7", max_score=4),
    ]
    return config


def test_model_includes_has_answer_fields():
    model = build_evaluation_model(_exam_config())
    fields = model.model_fields
    assert "q1_has_answer" in fields
    assert "q7_has_answer" in fields


def test_no_answer_question_is_forced_to_zero():
    config = _exam_config()
    # 모델이 무응답(7번)에 환각으로 2점을 준 상황을 재현한다.
    graded = {
        "q1_has_answer": True, "q1": 4, "q1_answer_summary": "관성의 법칙 설명",
        "q1_reason": "핵심 개념 서술", "q1_confidence": 0.9, "q1_review_required": False,
        "q7_has_answer": False, "q7": 2, "q7_answer_summary": "마찰력 언급",
        "q7_reason": "부분 개념 포함", "q7_confidence": 0.6, "q7_review_required": False,
    }

    result = compute_scores(config, graded)

    assert result["q7"] == 0
    assert result["q7_answer_summary"] == "무응답"
    assert result["q7_review_required"] is True
    assert "무효화" in result["q7_reason"]
    assert result["total_score"] == 4  # q1 점수만 합산
    assert result["review_required_count"] == 1


def test_answered_question_is_untouched():
    config = _exam_config()
    graded = {
        "q1_has_answer": True, "q1": 5, "q1_answer_summary": "정답",
        "q1_reason": "완전한 답", "q1_confidence": 0.95, "q1_review_required": False,
        "q7_has_answer": True, "q7": 3, "q7_answer_summary": "부분 정답",
        "q7_reason": "요소 일부 충족", "q7_confidence": 0.8, "q7_review_required": False,
    }

    result = compute_scores(config, graded)

    assert result["q1"] == 5 and result["q7"] == 3
    assert result["total_score"] == 8


def test_legacy_results_without_has_answer_are_unchanged():
    config = _exam_config()
    graded = {"q1": 3, "q7": 2}

    result = compute_scores(config, graded)

    assert result["q1"] == 3 and result["q7"] == 2
    assert result["total_score"] == 5
