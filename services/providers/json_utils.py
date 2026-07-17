"""AI 응답 텍스트에서 JSON을 복구하는 공용 유틸리티."""
from __future__ import annotations

import json
import re

from services.providers.base import ProviderError

JSON_START = "AI_GRADER_JSON_START_7C91"
JSON_END = "AI_GRADER_JSON_END_7C91"


def extract_json_payload(text: str) -> dict:
    """마커, 코드 블록, 원시 JSON 순서로 응답에서 JSON 객체를 복구한다."""
    marker = re.search(
        re.escape(JSON_START) + r"\s*(\{.*?\})\s*" + re.escape(JSON_END),
        text,
        re.DOTALL,
    )
    candidates = [marker.group(1)] if marker else []
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE))
    first_brace = text.find("{")
    if first_brace >= 0:
        candidates.append(text[first_brace:])
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate.strip())
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise ProviderError("AI 응답에서 JSON 결과를 찾지 못했습니다.")
