"""S4 Classify + draft [AI] and S5 Verify [AI].

Each call's output is validated with Pydantic. Invalid output gets one retry with the validation
errors; still invalid -> LLMError, and the service leaves the ticket open for the next run.
"""
from pydantic import BaseModel, ValidationError

from app.clients.llm import LLMClient, LLMError, LLMResult
from app.knowledge.faq import Knowledge
from app.pipeline import prompts
from app.schemas import Classification, Redaction, RuleResult, Ticket, Verification


def _call_validated(llm: LLMClient, system: str, user: str, model_cls: type[BaseModel]):
    total_in = total_out = 0
    last_err = ""
    for attempt in range(2):
        prompt = user if attempt == 0 else (
            f"{user}\n\nYour previous output was invalid: {last_err}\nReturn only one valid JSON object.")
        try:
            res: LLMResult = llm.complete_json(system, prompt)
        except LLMError:
            raise
        except Exception as exc:  # provider SDK errors
            raise LLMError(f"LLM call failed: {exc}") from exc
        total_in += res.input_tokens
        total_out += res.output_tokens
        try:
            obj = model_cls.model_validate(res.data)
        except ValidationError as exc:
            last_err = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())[:500]
            continue
        res.input_tokens, res.output_tokens = total_in, total_out
        return obj, res
    raise LLMError(f"invalid {model_cls.__name__} after retry: {last_err}")


def classify(llm: LLMClient, kb: Knowledge, ticket: Ticket, red: Redaction,
             rules: RuleResult) -> tuple[Classification, LLMResult]:
    return _call_validated(llm, prompts.classify_system(kb), prompts.classify_user(ticket, red, rules), Classification)


def verify(llm: LLMClient, kb: Knowledge, red: Redaction, cls: Classification) -> tuple[Verification, LLMResult]:
    user = prompts.verify_user(red, cls.draft_reply or "", kb, cls.faq_ids, cls.language)
    return _call_validated(llm, prompts.VERIFY_SYSTEM, user, Verification)
