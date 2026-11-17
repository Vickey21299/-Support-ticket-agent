"""Gemini adapter: request shape, parsing, retries, failures (no network)."""
import pytest

from app.clients.gemini import GeminiClient
from app.clients.llm import LLMError, LLMNotConfigured


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.sent = []

    def post(self, url, json=None, timeout=None):
        self.sent.append((url, json))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(text, usage=None):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                      "usageMetadata": usage or {"promptTokenCount": 1200, "candidatesTokenCount": 150,
                                                 "thoughtsTokenCount": 50},
                      "modelVersion": "gemini-x"})


def client(responses, **kw):
    return GeminiClient("key", "models/gemini-x", session=Session(responses), sleep=lambda s: None, **kw)


def test_parses_json_and_usage():
    c = client([ok('```json\n{"action": "reply"}\n```')])
    res = c.complete_json("sys", "user")
    assert res.data == {"action": "reply"}
    assert res.input_tokens == 1200 and res.output_tokens == 200   # thinking tokens counted as output
    url, body = c.session.sent[0]
    assert url.endswith("/models/gemini-x:generateContent")
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0


def test_thinking_budget_is_sent():
    c = client([ok("{}")], thinking_budget=0)
    c.complete_json("s", "u")
    assert c.session.sent[0][1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_ignores_thought_parts():
    body = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True},
                                                  {"text": '{"a": 1}'}]}}]}
    assert client([Resp(200, body)]).complete_json("s", "u").data == {"a": 1}


def test_retries_429_and_503():
    c = client([Resp(429), Resp(503), ok('{"a": 1}')])
    assert c.complete_json("s", "u").data == {"a": 1}


def test_400_is_not_retried():
    c = client([Resp(400, {"error": {"message": "bad model"}})])
    with pytest.raises(LLMError, match="bad model"):
        c.complete_json("s", "u")
    assert len(c.session.sent) == 1


def test_blocked_or_non_json_raise():
    with pytest.raises(LLMError, match="no answer"):
        client([Resp(200, {"promptFeedback": {"blockReason": "SAFETY"}})]).complete_json("s", "u")
    with pytest.raises(LLMError, match="not JSON"):
        client([ok("sorry, I can't")]).complete_json("s", "u")


def test_missing_config():
    with pytest.raises(LLMNotConfigured):
        GeminiClient("", "m")
    with pytest.raises(LLMNotConfigured):
        GeminiClient("k", "")
