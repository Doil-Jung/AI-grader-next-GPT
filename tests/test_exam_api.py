import io
import re
from pathlib import Path

from pypdf import PdfWriter

import app as app_module
import models.project as project_model
import services.file_manager as file_manager
import services.grading as grading
import services.pdf_splitter as splitter
import services.submissions as submissions


def pdf_bytes(pages: int) -> io.BytesIO:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    stream = io.BytesIO()
    writer.write(stream)
    stream.seek(0)
    return stream


def configure_temp_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    for module in (app_module, project_model, file_manager, grading, splitter, submissions):
        monkeypatch.setattr(module, "PROJECTS_DIR", projects)
    projects.mkdir()
    return projects


def test_exam_upload_split_and_approval_flow(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()

    created = client.post("/api/projects", json={"name": "중간고사", "project_type": "exam"})
    assert created.status_code == 200
    project_id = created.get_json()["id"]

    uploaded = client.post(
        f"/api/projects/{project_id}/exam/sources",
        data={"scan_file": (pdf_bytes(6), "class.pdf")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200

    students = [{"number": 1, "name": "가"}, {"number": 2, "name": "나"}, {"number": 3, "name": "다"}]
    assert client.put(f"/api/projects/{project_id}/exam/students", json={"students": students}).status_code == 200
    detail = client.get(f"/api/projects/{project_id}").get_json()
    assert [
        {"number": student["number"], "name": student["name"]}
        for student in detail["submissions"]["students"]
    ] == students
    preview = client.post(f"/api/projects/{project_id}/exam/split/preview", json={"pages_per_student": 2})
    assert preview.status_code == 200
    assert len(preview.get_json()["entries"]) == 3
    completed = client.post(f"/api/projects/{project_id}/exam/split", json={"pages_per_student": 2})
    assert completed.status_code == 200
    assert completed.get_json()["output_dir"].endswith("student_answers")
    submission_status = client.get(f"/api/projects/{project_id}/submissions").get_json()
    assert submission_status["split"]["exists"] is True
    assert submission_status["split"]["file_count"] == 3

    config = project_model.load_project(project_id)
    config.exam.questions = app_module._parse_exam_questions([{
        "id": "q1", "number": "1", "question_text": "설명", "max_score": 5,
        "model_answer": "답", "scoring_elements": [{"description": "핵심", "points": 5}],
    }])
    project_model.save_project(config)
    grading.save_result(project_id, 1, {
        "team_number": 1, "team_name": "가", "q1": 4, "total_score": 4,
        "teacher_status": "pending", "audit_log": [],
    }, 1)
    approved = client.post(f"/api/projects/{project_id}/result/1/approve?round=1", json={"teacher_note": "확인"})
    assert approved.status_code == 200
    assert approved.get_json()["data"]["teacher_status"] == "approved"

    root = client.get("/")
    assert root.status_code == 200
    root_html = root.get_data(as_text=True)
    assert "서술형 시험" in root_html
    assert "교사 추가 채점 지침" in root_html
    exam_section = root_html.index('id="tab-exam"')
    materials_section = root_html.index('id="tab-materials"')
    split_card = root_html.index('id="examIntegratedMaterialsCard"')
    assert exam_section < materials_section < split_card
    assert "examStudents" not in root_html[exam_section:materials_section]


def test_workflow_type_can_be_changed_and_provider_has_own_models(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()

    root = client.get("/")
    project_type_tag = re.search(r'<select[^>]*id="cfgProjectType"[^>]*>', root.get_data(as_text=True))
    assert project_type_tag
    assert "disabled" not in project_type_tag.group(0)

    api_models = client.get("/api/models?provider=gemini_api").get_json()
    assert list(api_models)[0] == "gemini-3.5-flash"
    assert api_models["gemini-3.5-flash"]["name"] == "Gemini 3.5 Flash"

    openai_models = client.get("/api/models?provider=openai_api").get_json()
    assert list(openai_models)[0] == "gpt-5.6-luna"
    assert "권장" in openai_models["gpt-5.6-luna"]["name"]

    created = client.post(
        "/api/projects",
        json={"name": "유형 전환", "workflow_type": "report"},
    )
    project_id = created.get_json()["id"]
    changed = client.put(
        f"/api/projects/{project_id}",
        json={
            "workflow_type": "exam",
            "ai_provider": "openai_api",
            "ai_model": "gpt-5.6-luna",
        },
    )
    assert changed.status_code == 200
    saved = changed.get_json()
    assert saved["workflow_type"] == "exam"
    assert saved["project_type"] == "exam"
    assert saved["ai_provider"] == "openai_api"
    assert saved["ai_model"] == "gpt-5.6-luna"


def test_generate_rubric_rejects_empty_or_directory_question_path(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    client = app_module.app.test_client()
    created = client.post("/api/projects", json={"name": "빈 문제지", "project_type": "exam"})
    project_id = created.get_json()["id"]

    empty_response = client.post(f"/api/projects/{project_id}/exam/generate-rubric")
    assert empty_response.status_code == 400
    assert "문제지 또는 분할된 학생 답지" in empty_response.get_json()["error"]

    client.put(
        f"/api/projects/{project_id}",
        json={"exam": {"question_source_path": str(tmp_path)}},
    )
    directory_response = client.post(f"/api/projects/{project_id}/exam/generate-rubric")
    assert directory_response.status_code == 400
    assert "문제지 또는 분할된 학생 답지" in directory_response.get_json()["error"]


def test_official_exam_rubric_is_extracted_and_saved_immediately(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    captured = {}

    class FakeProvider:
        def generate_json(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["files"] = kwargs["files"]
            return {"questions": [{
                "number": "1", "question_text": "", "max_score": 5,
                "model_answer": "공식 답안",
                "scoring_elements": [{"description": "핵심 개념", "points": 5, "required": True}],
                "accepted_answers": ["동치 답안"], "common_errors": ["부호 오류"],
            }]}

    monkeypatch.setattr(app_module, "get_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {})
    client = app_module.app.test_client()
    created = client.post("/api/projects", json={"name": "공식 기준", "project_type": "exam"})
    project_id = created.get_json()["id"]
    client.put(f"/api/projects/{project_id}", json={
        "exam": {
            "additional_instructions": "단위 누락 1점 감점",
            "questions": [{
                "number": "1", "question_text": "기존 문제 원문", "max_score": 5,
                "model_answer": "", "scoring_elements": [],
            }],
        },
    })

    response = client.post(
        f"/api/projects/{project_id}/exam/rubric/extract",
        data={"file": (pdf_bytes(1), "official.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["questions"][0]["question_text"] == "기존 문제 원문"
    assert data["questions"][0]["model_answer"] == "공식 답안"
    rubric_path = project_model.resolve_project_path(
        project_id, data["rubric_source_path"], expected_subdir="exam_sources"
    )
    assert rubric_path.is_file()
    assert captured["files"] == [str(rubric_path)]
    saved = project_model.load_project(project_id)
    assert saved.exam.questions[0].scoring_elements[0].description == "핵심 개념"
    assert "단위 누락 1점 감점" in saved.prompt_template


def test_combined_answer_scan_repairs_missing_question_numbers(tmp_path, monkeypatch):
    configure_temp_projects(tmp_path, monkeypatch)
    calls = []

    def question(number):
        return {
            "number": str(number),
            "question_text": f"{number}번 문제",
            "max_score": 5,
            "model_answer": f"{number}번 답",
            "scoring_elements": [{
                "description": "핵심 개념", "points": 5, "required": True,
            }],
            "accepted_answers": [],
            "common_errors": [],
        }

    class FakeProvider:
        def generate_json(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            if len(calls) == 1:
                return {
                    "document_kind": "combined_answers",
                    "detected_main_question_numbers": ["1", "3", "4"],
                    "coverage_notes": "여러 학생 답안이 반복됨",
                    "questions": [question(1), question(3), question(4)],
                }
            return {
                "document_kind": "combined_answers",
                "detected_main_question_numbers": ["1", "2", "3", "4"],
                "coverage_notes": "반복 페이지에서 2번을 추가 확인함",
                "questions": [question(2)],
            }

    monkeypatch.setattr(app_module, "get_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {})
    client = app_module.app.test_client()
    created = client.post("/api/projects", json={"name": "혼합 답안", "project_type": "exam"})
    project_id = created.get_json()["id"]
    uploaded = client.post(
        f"/api/projects/{project_id}/exam/sources",
        data={"question_file": (pdf_bytes(69), "olympiad.pdf")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    assert uploaded.get_json()["question_source_path"].startswith("exam_sources/")

    response = client.post(
        f"/api/projects/{project_id}/exam/generate-rubric",
        json={"source_mode": "combined_answers", "expected_question_count": 4},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert len(calls) == 2
    assert "첫 쪽부터 마지막 쪽까지" in calls[0]["prompt"]
    assert "특히 다음 번호가 빠졌을 가능성이 큽니다: 2" in calls[1]["prompt"]
    assert [question["number"] for question in data["questions"]] == ["1", "2", "3", "4"]
    assert data["detected_main_question_numbers"] == [1, 2, 3, 4]
    assert data["audit_performed"] is True
    assert data["needs_review"] is True
    assert "두 결과를 통합" in data["warnings"][0]
    saved = project_model.load_project(project_id)
    assert saved.exam.source_mode == "combined_answers"
    assert saved.exam.expected_question_count == 4


def test_rubric_generation_prefers_short_split_student_answers(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)
    calls = []

    def question(number):
        return {
            "number": str(number), "question_text": f"{number}번 문제", "max_score": 5,
            "model_answer": f"{number}번 답",
            "scoring_elements": [{"description": "핵심", "points": 5, "required": True}],
            "accepted_answers": [], "common_errors": [],
        }

    class FakeProvider:
        def generate_json(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            numbers = [1, 3] if len(calls) == 1 else [2, 4]
            return {
                "document_kind": "combined_answers",
                "detected_main_question_numbers": [str(number) for number in numbers],
                "coverage_notes": "분할 학생 답지에서 확인",
                "questions": [question(number) for number in numbers],
            }

    monkeypatch.setattr(app_module, "get_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {})
    client = app_module.app.test_client()
    created = client.post("/api/projects", json={"name": "분할 답지", "project_type": "exam"})
    project_id = created.get_json()["id"]
    answer_dir = projects / project_id / "materials" / "student_answers"
    answer_dir.mkdir(parents=True)
    for filename, pages in (("001. 가.pdf", 2), ("002. 나.pdf", 6), ("003. 다.pdf", 7)):
        with open(answer_dir / filename, "wb") as stream:
            stream.write(pdf_bytes(pages).getvalue())

    response = client.post(
        f"/api/projects/{project_id}/exam/generate-rubric",
        json={
            "source_mode": "combined_answers",
            "expected_question_count": 4,
            "prefer_split_answers": True,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["used_split_answers"] is True
    assert data["source_files_checked"] == ["003. 다.pdf", "002. 나.pdf"]
    assert [question["number"] for question in data["questions"]] == ["1", "2", "3", "4"]
    assert Path(calls[0]["files"][0]).name == "003. 다.pdf"
    assert Path(calls[1]["files"][0]).name == "002. 나.pdf"
    assert "학생 한 명의 답안지" in calls[0]["prompt"]


def test_new_round_defaults_to_round_one_then_advances_when_results_exist(tmp_path, monkeypatch):
    projects = configure_temp_projects(tmp_path, monkeypatch)

    class DummyThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(app_module.threading, "Thread", DummyThread)
    monkeypatch.setattr(app_module, "load_api_keys", lambda: {"openai": "test-key"})
    client = app_module.app.test_client()
    created = client.post("/api/projects", json={"name": "회차 테스트", "project_type": "exam"})
    project_id = created.get_json()["id"]
    client.put(f"/api/projects/{project_id}", json={"exam": {"questions": [{
        "number": "1", "question_text": "문제", "max_score": 5,
        "model_answer": "답", "scoring_elements": [{"description": "핵심", "points": 5}],
    }]}})
    materials_dir = projects / project_id / "materials"
    materials_dir.mkdir(exist_ok=True)
    (materials_dir / "1. 학생.pdf").write_bytes(b"%PDF-test")

    app_module.grading_state["running"] = False
    first = client.post(f"/api/projects/{project_id}/start", json={"new_round": True})
    assert first.status_code == 200
    assert first.get_json()["round"] == 1
    assert first.get_json()["plan"]["execution_context"]["model"] == "gpt-5.6-luna"

    app_module.grading_state["running"] = False
    grading.save_result(project_id, 1, {"team_number": 1, "total_score": 5}, 1)
    second = client.post(f"/api/projects/{project_id}/start", json={"new_round": True})
    assert second.status_code == 200
    assert second.get_json()["round"] == 2
    app_module.grading_state["running"] = False
