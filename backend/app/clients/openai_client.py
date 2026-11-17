"""OpenAI provider (REST via requests, no extra SDK).

Chat Completions with response_format=json_object. Temperature 0 where the model supports it
(reasoning models reject it; we then retry once without). Retries 429 / 5xx with backoff;
anything else, a refusal or non-JSON output -> LLMError, so the ticket is left open.
"""
import random
import time

import requests

from app.clients.llm import PROVIDERS, LLMError, LLMNotConfigured, LLMResult, parse_json_loose

BASE_URL = "https://api.openai.com/v1"


class OpenAIClient:
    MAX_RETRIES = 4

    def __init__(self, api_key: str, model: str, timeout: float = 60,
                 session: requests.Session | None = None, sleep=time.sleep):
        if not api_key:
            raise LLMNotConfigured("OPENAI_API_KEY is empty")
        if not model:
            raise LLMNotConfigured("LLM_MODEL is empty (run: python -m app.cli models)")
        self.model = model
        self.timeout = timeout
        self._sleep = sleep
        self._send_temperature = True
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def _body(self, system: str, user: str) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        if self._send_temperature:
            body["temperature"] = 0
        return body

    def complete_json(self, system: str, user: str) -> LLMResult:
        url = f"{BASE_URL}/chat/completions"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.post(url, json=self._body(system, user), timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.MAX_RETRIES:
                    raise LLMError(f"OpenAI unreachable: {exc}") from exc
                self._sleep(self._backoff(attempt))
                continue
            if resp.status_code == 400 and self._send_temperature and "temperature" in self._error_message(resp):
                self._send_temperature = False          # model doesn't support it; retry once without
                attempt -= 1
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.MAX_RETRIES \
                    and "insufficient_quota" not in resp.text:
                self._sleep(self._retry_after(resp, attempt))
                continue
            if resp.status_code != 200:
                raise LLMError(f"OpenAI HTTP {resp.status_code}: {self._error_message(resp)}")
            return self._parse(resp.json())

    def _parse(self, data: dict) -> LLMResult:
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("OpenAI returned no choices")
        msg = choices[0].get("message") or {}
        if msg.get("refusal"):
            raise LLMError(f"OpenAI refused: {msg['refusal'][:200]}")
        text = msg.get("content") or ""
        if not text:
            raise LLMError(f"OpenAI returned empty content (finish_reason={choices[0].get('finish_reason')})")
        try:
            parsed = parse_json_loose(text)
        except ValueError as exc:
            raise LLMError(f"OpenAI output is not JSON: {exc}") from exc
        usage = data.get("usage") or {}
        return LLMResult(data=parsed, model=data.get("model") or self.model,
                         input_tokens=int(usage.get("prompt_tokens") or 0),
                         output_tokens=int(usage.get("completion_tokens") or 0))

    def list_models(self) -> list[str]:
        resp = self.session.get(f"{BASE_URL}/models", timeout=self.timeout)
        if resp.status_code != 200:
            raise LLMError(f"OpenAI HTTP {resp.status_code}: {self._error_message(resp)}")
        return sorted(m["id"] for m in resp.json().get("data", []))

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2 ** attempt, 30) + random.uniform(0, 0.5)

    def _retry_after(self, resp, attempt: int) -> float:
        try:
            return min(float(resp.headers.get("Retry-After")), 60)
        except (TypeError, ValueError):
            return self._backoff(attempt)

    @staticmethod
    def _error_message(resp) -> str:
        try:
            return (resp.json().get("error") or {}).get("message", "")[:300]
        except ValueError:
            return resp.text[:300]


def _factory(settings):
    return OpenAIClient(settings.llm_api_key, settings.llm_model)


PROVIDERS["openai"] = _factory
