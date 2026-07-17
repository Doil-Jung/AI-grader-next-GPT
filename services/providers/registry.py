"""설정값에서 AI 제공자를 지연 생성한다."""
from __future__ import annotations

from models.project import ProjectConfig
from services.providers.base import AIProvider, ProviderError


def get_provider(config: ProjectConfig, api_keys: dict | None = None) -> AIProvider:
    provider_id = {
        "google": "gemini_api",
        "gemini": "gemini_api",
        # 지원 종료된 실행 방식은 기본 API 제공자로 자동 전환한다.
        "gemini_web": "openai_api",
        "gemini_cli": "openai_api",
        "chatgpt": "openai_api",
        "openai": "openai_api",
    }.get(config.ai_provider, config.ai_provider) or "gemini_api"
    if provider_id == "gemini_api":
        from services.providers.gemini_api import GeminiAPIProvider
        return GeminiAPIProvider((api_keys or {}).get("google", ""))
    if provider_id == "openai_api":
        from services.providers.openai_api import OpenAIAPIProvider
        return OpenAIAPIProvider((api_keys or {}).get("openai", ""))
    raise ProviderError(f"아직 지원하지 않는 AI 제공자입니다: {provider_id}")
