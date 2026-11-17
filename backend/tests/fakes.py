"""Test doubles: a scripted LLM and an in-memory helpdesk with injectable failures."""
import requests

from app.clients.helpdesk import AlreadyHandled, HelpdeskError
from app.clients.llm import LLMResult
from app.knowledge.faq import parse_faq

FAQ_MD = """# FAQ
## F01 · Forgotten password
Go to app.roosterly.nl/login and click "Wachtwoord vergeten".

## F10 · Ideas and feature requests
Feature requests go on our public roadmap at roadmap.roosterly.nl.

---

## The client's rules for the support team
- Refunds always go to a human.
"""
KB = parse_faq(FAQ_MD)


def cls_json(**over):
    base = {"language": "nl", "category": "question", "priority": "P4", "action": "reply",
            "faq_ids": ["F01"], "reason": "Password question answered by F01.", "confidence": 0.9,
            "summary_en": "Customer forgot their password.",
            "draft_reply": "Hoi Marloes, ga naar app.roosterly.nl/login en klik op 'Wachtwoord vergeten'. Team Roosterly",
            "handoff_note": None}
    base.update(over)
    return base


def ver_json(**over):
    base = {"back_translation_en": "Hi Marloes, go to app.roosterly.nl/login ...", "language_detected": "nl",
            "answers_question": True, "unsupported_claims": [], "violations": [], "supported": True}
    base.update(over)
    return base


class FakeLLM:
    """Returns classify output for classify prompts and verify output for verify prompts."""
    model = "fake-1"

    def __init__(self, classify=None, verify=None, fail=False):
        self.classify = classify if classify is not None else cls_json()
        self.verify = verify if verify is not None else ver_json()
        self.fail = fail
        self.calls = []

    def complete_json(self, system, user):
        self.calls.append(system[:30])
        if self.fail:
            raise RuntimeError("provider down")
        data = self.verify if "strict reviewer" in system else self.classify
        if callable(data):
            data = data()
        return LLMResult(data=data, model=self.model, input_tokens=100, output_tokens=50)


class FakeHelpdesk:
    def __init__(self, failures=None):
        self.handled: dict[str, dict] = {}
        self.posts: list[tuple[str, str, dict]] = []
        # list of exceptions/markers to raise on successive act() calls; "saved_then_timeout" saves, then raises
        self.failures = list(failures or [])

    def act(self, ticket_id, action, body):
        if ticket_id in self.handled:
            raise AlreadyHandled(409, {"error": "already_handled"})
        if self.failures:
            f = self.failures.pop(0)
            if f == "saved_then_timeout":
                self._save(ticket_id, action, body)
                raise requests.Timeout("read timed out")
            raise f
        self._save(ticket_id, action, body)
        return {"ok": True}

    def _save(self, ticket_id, action, body):
        self.posts.append((ticket_id, action, body))
        self.handled[ticket_id] = {"action": action, **body}

    def is_handled(self, ticket_id):
        return ticket_id in self.handled

    def ticket(self, ticket_id):
        return {"id": ticket_id, "handled": self.handled.get(ticket_id)}


def http_error(status):
    return HelpdeskError(status, {"error": "x"})
