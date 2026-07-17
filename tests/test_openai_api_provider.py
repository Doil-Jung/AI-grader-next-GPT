import json
from types import SimpleNamespace

import pytest

from services.providers.base import ProviderError, ProviderNeedsUserAction
from services.providers.openai_api import OpenAIAPIProvider, _classify_error, _strictify


class _FakeResponses:
    def __init__(self, page):
        self.page = page

    def create(self, **kwargs):
        self.page.calls.append(kwargs)
        result = self.page.results[min(len(self.page.calls) - 1, len(self.page.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(output_text=result)


class _FakeFiles:
    def __init__(self, page):
        self.page = page

    def create(self, *, file, purpose):
        self.page.uploaded += 1
        return SimpleNamespace(id=f"file_{self.page.uploaded}")

    def delete(self, file_id):
        self.page.deleted.append(file_id)


class _FakeClientState:
    def __init__(self, results):
        self.results = results
        self.calls = []
        self.uploaded = 0
        self.deleted = []


def _provider(results):
    state = _FakeClientState(results)
    client = SimpleNamespace(responses=_FakeResponses(state), files=_FakeFiles(state))
    return OpenAIAPIProvider(api_key="", client=client), state


def test_strictify_adds_required_and_no_additional_props():
    schema = {
        "type": "object",
        "properties": {
            "q1": {"type": "integer"},
            "detail": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    }
    strict = _strictify(schema)
    assert strict["additionalProperties"] is False
    assert set(strict["required"]) == {"q1", "detail"}
    assert strict["properties"]["detail"]["additionalProperties"] is False
    # 원본은 바꾸지 않는다.
    assert "required" not in schema


def test_generate_json_uses_schema_and_parses(tmp_path):
    provider, state = _provider([json.dumps({"q1": 3})])
    answer = tmp_path / "answer.pdf"
    answer.write_bytes(b"%PDF-1.4 test")

    result = provider.generate_json(
        "채점하세요", schema={"type": "object", "properties": {"q1": {"type": "integer"}}},
        files=[str(answer)],
    )

    assert result == {"q1": 3}
    call = state.calls[0]
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    # PDF는 업로드 후 input_file로 첨부되고, 끝나면 삭제된다.
    types = [part["type"] for part in call["input"][0]["content"]]
    assert "input_file" in types and "input_text" in types
    assert state.deleted == ["file_1"]


def test_schema_rejection_falls_back_to_json_mode():
    provider, state = _provider([
        Exception("invalid_request_error: unsupported schema for strict format"),
        json.dumps({"ok": True}),
    ])

    result = provider.generate_json("채점", schema={"type": "object"})

    assert result == {"ok": True}
    assert state.calls[1]["text"]["format"]["type"] == "json_object"


def test_error_classification():
    quota = _classify_error(Exception("You exceeded your current quota: insufficient_quota"))
    assert isinstance(quota, ProviderNeedsUserAction)
    assert "크레딧" in str(quota)

    auth = _classify_error(Exception("Incorrect API key provided (401)"))
    assert isinstance(auth, ProviderNeedsUserAction)

    other = _classify_error(Exception("boom"))
    assert isinstance(other, ProviderError)
    assert not isinstance(other, ProviderNeedsUserAction)


def test_gemini_model_name_is_replaced_with_default():
    provider, state = _provider([json.dumps({"ok": True})])

    provider.generate_json("채점", schema={"type": "object"}, model_name="gemini-3.5-flash")

    assert state.calls[0]["model"] == "gpt-5.6-luna"
