from google import genai

from services.providers.gemini_api import API_REQUEST_TIMEOUT_MS, GeminiAPIProvider


def test_gemini_api_client_has_bounded_request_timeout(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(genai, "Client", fake_client)
    GeminiAPIProvider("test-key")

    assert captured["api_key"] == "test-key"
    assert captured["http_options"].timeout == API_REQUEST_TIMEOUT_MS
