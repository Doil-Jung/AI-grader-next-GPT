"""Google Gemini API 제공자."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from config import PROJECTS_DIR
from models.project import ProjectConfig
from services.providers.base import AIProvider, ProviderError, StepCallback
from services.providers.file_prep import prepare_upload_file

API_REQUEST_TIMEOUT_MS = 120_000
FILE_PROCESSING_TIMEOUT_SECONDS = 120


class GeminiAPIProvider(AIProvider):
    provider_id = "gemini_api"
    display_name = "Gemini API"

    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderError("Google API 키가 설정되지 않았습니다.")
        from google import genai
        from google.genai import types
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=API_REQUEST_TIMEOUT_MS),
        )

    def _upload_parts(self, paths: list[Path], on_step: StepCallback, temp_dir: Path):
        from google.genai import types

        uploaded = []
        parts = []
        for index, path in enumerate(paths):
            on_step(f"{path.name} 업로드 준비 중...")
            prepared = prepare_upload_file(path, temp_dir, index)
            remote_file = self.client.files.upload(file=str(prepared))
            uploaded.append(remote_file)
            processing_deadline = time.monotonic() + FILE_PROCESSING_TIMEOUT_SECONDS
            while remote_file.state.name == "PROCESSING":
                if time.monotonic() >= processing_deadline:
                    raise ProviderError(f"Gemini 파일 처리 시간 초과: {path.name}")
                time.sleep(3)
                remote_file = self.client.files.get(name=remote_file.name)
            if remote_file.state.name == "FAILED":
                raise ProviderError(f"파일 처리 실패: {path.name}")
            parts.append(types.Part.from_uri(file_uri=remote_file.uri, mime_type=remote_file.mime_type))
        return uploaded, parts

    def _cleanup_remote(self, uploaded) -> None:
        for remote_file in uploaded:
            try:
                self.client.files.delete(name=remote_file.name)
            except Exception:
                pass

    def evaluate_submission(
        self,
        config: ProjectConfig,
        participant_num: int,
        files: list[dict],
        prompt: str,
        eval_model,
        on_step: StepCallback,
    ) -> dict:
        from google.genai import types

        uploaded = []
        temp_parent = PROJECTS_DIR / config.id / "temp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="api_", dir=temp_parent) as temp_name:
            temp_dir = Path(temp_name)
            try:
                paths = [Path(item["path"]) for item in files]
                uploaded, parts = self._upload_parts(paths, on_step, temp_dir)
                parts.append(types.Part.from_text(text=prompt))
                on_step("AI 채점 중...")
                response = self.client.models.generate_content(
                    model=config.ai_model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=eval_model,
                        temperature=config.temperature,
                    ),
                )
                result = eval_model.model_validate_json(response.text).model_dump()
                result["team_number"] = participant_num
                return result
            finally:
                self._cleanup_remote(uploaded)

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
        from google.genai import types

        step = on_step or (lambda _message: None)
        uploaded = []
        with tempfile.TemporaryDirectory(prefix="ai_grader_json_") as temp_name:
            temp_dir = Path(temp_name)
            try:
                paths = [Path(path) for path in (files or [])]
                uploaded, parts = self._upload_parts(paths, step, temp_dir)
                parts.append(types.Part.from_text(text=prompt))
                config_args = {
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                }
                if schema:
                    config_args["response_schema"] = schema
                response = self.client.models.generate_content(
                    model=model_name or "gemini-3.5-flash",
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(**config_args),
                )
                return json.loads(response.text)
            finally:
                self._cleanup_remote(uploaded)
