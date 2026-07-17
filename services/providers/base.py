"""Gemini·Claude·ChatGPT를 같은 채점 파이프라인에 연결하기 위한 계약."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from models.project import ProjectConfig


StepCallback = Callable[[str], None]


class ProviderError(RuntimeError):
    pass


class ProviderNeedsUserAction(ProviderError):
    """로그인, 사용량 제한 해제 등 사용자의 조치가 필요함."""


class AIProvider(ABC):
    provider_id = "base"
    display_name = "AI"

    @abstractmethod
    def evaluate_submission(
        self,
        config: ProjectConfig,
        participant_num: int,
        files: list[dict],
        prompt: str,
        eval_model,
        on_step: StepCallback,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        files: list[str] | None = None,
        model_name: str | None = None,
        temperature: float = 0.1,
        on_step: StepCallback | None = None,
    ) -> dict:
        raise NotImplementedError

