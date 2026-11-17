"""Ollama adapter: native /api/chat request shape, parsing, think fallback, context guard (no network)."""
import pytest
import requests

from app.clients.llm import LLMError
from app.clients.ollama_client import OllamaClient


class Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text or str(self._body)

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def post(self, url, json=None, timeout=None):
        self.sent.append((url, json))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(content='{"action": "reply"}', prompt=2500, out=120):
    return Resp(200, {"model": "qwen-test", "message": {"content": content},
                      "prompt_eval_count": prompt, "eval_count": out})


def client(responses, num_ctx=8192):
    return OllamaClient("qwen-test", num_ctx=num_ctx, session=Session(responses), sleep=lambda s: None)


def test_request_shape_and_parse():
    c = client([ok()])
    res = c.complete_json("sys", "user")
    assert res.data == {"action": "reply"} and res.input_tokens == 2500 and res.output_tokens == 120
    url, body = c.session.sent[0]
    assert url.endswith("/api/chat")
    assert body["format"] == "json" and body["stream"] is False and body["think"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 4096}   # output cap


def test_model_without_think_switch_retries_without_it():
    c = client([Resp(400, text='{"error":"model does not support thinking"}'), ok()])
    assert c.complete_json("s", "u").data == {"action": "reply"}
    assert "think" not in c.session.sent[1][1]


def test_prompt_that_fills_the_context_is_rejected():
    with pytest.raises(LLMError, match="num_ctx"):
        client([ok(prompt=4096)], num_ctx=4096).complete_json("s", "u")


def test_not_running_gives_clear_error():
    with pytest.raises(LLMError, match="not reachable"):
        client([requests.ConnectionError("refused")]).complete_json("s", "u")


def test_non_json_raises():
    with pytest.raises(LLMError, match="not JSON"):
        client([ok(content="Sure! Here you go")]).complete_json("s", "u")
