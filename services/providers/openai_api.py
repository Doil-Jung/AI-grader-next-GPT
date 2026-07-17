"""OpenAI API(GPT) 제공자.

Responses API의 PDF 파일 입력과 Structured Outputs(JSON 스키마 강제)를 사용한다.
스키마 강제가 실패하는 모델·스키마 조합에서는 JSON 모드 + 마커 복구로 폴백한다.
"""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

from models.project import ProjectConfig
from services.providers.base import AIProvider, ProviderError, ProviderNeedsUserAction, StepCallback
from services.providers.file_prep import prepare_upload_file
from services.providers.json_utils import extract_json_payload

REQUEST_TIMEOUT_SECONDS = 300
DEFAULT_MODEL = "gpt-5.6-luna"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _strictify(schema: dict) -> dict:
    """Structured Outputs strict 모드 요구사항에 맞게 스키마를 변환한다.

    모든 object에 additionalProperties=false를 넣고 모든 속성을 required로 만든다.
    """
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and isinstance(node.get("properties"), dict):
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    cloned = json.loads(json.dumps(schema or {"type": "object"}))
    walk(cloned)
    return cloned


def _classify_error(exc: Exception) -> ProviderError:
    message = str(exc)
    lower = message.lower()
    if any(k in lower for k in ("invalid_api_key", "incorrect api key", "authentication", "401")):
        return ProviderNeedsUserAction(
            "OpenAI API 키가 올바르지 않습니다. 오른쪽 위 'API 키'에서 platform.openai.com의 키를 확인하세요."
        )
    if "insufficient_quota" in lower or "exceeded your current quota" in lower:
        return ProviderNeedsUserAction(
            "OpenAI API 크레딧이 부족합니다. platform.openai.com의 Billing에서 잔액을 확인하세요."
        )
    if "429" in lower or "rate limit" in lower or "rate_limit" in lower:
        return ProviderError("OpenAI API 요청 한도(429)에 걸렸습니다. 잠시 후 재시도됩니다.")
    if "timeout" in lower or "timed out" in lower:
        return ProviderError("OpenAI API 응답 대기 시간이 초과되었습니다.")
    return ProviderError(f"OpenAI API 오류: {message[:300]}")


class OpenAIAPIProvider(AIProvider):
    provider_id = "openai_api"
    display_name = "OpenAI API (GPT)"

    def __init__(self, api_key: str, client=None):
        if client is not None:
            self.client = client
            return
        if not api_key:
            raise ProviderError("OpenAI API 키가 설정되지 않았습니다.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(
                "openai 패키지가 설치되지 않았습니다. `pip install -r requirements.txt`를 실행하세요."
            ) from exc
        self.client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    # ─── 파일 준비 ──────────────────────────────────────────

    def _build_file_parts(self, paths: list[Path], on_step: StepCallback, temp_dir: Path):
        """PDF는 파일 업로드로, 이미지는 base64로 첨부한다."""
        parts = []
        uploaded_ids = []
        for index, path in enumerate(paths):
            on_step(f"{path.name} 준비 중...")
            prepared = prepare_upload_file(path, temp_dir, index)
            suffix = prepared.suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else f"image/{suffix[1:]}"
                encoded = base64.b64encode(prepared.read_bytes()).decode("ascii")
                parts.append({
                    "type": "input_image",
                    "image_url": f"data:{mime};base64,{encoded}",
                })
            else:
                with open(prepared, "rb") as handle:
                    remote = self.client.files.create(file=handle, purpose="user_data")
                uploaded_ids.append(remote.id)
                parts.append({"type": "input_file", "file_id": remote.id})
        return parts, uploaded_ids

    def _cleanup_remote(self, uploaded_ids: list[str]) -> None:
        for file_id in uploaded_ids:
            try:
                self.client.files.delete(file_id)
            except Exception:
                pass

    # ─── 요청 실행 ──────────────────────────────────────────

    def _create_response(self, *, model: str, content: list, schema: dict | None):
        """스키마 강제를 우선 시도하고, 안 되면 JSON 모드로 폴백한다."""
        if schema:
            try:
                response = self.client.responses.create(
                    model=model,
                    input=[{"role": "user", "content": content}],
                    text={"format": {
                        "type": "json_schema",
                        "name": "grading_result",
                        "schema": _strictify(schema),
                        "strict": True,
                    }},
                )
                return response, True
            except Exception as exc:
                lower = str(exc).lower()
                # 스키마·형식 관련 거절만 폴백하고 나머지는 그대로 알린다.
                if not any(k in lower for k in ("schema", "format", "strict", "invalid_request")):
                    raise
        response = self.client.responses.create(
            model=model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_object"}},
        )
        return response, False

    def _generate(
        self,
        prompt: str,
        files: list[str],
        model_name: str | None = None,
        schema: dict | None = None,
        on_step: StepCallback | None = None,
    ) -> dict:
        step = on_step or (lambda _message: None)
        model = (model_name or "").strip() or DEFAULT_MODEL
        if model.startswith(("gemini", "Gemini")):
            # 프로젝트에 Gemini 모델명이 남아 있으면 OpenAI 기본 모델로 대체.
            model = DEFAULT_MODEL

        json_note = (
            "\n\n반드시 요구한 구조의 단일 JSON 객체만 출력하세요. "
            "설명·인사말·마크다운을 붙이지 마세요."
        )
        if schema:
            json_note += "\nJSON 스키마:\n" + json.dumps(
                schema, ensure_ascii=False, separators=(",", ":")
            )

        uploaded_ids = []
        with tempfile.TemporaryDirectory(prefix="openai_api_") as temp_name:
            temp_dir = Path(temp_name)
            try:
                paths = [Path(value) for value in files]
                for path in paths:
                    if not path.is_file():
                        raise ProviderError(f"OpenAI 업로드 대상 파일을 찾을 수 없습니다: {path.name}")
                parts, uploaded_ids = self._build_file_parts(paths, step, temp_dir)
                parts.append({"type": "input_text", "text": prompt + json_note})
                step("OpenAI 채점 요청 중...")
                try:
                    response, strict_used = self._create_response(
                        model=model, content=parts, schema=schema,
                    )
                except Exception as exc:
                    raise _classify_error(exc) from exc
                text = getattr(response, "output_text", "") or ""
                if not text.strip():
                    raise ProviderError("OpenAI가 빈 응답을 반환했습니다.")
                try:
                    value = json.loads(text)
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    pass
                # 모델이 형식을 벗어난 경우 마커·코드블록 복구를 시도한다.
                return extract_json_payload(text)
            finally:
                self._cleanup_remote(uploaded_ids)

    # ─── 공개 인터페이스 ────────────────────────────────────

    def evaluate_submission(
        self,
        config: ProjectConfig,
        participant_num: int,
        files: list[dict],
        prompt: str,
        eval_model,
        on_step: StepCallback,
    ) -> dict:
        payload = self._generate(
            prompt,
            [str(Path(item["path"]).resolve()) for item in files],
            config.ai_model,
            schema=eval_model.model_json_schema(),
            on_step=on_step,
        )
        result = eval_model.model_validate(payload).model_dump()
        result["team_number"] = participant_num
        return result

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
        return self._generate(
            prompt,
            files or [],
            model_name,
            schema=schema,
            on_step=on_step,
        )
