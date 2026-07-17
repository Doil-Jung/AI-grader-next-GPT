"""배포 전 환경과 현재 프로젝트의 복구 가능한 문제를 진단한다."""

from __future__ import annotations

import importlib
import os
import platform
import sys
import tempfile

from config import PROJECTS_DIR
from models.project import ProjectConfig
from services.competition import competition_state_view
from services.file_manager import find_materials
from services.grading import list_round_summaries
from services.review import build_review_dashboard


APP_VERSION = "3.0.0-gpt-preview"


def _dependency_status() -> list[dict]:
    dependencies = [
        ("Flask", "flask", True),
        ("Excel", "openpyxl", True),
        ("PDF", "pypdf", True),
        ("데이터 모델", "pydantic", True),
        ("Gemini API", "google.genai", False),
        ("OpenAI API", "openai", False),
    ]
    results = []
    for label, module_name, required in dependencies:
        try:
            importlib.import_module(module_name)
            available = True
        except Exception:
            available = False
        results.append({
            "label": label,
            "module": module_name,
            "required": required,
            "available": available,
        })
    return results


def _projects_writable() -> bool:
    try:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=PROJECTS_DIR,
            prefix=".diagnostic_",
            delete=True,
        ):
            pass
        return True
    except OSError:
        return False


def build_diagnostics(
    *,
    config: ProjectConfig | None = None,
    api_keys: dict | None = None,
) -> dict:
    dependencies = _dependency_status()
    writable = _projects_writable()
    issues = []
    if not writable:
        issues.append({
            "severity": "error",
            "code": "projects_not_writable",
            "message": "프로젝트 저장 폴더에 쓸 수 없습니다.",
            "action": "원드라이브 동기화 상태와 폴더 권한을 확인하세요.",
        })
    for dependency in dependencies:
        if dependency["required"] and not dependency["available"]:
            issues.append({
                "severity": "error",
                "code": f"missing_{dependency['module']}",
                "message": f"{dependency['label']} 구성요소가 없습니다.",
                "action": "requirements.txt의 패키지를 다시 설치하세요.",
            })

    project = None
    if config is not None:
        materials = find_materials(config)
        participant_numbers = [
            int(item["number"]) for item in materials
        ]
        rounds = list_round_summaries(
            config, participant_count=len(participant_numbers)
        )
        dashboard = build_review_dashboard(
            config,
            participant_numbers=participant_numbers,
        )
        criteria_count = (
            len(config.exam.scored_questions())
            if config.project_type == "exam"
            else len(config.all_criteria)
        )
        full_rounds = [
            item for item in rounds
            if participant_numbers
            and item["completed_count"] >= len(participant_numbers)
            and item["failure_count"] == 0
        ]
        if criteria_count == 0:
            issues.append({
                "severity": "warning",
                "code": "criteria_missing",
                "message": "평가기준 또는 서술형 문항이 없습니다.",
                "action": "2단계 평가기준에서 기준을 준비하고 교사 승인하세요.",
            })
        if not participant_numbers:
            issues.append({
                "severity": "warning",
                "code": "submissions_missing",
                "message": "연결된 학생 답안이 없습니다.",
                "action": "3단계 학생·답안에서 명렬과 파일 연결을 확인하세요.",
            })
        if len(full_rounds) < 2:
            issues.append({
                "severity": "info",
                "code": "rounds_insufficient",
                "message": f"전체 대상 독립 채점이 {len(full_rounds)}/2회 완료되었습니다.",
                "action": "신뢰도 비교를 위해 독립 채점 2회를 완료하세요.",
            })
        if dashboard["summary"]["pending_count"]:
            issues.append({
                "severity": "info",
                "code": "review_pending",
                "message": (
                    f"교사 최종 확정 대기 "
                    f"{dashboard['summary']['pending_count']}명이 있습니다."
                ),
                "action": "5단계 검토·확정에서 우선 확인 대상을 처리하세요.",
            })
        competition_stale = False
        if config.workflow_type == "competition":
            competition_stale = competition_state_view(config)["current_stale"]
            if competition_stale:
                issues.append({
                    "severity": "warning",
                    "code": "competition_stale",
                    "message": "순위 확정 뒤 원 평가 결과가 변경되었습니다.",
                    "action": "내보내기·분석에서 순위 조정안을 다시 확정하세요.",
                })
        project = {
            "project_id": config.id,
            "workflow_type": config.workflow_type,
            "criteria_count": criteria_count,
            "participant_count": len(participant_numbers),
            "material_file_count": sum(
                len(item.get("files", [])) for item in materials
            ),
            "round_count": len(rounds),
            "full_round_count": len(full_rounds),
            "failure_count": sum(item["failure_count"] for item in rounds),
            "manual_count": dashboard["summary"]["manual_count"],
            "approved_count": dashboard["summary"]["effective_approved_count"],
            "pending_count": dashboard["summary"]["pending_count"],
            "competition_stale": competition_stale,
        }

    keys = api_keys or {}
    return {
        "app_version": APP_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "projects_writable": writable,
        "dependencies": dependencies,
        "api_keys": {
            "google": bool(keys.get("google")),
            "openai": bool(keys.get("openai")),
        },
        "project": project,
        "issues": issues,
        "ready": not any(issue["severity"] == "error" for issue in issues),
    }
