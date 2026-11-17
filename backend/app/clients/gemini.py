"""Gemini provider for the writing/deciding LLM (REST, no extra SDK).

Uses generateContent with responseMimeType=application/json and temperature 0.
Retries 429 / 5xx with backoff; anything else, a blocked response or non-JSON output -> LLMError,
which makes the pipeline leave the ticket open instead of guessing.
"""
import random
import time

import requests

from app.clients.llm import PROVIDERS, LLMError, LLMNotConfigured, LLMResult, parse_json_loose

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    MAX_RETRIES = 4

    def __init__(self, api_key: str, model: str, timeout: float = 60, thinking_budget: int | None = None,
                 session: requests.Session | None = None, sleep=time.sleep, max_output_tokens: int = 4096):
        if not api_key:
            raise LLMNotConfigured("LLM_API_KEY is empty")
        if not model:
            raise LLMNotConfigured("LLM_MODEL is empty (run: python -m app.cli models)")
        self.model = model.removeprefix("models/")
        self.timeout = timeout
        self.thinking_budget = thinking_budget
        self.max_output_tokens = max_output_tokens
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update({"x-goog-api-key": api_key, "Content-Type": "application/json"})

    def _body(self, system: str, user: str) -> dict:
        gen = {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": self.max_output_tokens}
        if self.thinking_budget is not None:
            gen["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        }

    def complete_json(self, system: str, user: str) -> LLMResult:
        url = f"{BASE_URL}/models/{self.model}:generateContent"
        body = self._body(system, user)
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = self.session.post(url, json=body, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.MAX_RETRIES:
                    raise LLMError(f"Gemini unreachable: {exc}") from exc
                self._sleep(self._backoff(attempt))
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.MAX_RETRIES:
                self._sleep(self._retry_after(resp, attempt))
                continue
            if resp.status_code != 200:
                raise LLMError(f"Gemini HTTP {resp.status_code}: {self._error_message(resp)}")
            return self._parse(resp.json())
        raise LLMError("Gemini: retries exhausted")

    def _parse(self, data: dict) -> LLMResult:
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"Gemini returned no answer ({reason})")
        cand = cands[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise LLMError(f"Gemini returned empty content (finishReason={cand.get('finishReason')})")
        try:
            parsed = parse_json_loose(text)
        except ValueError as exc:
            raise LLMError(f"Gemini output is not JSON: {exc}") from exc
        usage = data.get("usageMetadata") or {}
        return LLMResult(
            data=parsed,
            model=data.get("modelVersion") or self.model,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            # thinking tokens are billed as output
            output_tokens=int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0),
        )

    def list_models(self) -> list[str]:
        resp = self.session.get(f"{BASE_URL}/models", params={"pageSize": 200}, timeout=self.timeout)
        if resp.status_code != 200:
            raise LLMError(f"Gemini HTTP {resp.status_code}: {self._error_message(resp)}")
        return [m["name"].removeprefix("models/") for m in resp.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]

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
            return resp.json().get("error", {}).get("message", "")[:300]
        except ValueError:
            return resp.text[:300]


def _factory(settings):
    budget = settings.llm_thinking_budget
    return GeminiClient(settings.llm_api_key, settings.llm_model,
                        thinking_budget=int(budget) if budget not in ("", None) else None,
                        max_output_tokens=settings.llm_max_output_tokens)


PROVIDERS["gemini"] = _factory
