"""처음 사용하는 교사가 API 호출 없이 둘러볼 수 있는 가상 프로젝트."""

from __future__ import annotations

from models.project import (
    Category,
    Criterion,
    ProjectSetup,
    StudentRecord,
    create_project,
    save_project,
)
from services import grading as grading_service
from services.grading import save_result, save_round_metadata
from services.review import approve_final_score, set_manual_score


SAMPLE_STUDENTS = [
    (1, "가상학생01", (9, 9), (10, 8), (9, 9)),
    (2, "가상학생02", (8, 7), (8, 8), (8, 7)),
    (3, "가상학생03", (6, 6), (7, 6), (6, 6)),
    (4, "가상학생04", (9, 8), (8, 8), (9, 8)),
    (5, "가상학생05", (4, 2), (5, 2), (4, 2)),
]


def create_sample_project():
    config = create_project(
        "샘플 - 과학 탐구보고서",
        "실제 학생 정보와 AI 호출 없이 전체 흐름을 연습하는 가상 프로젝트입니다.",
        workflow_type="report",
    )
    config.materials.file_types = ["txt"]
    config.setup = ProjectSetup(
        target="가상 학급",
        assessment_name="가상 과학 탐구보고서",
        participant_mode="individual",
        expected_count=5,
        materials_status="ready",
        ai_setup_mode="recommended",
    )
    config.categories = [
        Category("내용", [
            Criterion(
                id="c1",
                name="과학적 정확성",
                description="핵심 개념과 자료 해석이 과학적으로 타당한가",
                scale=[10, 8, 6, 4, 2],
                scale_labels=["매우 우수", "우수", "보통", "미흡", "매우 미흡"],
                core_criteria=["핵심 개념 정확성", "자료와 결론의 일치"],
            ),
            Criterion(
                id="c2",
                name="논리적 설명",
                description="근거와 결론을 논리적으로 연결했는가",
                scale=[10, 8, 6, 4, 2],
                scale_labels=["매우 우수", "우수", "보통", "미흡", "매우 미흡"],
                core_criteria=["근거 제시", "결론과의 연결"],
            ),
        ])
    ]
    config.criteria_state.status = "unversioned"
    config.submissions.students = [
        StudentRecord(
            number=number,
            name=name,
            grade="가상",
            class_name="연습",
            student_id=f"SAMPLE-{number:03d}",
        )
        for number, name, *_ in SAMPLE_STUDENTS
    ]
    config.prompt_template = (
        "가상 과학 탐구보고서를 과학적 정확성과 논리적 설명으로 평가한다."
    )
    config.total_max_score = 20
    save_project(config)

    materials = grading_service.PROJECTS_DIR / config.id / "materials"
    materials.mkdir(parents=True, exist_ok=True)
    for number, name, *_ in SAMPLE_STUDENTS:
        (materials / f"{number}. {name}.txt").write_text(
            "이 문서는 기능 연습을 위한 가상 탐구보고서입니다.\n"
            f"가상 제출자: {name}\n"
            "관찰 자료를 바탕으로 가설을 검토하고 근거와 결론을 연결했습니다.",
            encoding="utf-8",
        )

    for round_id, score_index in ((1, 2), (2, 3)):
        for number, name, _manual, first, second in SAMPLE_STUDENTS:
            scores = first if score_index == 2 else second
            c1, c2 = scores
            save_result(
                config.id,
                round_id,
                {
                    "team_number": number,
                    "team_name": name,
                    "c1": c1,
                    "c1_answer_summary": "핵심 개념과 관찰 자료를 연결함",
                    "c1_reason": "자료 해석의 정확성을 기준으로 평가함",
                    "c1_confidence": 0.85,
                    "c1_review_required": False,
                    "c2": c2,
                    "c2_answer_summary": "근거에서 결론으로 이어지는 설명을 제시함",
                    "c2_reason": "근거와 결론의 논리적 연결을 기준으로 평가함",
                    "c2_confidence": 0.8,
                    "c2_review_required": number == 5,
                    "total_score": c1 + c2,
                    "overall_comment": "강점과 보완점을 함께 확인하는 가상 피드백입니다.",
                    "seteuk": "자료를 근거로 과학적 결론을 설명하는 역량을 보임.",
                },
                number,
            )
        save_round_metadata(
            config.id,
            round_id,
            {
                "status": "completed",
                "execution_context": {
                    "provider": "sample",
                    "model": "synthetic-data",
                    "criteria_version": 0,
                    "criteria_status": "unversioned",
                },
                "target_team_numbers": [
                    number for number, *_ in SAMPLE_STUDENTS
                ],
                "started_at": "",
                "finished_at": "",
                "request_plan": {
                    "expected_requests": 0,
                    "estimated_minutes_range": [0, 0],
                    "estimated_cost_range_krw": [0, 0],
                },
            },
        )

    participants = [number for number, *_ in SAMPLE_STUDENTS]
    for number, _name, manual, _first, _second in SAMPLE_STUDENTS:
        c1, c2 = manual
        set_manual_score(
            config,
            number,
            total_score=c1 + c2,
            item_scores={"c1": c1, "c2": c2},
            source="sample",
        )
        approve_final_score(
            config,
            number,
            final_total_score=c1 + c2,
            item_scores={"c1": c1, "c2": c2},
            teacher_note="가상 샘플 확정",
            decision_source="manual",
            basis_rounds=[1, 2],
            participant_numbers=participants,
        )
    return config
