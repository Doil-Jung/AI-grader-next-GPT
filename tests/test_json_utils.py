import pytest

from services.providers.base import ProviderError
from services.providers.json_utils import JSON_END, JSON_START, extract_json_payload


def test_extract_marked_json():
    value = extract_json_payload(f"설명\n{JSON_START}\n{{\"score\": 3}}\n{JSON_END}")
    assert value == {"score": 3}


def test_extract_fenced_and_raw_json():
    assert extract_json_payload('```json\n{"ok": true}\n```') == {"ok": True}
    assert extract_json_payload('앞 설명 {"score": 2} 뒤 설명') == {"score": 2}


def test_rejects_text_without_json():
    with pytest.raises(ProviderError):
        extract_json_payload("JSON이 없는 응답")
