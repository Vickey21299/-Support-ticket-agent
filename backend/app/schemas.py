"""Data models shared by the pipeline, the FastAPI layer, LLM output validation and the eval."""
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal["nl", "en", "de"]
Category = Literal["bug", "billing", "feature_request", "question", "other"]
Priority = Literal["P1", "P2", "P3", "P4"]
Action = Literal["reply", "handoff", "close"]

PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def most_severe(*priorities: Optional[str]) -> str:
    present = [p for p in priorities if p in PRIORITY_RANK]
    return min(present, key=PRIORITY_RANK.__getitem__) if present else "P4"


class Ticket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    subject: str = ""
    body: str = ""
    channel: Optional[str] = None
    customer_plan: Optional[str] = None
    received_at: Optional[str] = None

    @field_validator("subject", "body", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return v or ""


class Redaction(BaseModel):
    """Stage S2 output: ticket text with sensitive data masked."""
    subject: str
    body: str
    has_payment_data: bool = False
    injection_suspected: bool = False
    redaction_types: list[str] = []


class RuleResult(BaseModel):
    """Stage S3 output. Rules can only force a *more careful* action."""
    forced_action: Optional[Literal["handoff", "close"]] = None
    min_priority: Optional[Priority] = None
    hits: list[str] = []


class Classification(BaseModel):
    """Stage S4 output: what the LLM must return (validated strictly)."""
    model_config = ConfigDict(extra="ignore")

    language: Language
    category: Category
    priority: Priority
    action: Action
    faq_ids: list[str] = []
    reason: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)
    summary_en: str = Field(min_length=1)
    draft_reply: Optional[str] = None
    handoff_note: Optional[str] = None

    @field_validator("language", "category", "priority", "action", mode="before")
    @classmethod
    def _normalise(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v.upper() if re.fullmatch(r"[pP][1-4]", v) else v.lower()
        return v

    @field_validator("faq_ids", mode="before")
    @classmethod
    def _faq_ids(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip().upper() for x in v if str(x).strip()]

    @model_validator(mode="after")
    def _text_for_action(self):
        if self.action == "reply" and not (self.draft_reply or "").strip():
            raise ValueError("draft_reply is required when action is 'reply'")
        if self.action == "handoff" and not (self.handoff_note or "").strip():
            raise ValueError("handoff_note is required when action is 'handoff'")
        return self


class Verification(BaseModel):
    """Stage S5 output: independent check of a draft reply."""
    model_config = ConfigDict(extra="ignore")

    back_translation_en: str = ""
    language_detected: str = ""
    answers_question: bool = False
    unsupported_claims: list[str] = []
    violations: list[str] = []
    supported: bool = False

    @field_validator("language_detected", mode="before")
    @classmethod
    def _lang(cls, v):
        return (v or "").strip().lower()

    @property
    def passed(self) -> bool:
        return self.supported and self.answers_question and not self.unsupported_claims and not self.violations


class Decision(BaseModel):
    """Stage S6 output: the one decision we post, plus audit data for the log."""
    ticket_id: str
    action: Action
    language: Language
    category: Category
    priority: Priority
    reason: str
    draft_reply: Optional[str] = None
    handoff_note: Optional[str] = None
    confidence: Optional[float] = None

    # audit only (never sent to the helpdesk)
    llm_action: Optional[Action] = None
    faq_ids: list[str] = []
    rule_hits: list[str] = []
    flags: list[str] = []
    policy_notes: list[str] = []
    verification: Optional[Verification] = None
    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0

    def api_payload(self) -> dict:
        payload = {
            "language": self.language,
            "category": self.category,
            "priority": self.priority,
            "reason": self.reason,
        }
        if self.confidence is not None:
            payload["confidence"] = round(self.confidence, 3)
        if self.action == "reply":
            payload["draft_reply"] = self.draft_reply
        elif self.action == "handoff":
            payload["handoff_note"] = self.handoff_note
        return payload
