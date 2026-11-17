"""Local model via Ollama's native /api/chat (no key, no cost, runs on the local GPU).

Native API instead of Ollama's OpenAI-compatible endpoint because only the native one lets us set
num_ctx: Ollama's default context (often 4096) silently truncates the START of a long prompt, which
would cut off the FAQ in our system prompt. We also turn "thinking" off for speed and clean JSON.
"""
import time

import requests

from app.clients.llm import PROVIDERS, LLMError, LLMNotConfigured, LLMResult, parse_json_loose


class OllamaClient:
    MAX_RETRIES = 3

    def __init__(self, model: str, base_url: str = "http://localhost:11434", num_ctx: int = 8192,
                 timeout: float = 300, session: requests.Session | None = None, sleep=time.sleep):
        if not model:
            raise LLMNotConfigured("LLM_MODEL is empty (run: ollama list)")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.timeout = timeout
        self._sleep = sleep
        self._send_think = True
        self.session = session or requests.Session()

    def _body(self, system: str, user: str) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        if self._send_think:
            body["think"] = False
        return body

    def complete_json(self, system: str, user: str) -> LLMResult:
        url = f"{self.base_url}/api/chat"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.post(url, json=self._body(system, user), timeout=self.timeout)
            except requests.ConnectionError as exc:
                raise LLMError(f"Ollama not reachable at {self.base_url} (is the Ollama app running?)") from exc
            except requests.Timeout as exc:
                raise LLMError(f"Ollama timed out after {self.timeout}s") from exc
            if resp.status_code == 400 and self._send_think and "think" in resp.text.lower():
                self._send_think = False          # model has no thinking switch; retry once without it
                attempt -= 1
                continue
            if resp.status_code in (500, 503) and attempt < self.MAX_RETRIES:
                self._sleep(2 * attempt)          # e.g. model still loading
                continue
            if resp.status_code != 200:
                raise LLMError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
            return self._parse(resp.json())

    def _parse(self, data: dict) -> LLMResult:
        text = (data.get("message") or {}).get("content") or ""
        if not text.strip():
            raise LLMError(f"Ollama returned empty content (done_reason={data.get('done_reason')})")
        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        if prompt_tokens >= self.num_ctx:
            raise LLMError(f"prompt ({prompt_tokens} tokens) does not fit num_ctx={self.num_ctx}")
        try:
            parsed = parse_json_loose(text)
        except ValueError as exc:
            raise LLMError(f"Ollama output is not JSON: {exc}") from exc
        return LLMResult(data=parsed, model=data.get("model") or self.model,
                         input_tokens=prompt_tokens, output_tokens=int(data.get("eval_count") or 0))

    def list_models(self) -> list[str]:
        resp = self.session.get(f"{self.base_url}/api/tags", timeout=10)
        if resp.status_code != 200:
            raise LLMError(f"Ollama HTTP {resp.status_code}")
        return [m["name"] for m in resp.json().get("models", [])]


def _factory(settings):
    return OllamaClient(settings.llm_model, settings.ollama_base_url, settings.llm_num_ctx)


PROVIDERS["ollama"] = _factory
