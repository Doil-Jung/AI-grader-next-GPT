"""
프로젝트 설정 모델
- 프로젝트 생성/로드/저장
- 채점 기준(rubric) 관리
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
from config import PROJECTS_DIR


CURRENT_SCHEMA_VERSION = 3


def _project_dir(project_id: str) -> Path:
    return (PROJECTS_DIR / project_id).resolve()


def _tail_after_project_id(project_id: str, path: Path) -> Path | None:
    """다른 PC의 절대경로에서 프로젝트 ID 뒤쪽의 프로젝트 내부 경로를 복구한다."""
    if not project_id:
        return None
    parts = list(path.parts)
    for index, part in enumerate(parts):
        if part.casefold() == project_id.casefold() and index + 1 < len(parts):
            return Path(*parts[index + 1:])
    return None


def portable_project_path(project_id: str, value: str | Path | None) -> str:
    """프로젝트 내부 파일은 PC 계정명과 무관한 상대경로로 직렬화한다."""
    if value is None or not str(value).strip():
        return ""
    path = Path(value)
    if not project_id:
        return str(path)
    if not path.is_absolute():
        return path.as_posix()

    project_dir = _project_dir(project_id)
    try:
        return path.resolve(strict=False).relative_to(project_dir).as_posix()
    except (OSError, ValueError):
        tail = _tail_after_project_id(project_id, path)
        return tail.as_posix() if tail is not None else str(path)


def resolve_project_path(
    project_id: str,
    value: str | Path | None,
    *,
    expected_subdir: str | None = None,
) -> Path:
    """상대경로와 다른 PC에서 저장한 절대경로를 현재 프로젝트 위치로 해석한다."""
    if value is None or not str(value).strip():
        return Path()

    path = Path(value)
    project_dir = _project_dir(project_id)
    if path.is_absolute() and path.exists():
        return path

    relative = path if not path.is_absolute() else _tail_after_project_id(project_id, path)
    if relative is not None:
        candidate = (project_dir / relative).resolve(strict=False)
        try:
            candidate.relative_to(project_dir)
            if candidate.exists() or not path.is_absolute():
                return candidate
        except ValueError:
            pass

    if expected_subdir:
        fallback = (project_dir / expected_subdir / path.name).resolve(strict=False)
        try:
            fallback.relative_to(project_dir)
            return fallback
        except ValueError:
            pass
    return path


@dataclass
class Criterion:
    """개별 채점 항목"""
    id: str
    name: str
    description: str
    scale: list[int]  # e.g. [15, 13, 11, 9, 7]
    scale_labels: list[str]  # e.g. ["매우우수", "우수", ...]
    
    @property
    def max_score(self) -> int:
        return max(self.scale)
    
    @property
    def min_score(self) -> int:
        return min(self.scale)


@dataclass
class Category:
    """채점 영역 (적절성, 창의성 등)"""
    name: str
    criteria: list[Criterion]
    
    @property
    def max_score(self) -> int:
        return sum(c.max_score for c in self.criteria)


@dataclass
class MaterialsConfig:
    """심사자료 설정"""
    source_type: str = "folder"  # "folder" | "upload"
    folder_path: str = ""
    file_types: list[str] = field(default_factory=lambda: ["pdf", "mp4"])
    naming_pattern: str = r"(\d+)\.\s*(.+)"  # 기본: "번호. 이름" 형식
    excluded_files: list[str] = field(default_factory=list)  # 제외된 파일 경로 목록


@dataclass
class ScoringElement:
    """서술형 문항의 부분점 요소."""
    description: str
    points: int
    required: bool = True


@dataclass
class ExamQuestion:
    """정기고사 서술형 문항과 채점 기준."""
    id: str
    number: str
    question_text: str
    max_score: int
    model_answer: str = ""
    scoring_elements: list[ScoringElement] = field(default_factory=list)
    accepted_answers: list[str] = field(default_factory=list)
    common_errors: list[str] = field(default_factory=list)
    # AI 채점용 핵심 확인 요소 (교사용 상세 기준과 분리된 압축 층)
    core_criteria: list[str] = field(default_factory=list)


@dataclass
class StudentRecord:
    """통합 스캔 분할에 사용하는 학생 명렬."""
    number: int
    name: str = ""


@dataclass
class ScanSplitConfig:
    """한 반 통합 PDF의 학생별 분할 설정."""
    source_path: str = ""
    start_page: int = 1
    pages_per_student: int = 0
    boundaries: list[int] = field(default_factory=list)
    completed_at: str = ""


@dataclass
class ExamConfig:
    """정기고사 프로젝트 전용 설정."""
    question_source_path: str = ""
    rubric_source_path: str = ""
    source_mode: str = "auto"  # auto | question_only | combined_answers | answers_only
    expected_question_count: int = 0  # 0이면 AI가 자동 판별
    additional_instructions: str = ""
    # AI에게 전달할 기준의 양: autonomous(정답·배점만) | core(핵심 요소만) | strict(상세 전체)
    grading_mode: str = "autonomous"
    questions: list[ExamQuestion] = field(default_factory=list)
    students: list[StudentRecord] = field(default_factory=list)
    scan_split: ScanSplitConfig = field(default_factory=ScanSplitConfig)


@dataclass
class ProjectConfig:
    """프로젝트 전체 설정"""
    id: str = ""
    name: str = ""
    description: str = ""
    created_at: str = ""
    updated_at: str = ""

    # 스키마/프로젝트 유형. 기존 설정 파일은 report로 자동 마이그레이션한다.
    schema_version: int = CURRENT_SCHEMA_VERSION
    project_type: str = "report"  # "report" | "exam"
    
    # AI 설정
    ai_model: str = "gpt-5.6-luna"
    ai_provider: str = "openai_api"  # openai_api | gemini_api
    temperature: float = 0.2
    
    # 심사자료
    materials: MaterialsConfig = field(default_factory=MaterialsConfig)
    
    # 채점 기준
    categories: list[Category] = field(default_factory=list)

    # 정기고사 설정
    exam: ExamConfig = field(default_factory=ExamConfig)
    
    # 평가 프롬프트 (사용자 커스텀)
    prompt_template: str = ""
    
    # 제출용 설정
    total_max_score: int = 100
    
    @property
    def all_criteria(self) -> list[Criterion]:
        result = []
        for cat in self.categories:
            result.extend(cat.criteria)
        return result

    @property
    def all_exam_questions(self) -> list[ExamQuestion]:
        return list(self.exam.questions)
    
    def to_dict(self) -> dict:
        exam_data = asdict(self.exam)
        exam_data["question_source_path"] = portable_project_path(
            self.id, self.exam.question_source_path
        )
        exam_data["rubric_source_path"] = portable_project_path(
            self.id, self.exam.rubric_source_path
        )
        exam_data["scan_split"]["source_path"] = portable_project_path(
            self.id, self.exam.scan_split.source_path
        )
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "project_type": self.project_type,
            "ai_model": self.ai_model,
            "ai_provider": self.ai_provider,
            "temperature": self.temperature,
            "materials": asdict(self.materials),
            "categories": [
                {
                    "name": cat.name,
                    "criteria": [asdict(c) for c in cat.criteria],
                }
                for cat in self.categories
            ],
            "exam": exam_data,
            "prompt_template": self.prompt_template,
            "total_max_score": self.total_max_score,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        materials_data = data.get("materials", {}) or {}
        materials = MaterialsConfig(
            source_type=materials_data.get("source_type", "folder"),
            folder_path=materials_data.get("folder_path", ""),
            file_types=materials_data.get("file_types", ["pdf", "mp4"]),
            naming_pattern=materials_data.get("naming_pattern", r"(\d+)\.\s*(.+)"),
            excluded_files=materials_data.get("excluded_files", []),
        )
        categories = []
        used_ids = set()
        for cat_idx, cat_data in enumerate(data.get("categories", [])):
            criteria = []
            for c_data in cat_data.get("criteria", []):
                c = Criterion(**c_data)
                # 중복 ID 자동 보정: cat인덱스_원래ID
                if c.id in used_ids:
                    c.id = f"cat{cat_idx + 1}_{c.id}"
                used_ids.add(c.id)
                criteria.append(c)
            # 중복 영역 이름 자동 보정
            cat_name = cat_data["name"]
            existing_names = [cat.name for cat in categories]
            if cat_name in existing_names:
                cat_name = f"{cat_name} {cat_idx + 1}"
            categories.append(Category(name=cat_name, criteria=criteria))

        exam_data = data.get("exam", {}) or {}
        exam_questions = []
        for q_idx, q_data in enumerate(exam_data.get("questions", []), 1):
            elements = [
                ScoringElement(
                    description=e.get("description", ""),
                    points=max(0, int(e.get("points", 0))),
                    required=bool(e.get("required", True)),
                )
                for e in q_data.get("scoring_elements", [])
            ]
            exam_questions.append(ExamQuestion(
                id=q_data.get("id", f"q{q_idx}"),
                number=str(q_data.get("number", q_idx)),
                question_text=q_data.get("question_text", ""),
                max_score=max(1, int(q_data.get("max_score", 1))),
                model_answer=q_data.get("model_answer", ""),
                scoring_elements=elements,
                accepted_answers=list(q_data.get("accepted_answers", [])),
                common_errors=list(q_data.get("common_errors", [])),
                core_criteria=[str(v).strip() for v in q_data.get("core_criteria", []) if str(v).strip()],
            ))

        students = [
            StudentRecord(number=int(s.get("number", i)), name=s.get("name", ""))
            for i, s in enumerate(exam_data.get("students", []), 1)
        ]
        split_data = exam_data.get("scan_split", {}) or {}
        scan_split = ScanSplitConfig(
            source_path=split_data.get("source_path", ""),
            start_page=max(1, int(split_data.get("start_page", 1))),
            pages_per_student=max(0, int(split_data.get("pages_per_student", 0))),
            boundaries=[int(v) for v in split_data.get("boundaries", [])],
            completed_at=split_data.get("completed_at", ""),
        )
        exam = ExamConfig(
            question_source_path=exam_data.get("question_source_path", ""),
            rubric_source_path=exam_data.get("rubric_source_path", ""),
            source_mode=(
                exam_data.get("source_mode", "auto")
                if exam_data.get("source_mode", "auto") in {
                    "auto", "question_only", "combined_answers", "answers_only"
                }
                else "auto"
            ),
            expected_question_count=max(0, int(exam_data.get("expected_question_count", 0) or 0)),
            additional_instructions=exam_data.get("additional_instructions", ""),
            # 필드가 없는 기존 프로젝트는 현행 동작(상세 전체 전달)을 유지한다.
            grading_mode=(
                exam_data.get("grading_mode", "strict")
                if exam_data.get("grading_mode", "strict") in {"autonomous", "core", "strict"}
                else "strict"
            ),
            questions=exam_questions,
            students=students,
            scan_split=scan_split,
        )
        
        provider_aliases = {
            "google": "gemini_api",
            "gemini": "gemini_api",
            # 지원 종료된 실행 방식(웹 자동화·CLI)은 OpenAI API로 전환한다.
            "gemini_web": "openai_api",
            "gemini_cli": "openai_api",
            "chatgpt": "openai_api",
            "openai": "openai_api",
        }
        stored_provider = data.get("ai_provider", "gemini_api")
        normalized_provider = provider_aliases.get(stored_provider, stored_provider)
        stored_model = data.get("ai_model", "gemini-3.5-flash")
        api_model_aliases = {
            "gemini-3-flash": "gemini-3.5-flash",
            "gemini-3-flash-preview": "gemini-3.5-flash",
            "gemini-3.1-pro-preview": "gemini-3.5-flash",
            "gemini-3.1-flash-lite": "gemini-3.5-flash",
            "gemini-2.5-flash": "gemini-3.5-flash",
            "gemini-2.5-pro": "gemini-3.5-flash",
        }
        normalized_model = api_model_aliases.get(stored_model, stored_model)
        if normalized_provider == "openai_api" and not normalized_model.startswith("gpt-"):
            # 웹/CLI에서 넘어온 프로젝트의 Gemini 계열 모델명은 기본 GPT 모델로 바꾼다.
            normalized_model = "gpt-5.6-luna"

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            schema_version=max(CURRENT_SCHEMA_VERSION, int(data.get("schema_version", 1))),
            project_type=data.get("project_type", "report"),
            ai_model=normalized_model,
            ai_provider=normalized_provider,
            temperature=data.get("temperature", 0.2),
            materials=materials,
            categories=categories,
            exam=exam,
            prompt_template=data.get("prompt_template", ""),
            total_max_score=data.get("total_max_score", 100),
        )


def create_project(name: str, description: str = "", project_type: str = "report") -> ProjectConfig:
    """새 프로젝트 생성"""
    project_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    now = datetime.now().isoformat()
    
    config = ProjectConfig(
        id=project_id,
        name=name,
        description=description,
        created_at=now,
        updated_at=now,
        project_type=project_type if project_type in ("report", "exam") else "report",
    )
    
    # 프로젝트 디렉토리 생성
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "results").mkdir(exist_ok=True)
    (project_dir / "materials").mkdir(exist_ok=True)
    
    save_project(config)
    return config


def save_project(config: ProjectConfig):
    """프로젝트 설정 저장"""
    config.updated_at = datetime.now().isoformat()
    project_dir = PROJECTS_DIR / config.id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    config_path = project_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)


def load_project(project_id: str) -> Optional[ProjectConfig]:
    """프로젝트 설정 로드"""
    config_path = PROJECTS_DIR / project_id / "config.json"
    if not config_path.exists():
        return None
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ProjectConfig.from_dict(data)


def list_projects() -> list[dict]:
    """모든 프로젝트 목록"""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for d in PROJECTS_DIR.iterdir():
        if d.is_dir():
            config_path = d / "config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # 결과 카운트
                    results_dir = d / "results"
                    round_count = 0
                    team_count = 0
                    if results_dir.exists():
                        round_dirs = [rd for rd in results_dir.iterdir() if rd.is_dir() and rd.name.startswith("round_")]
                        round_count = len(round_dirs)
                        if round_dirs:
                            team_count = len(list(round_dirs[-1].glob("team_*.json")))
                    
                    projects.append({
                        "id": data["id"],
                        "name": data["name"],
                        "description": data.get("description", ""),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "ai_model": data.get("ai_model", ""),
                        "ai_provider": data.get("ai_provider", "gemini_api"),
                        "project_type": data.get("project_type", "report"),
                        "round_count": round_count,
                        "team_count": team_count,
                        "criteria_count": (
                            len((data.get("exam") or {}).get("questions", []))
                            if data.get("project_type") == "exam"
                            else sum(len(cat.get("criteria", [])) for cat in data.get("categories", []))
                        ),
                    })
                except Exception:
                    pass
    
    projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return projects


def delete_project(project_id: str) -> bool:
    """프로젝트 삭제"""
    import shutil
    import stat
    import os
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        def on_rm_error(func, path, exc_info):
            """OneDrive 잠금 등 권한 에러 시 재시도"""
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass
        shutil.rmtree(project_dir, onerror=on_rm_error)
        return True
    return False


def generate_default_prompt(config: ProjectConfig) -> str:
    """채점 기준에서 자동으로 평가 프롬프트 생성"""
    if config.project_type == "exam":
        return generate_exam_prompt(config)
    lines = [
        f"당신은 '{config.name}' 심사위원입니다.",
        f"{config.description}" if config.description else "",
        "아래의 심사 기준에 따라, 첨부된 자료를 종합적으로 심사해 주세요.",
        "",
        "## 심사 기준",
        "",
    ]
    
    for cat in config.categories:
        lines.append(f"### {cat.name} ({cat.max_score}점)")
        for c in cat.criteria:
            scale_header = " | ".join(c.scale_labels) if c.scale_labels else ""
            scale_values = " | ".join(str(s) for s in c.scale)
            lines.append(f"- **{c.name}**: {c.description}")
            lines.append(f"  - 척도: {scale_header}")
            lines.append(f"  - 배점: {scale_values}")
        lines.append("")
    
    lines.extend([
        "## 심사 지침",
        "1. 각 항목의 점수는 반드시 제시된 척도 중 하나만 선택하세요.",
        "2. 변별력 확보를 위해 엄격하게 채점하세요. 최고점은 상위 10%에만 부여합니다.",
        "3. 첨부된 모든 자료를 종합적으로 참고하여 판단하세요.",
        "4. 각 항목마다 구체적인 채점 근거를 한국어로 2~3문장 작성하세요.",
        "5. 종합 평가 의견에서 강점과 개선점을 균형 있게 기술하세요.",
        "",
        "## 세부능력 및 특기사항 (세특) 작성",
        "채점 결과를 바탕으로, 해당 참가자에 대한 학교생활기록부 '세부능력 및 특기사항' 문구를 작성하세요.",
        "- 3~5문장으로, 해당 학생의 강점·성장 가능성·탐구 태도를 구체적으로 기술하세요.",
        "- 3인칭 서술체('~함', '~을 보임')로 작성하세요.",
        "- 평가 항목에서 높은 점수를 받은 영역을 중심으로 작성하되, 부족한 부분은 성장 가능성으로 표현하세요.",
        "- 결과물의 JSON에 'seteuk' 필드로 포함하세요.",
        "",
        "참가자의 번호와 이름을 파일명에서 추출하여 기입하세요.",
    ])
    
    return "\n".join(lines)


def generate_exam_prompt(config: ProjectConfig) -> str:
    """서술형 채점 프롬프트 생성. grading_mode로 AI에게 전달할 기준의 양을 조절한다.

    - autonomous(자율 선채점): 문제·배점·모범답안만 전달, 부분점수는 AI가 자율 부여
    - core(핵심 기준 채점): 문항별 핵심 확인 요소(core_criteria)만 전달
    - strict(공식 기준 엄격 적용): 저장된 상세 기준 전체를 전달
    상세 기준(부분점·인정답안·감점례)은 어느 모드에서든 교사 검토용으로 저장은 유지된다.
    """
    mode = getattr(config.exam, "grading_mode", "strict") or "strict"
    if mode not in ("autonomous", "core", "strict"):
        mode = "strict"

    lines = [
        f"당신은 '{config.name}' 서술형 답안을 채점하는 교사 보조자입니다.",
        config.description if config.description else "",
        "첨부된 파일은 학생 한 명의 전체 답안입니다.",
        "아래 문항별 기준을 독립적으로 적용하고, 답안에 실제로 적힌 내용만 근거로 채점하세요.",
        "",
        "## 무응답 판정 규칙 (가장 중요)",
        "1. 각 문항을 채점하기 전에, 답안지에서 그 문항에 대한 답이 실제로 존재하는지 먼저 확인하세요.",
        "2. 각 문항의 has_answer 필드에 그 판정을 true/false로 기록하세요. "
        "답란이 비어 있거나 그 문항에 해당하는 답을 찾을 수 없으면 has_answer는 false이고 반드시 0점이며, "
        "답안 요약(answer_summary)에는 '무응답'이라고만 쓰고 review_required를 true로 표시하세요.",
        "3. 채점 근거(reason)에는 답안지에서 실제로 읽은 학생의 표현을 짧게 직접 인용하세요. "
        "인용할 문구가 답안지에 없다면 그 문항은 무응답입니다.",
        "4. 답하지 않은 문항에 내용이 있는 것처럼 부분점수를 만들어 주는 것은 가장 심각한 채점 오류입니다. "
        "확실히 보이는 답만 채점하세요.",
        "5. 부분점수는 그 문항의 답으로 명확히 식별되는 서술과 식에만 부여하세요. "
        "문제지에 인쇄된 내용, 다른 문항의 답, 단순 낙서·밑줄·계산 흔적은 점수의 근거가 될 수 없습니다. "
        "'시도한 흔적이 있으므로 기본 점수'와 같은 채점은 허용되지 않습니다.",
        "",
        "답안을 읽을 수 없거나 문항 대응이 불명확하면 추측하지 말고 review_required를 true로 표시하세요.",
        "어떤 경우에도 문항 배점을 넘는 점수를 주지 마세요.",
        "",
        "## 문항별 채점 기준",
    ]

    for q in config.exam.questions:
        lines.extend([
            "",
            f"### {q.number}번 ({q.max_score}점)",
        ])
        if q.question_text.strip():
            lines.append(f"문제: {q.question_text}")
        lines.append(f"모범 답안: {q.model_answer or '교사가 아직 입력하지 않음'}")

        if mode == "strict":
            lines.append("부분점 요소:")
            if q.scoring_elements:
                for element in q.scoring_elements:
                    required = "필수" if element.required else "선택"
                    lines.append(f"- {element.description}: {element.points}점 ({required})")
            else:
                lines.append(f"- 정답의 핵심 개념과 논리 전개를 종합 평가: {q.max_score}점")
                lines.append(
                    "- 부분점 기준이 따로 없는 문항입니다. 모범답안과 배점을 기준으로 "
                    "부분점수를 스스로 합리적이고 일관되게 부여하고, 채점 근거에 그 기준을 남기세요."
                )
            if q.accepted_answers:
                lines.append("허용 답안: " + "; ".join(q.accepted_answers))
            if q.common_errors:
                lines.append("주요 감점 사례: " + "; ".join(q.common_errors))
        elif mode == "core":
            if q.core_criteria:
                lines.append("핵심 확인 요소:")
                for item in q.core_criteria:
                    lines.append(f"- {item}")
            else:
                lines.append(
                    "- 이 문항은 핵심 요소가 지정되지 않았습니다. 모범답안과 배점을 기준으로 "
                    "부분점수를 스스로 합리적이고 일관되게 부여하세요."
                )
        else:  # autonomous
            lines.append(
                "- 모범답안과 배점을 기준으로 부분점수를 스스로 합리적이고 일관되게 부여하고, "
                "채점 근거에 그 기준을 남기세요."
            )

    if mode == "strict":
        lines.extend([
            "",
            "위 부분점 기준에 명시되지 않은 방식의 답이나 기준을 벗어나는 답은 "
            "점수를 추정하지 말고 review_required를 true로 표시하세요.",
        ])
    elif mode == "core":
        lines.extend([
            "",
            "핵심 확인 요소를 중심으로 채점하되, 요소에 없는 타당한 풀이는 모범답안과 배점을 "
            "기준으로 판단하고, 확신이 낮으면 review_required를 true로 표시하세요.",
        ])

    if config.exam.additional_instructions.strip():
        lines.extend([
            "",
            "## 교사 추가 채점 지침",
            config.exam.additional_instructions.strip(),
            "공식 문항별 채점 기준과 충돌하지 않는 범위에서 위 지침을 적용하세요.",
        ])

    return "\n".join(lines)
