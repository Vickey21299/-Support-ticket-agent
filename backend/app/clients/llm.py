"""Provider-agnostic LLM interface.

Every provider implements one method: complete_json(system, user) -> LLMResult.
Providers are registered in PROVIDERS; none is wired up yet (model choice pending), so get_llm()
raises LLMNotConfigured and the pipeline leaves tickets open instead of guessing.
"""
import json
import re
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    """Provider call failed (network, quota, invalid output after retry)."""


@dataclass
class LLMResult:
    data: dict
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Optional calibrated probability of the chosen action (e.g. from token logprobs).
    action_probability: Optional[float] = None


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str) -> LLMResult: ...


def parse_json_loose(text: str) -> dict:
    """Parse a JSON object from model text, tolerating ```json fences and leading prose."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


# provider name -> factory(settings) -> LLMClient
PROVIDERS: dict[str, Callable] = {}


def get_llm(settings) -> LLMClient:
    if not settings.llm_provider:
        raise LLMNotConfigured("No LLM configured: set LLM_PROVIDER / LLM_MODEL / LLM_API_KEY in .env")
    factory = PROVIDERS.get(settings.llm_provider)
    if not factory:
        raise LLMNotConfigured(
            f"LLM provider {settings.llm_provider!r} is not implemented yet (available: {sorted(PROVIDERS) or 'none'})")
    return factory(settings)
