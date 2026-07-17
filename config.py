"""
범용 AI 채점 시스템 - 설정
"""
import sys
from pathlib import Path

# 데이터 경로는 exe 위치 기준 (projects, api_keys 등)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

PROJECTS_DIR = BASE_DIR / "projects"
API_KEY_FILE = BASE_DIR / ".api_keys.json"

# 기본 포트
DEFAULT_PORT = 5000

# Gemini API 모델. 첫 항목이 새 프로젝트의 권장 기본 모델이다.
AI_MODELS = {
    "gemini-3.5-flash": {
        "name": "Gemini 3.5 Flash",
        "description": "Gemini API 채점 기본 (1티어 1,000회/일)",
    },
}

# OpenAI API에서 선택할 수 있는 모델. 첫 항목이 권장 기본값.
OPENAI_AI_MODELS = {
    "gpt-5.6-luna": {
        "name": "GPT-5.6 luna - 권장",
        "description": "정확한 채점·저비용 (학생당 약 20원)",
    },
    "gpt-5.6-terra": {
        "name": "GPT-5.6 terra",
        "description": "상위 품질 (학생당 약 50원)",
    },
}

# 지원 파일 타입
SUPPORTED_FILE_TYPES = {
    "documents": [".pdf", ".hwp", ".hwpx", ".docx", ".doc", ".txt"],
    "videos": [".mp4", ".avi", ".mov", ".mkv", ".webm"],
    "images": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
    "spreadsheets": [".xlsx", ".xls", ".csv"],
}

# 기본 채점 척도 프리셋
SCALE_PRESETS = {
    "5단계_15점": {
        "name": "5단계 (15점 만점)",
        "scale": [15, 13, 11, 9, 7],
        "labels": ["매우우수", "우수", "보통", "미흡", "매우미흡"],
    },
    "5단계_10점": {
        "name": "5단계 (10점 만점)",
        "scale": [10, 9, 8, 7, 6],
        "labels": ["매우우수", "우수", "보통", "미흡", "매우미흡"],
    },
    "5단계_20점": {
        "name": "5단계 (20점 만점)",
        "scale": [20, 17, 14, 11, 8],
        "labels": ["매우우수", "우수", "보통", "미흡", "매우미흡"],
    },
    "5단계_5점": {
        "name": "5단계 (5점 만점)",
        "scale": [5, 4, 3, 2, 1],
        "labels": ["매우우수", "우수", "보통", "미흡", "매우미흡"],
    },
}
