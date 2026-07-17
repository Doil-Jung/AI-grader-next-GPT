from models.evaluation import build_evaluation_model, compute_scores
import app as app_module
from models.project import ExamQuestion, ProjectConfig, generate_default_prompt


def make_exam(questions):
    return ProjectConfig.from_dict({
        "name": "소문항 시험",
        "project_type": "exam",
        "exam": {"questions": questions},
    })


def test_subquestions_are_the_only_scored_units_and_sum_to_total():
    config = make_exam([
        {
            "id": "q1", "number": "1", "question_text": "공통 지문",
            "max_score": 10, "model_answer": "",
        },
        {
            "id": "q1a", "number": "1-(1)", "question_text": "값",
            "max_score": 4, "model_answer": "4", "parent_id": "q1",
            "sub_index": 1, "answer_type": "short",
        },
        {
            "id": "q1b", "number": "1-(2)", "question_text": "유도",
            "max_score": 6, "model_answer": "식", "parent_id": "q1",
            "sub_index": 2, "answer_type": "formula",
        },
    ])

    assert [question.id for question in config.exam.scored_questions()] == [
        "q1a", "q1b"
    ]
    assert config.exam.scored_max_score == 10
    assert config.exam.score_validation() == []

    model = build_evaluation_model(config)
    fields = model.model_fields
    assert "q1" not in fields
    assert {"q1a", "q1b"} <= set(fields)

    value = model(
        team_number=1,
        team_name="학생",
        q1a_has_answer=True,
        q1a=3,
        q1a_answer_summary="값",
        q1a_reason="근거",
        q1a_confidence=0.9,
        q1a_review_required=False,
        q1b_has_answer=True,
        q1b=5,
        q1b_answer_summary="유도",
        q1b_reason="근거",
        q1b_confidence=0.8,
        q1b_review_required=False,
        overall_comment="",
    )
    result = compute_scores(config, value.model_dump())
    assert result["total_score"] == 8


def test_parent_score_mismatch_is_reported_and_prompt_shows_structure():
    config = make_exam([
        {
            "id": "q1", "number": "1", "question_text": "공통 지문",
            "max_score": 9,
        },
        {
            "id": "q1a", "number": "1-(1)", "question_text": "설명",
            "max_score": 4, "model_answer": "답", "parent_id": "q1",
            "sub_index": 1, "answer_type": "diagram",
        },
        {
            "id": "q1b", "number": "1-(2)", "question_text": "계산",
            "max_score": 6, "model_answer": "답", "parent_id": "q1",
            "sub_index": 2, "answer_type": "formula",
            "grading_mode": "core", "core_criteria": ["식 설정"],
        },
    ])

    assert config.exam.score_validation()[0]["child_score"] == 10
    prompt = generate_default_prompt(config)
    assert "대문항 묶음" in prompt
    assert "직접 점수를 출력하지 말고" in prompt
    assert "그래프·도식형" in prompt
    assert "수식·계산형" in prompt
    assert "핵심 확인 요소" in prompt


def test_legacy_flat_questions_remain_scored_and_new_fields_round_trip():
    config = make_exam([
        {
            "id": "q1", "number": "1", "question_text": "설명",
            "max_score": 5, "model_answer": "답",
            "answer_type": "mixed", "grading_mode": "strict",
            "teacher_notes": "교사용",
        },
    ])

    reloaded = ProjectConfig.from_dict(config.to_dict())
    question = reloaded.exam.scored_questions()[0]
    assert question.id == "q1"
    assert question.answer_type == "mixed"
    assert question.grading_mode == "strict"
    assert question.teacher_notes == "교사용"


def test_audit_merge_preserves_parent_links_when_each_batch_reuses_ids():
    first = [
        ExamQuestion("q1", "1", "공통 1", 10),
        ExamQuestion(
            "q2", "1-(1)", "가", 4, parent_id="q1", sub_index=1
        ),
    ]
    second = [
        # 별도 AI 응답이라 id가 다시 q1부터 시작해도 안전해야 한다.
        ExamQuestion("q1", "2", "공통 2", 6),
        ExamQuestion(
            "q2", "2-(1)", "나", 6, parent_id="q1", sub_index=1
        ),
    ]

    merged = app_module._merge_question_candidates(first, second)
    config = make_exam([vars(question) for question in merged])

    assert [question.number for question in config.exam.top_level_questions()] == [
        "1", "2"
    ]
    assert [question.number for question in config.exam.scored_questions()] == [
        "1-(1)", "2-(1)"
    ]
    assert len({question.id for question in merged}) == 4


def test_expected_question_warning_counts_main_questions_not_subquestions():
    config = make_exam([
        {"id": "q1", "number": "1", "question_text": "공통", "max_score": 5},
        {
            "id": "q1a", "number": "1-(1)", "question_text": "가",
            "max_score": 2, "parent_id": "q1", "sub_index": 1,
        },
        {
            "id": "q1b", "number": "1-(2)", "question_text": "나",
            "max_score": 3, "parent_id": "q1", "sub_index": 2,
        },
    ])

    warnings = app_module._exam_extraction_warnings(
        config.exam.questions, detected=[1], expected_count=1
    )
    assert not any("예상 대문항 수" in warning for warning in warnings)
