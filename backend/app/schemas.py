"""Data models shared by the pipeline, the FastAPI layer, LLM output validation and the eval."""
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

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


class PriorityFacts(BaseModel):
    """Facts the LLM extracts; app/pipeline/priority.py turns them into P1-P4."""
    model_config = ConfigDict(extra="ignore")

    many_users_blocked: bool = False
    security_or_legal_risk: bool = False
    money_or_contract_dispute: bool = False
    privacy_request: bool = False
    something_broken: bool = False
    # workaround evidence, extracted separately (true / false / null = not enough evidence)
    others_unaffected: Optional[bool] = None             # impact only: NOT proof of a workaround
    fix_in_help_centre: Optional[bool] = None            # a FAQ section documents this cause AND an applicable fix
    fix_section: Optional[str] = None                    # that section's id (e.g. "F12"); checked in policy.py
    alternative_workflow_available: Optional[bool] = None
    cosmetic_only: bool = False
    evidence: str = ""

    @computed_field
    @property
    def workaround_available(self) -> Optional[bool]:
        """Derived in code: fix_in_help_centre OR alternative_workflow_available; None = unknown (never silently False)."""
        if self.fix_in_help_centre or self.alternative_workflow_available:
            return True
        if self.fix_in_help_centre is False and self.alternative_workflow_available is False:
            return False
        return None

    @field_validator("many_users_blocked", "security_or_legal_risk", "money_or_contract_dispute",
                     "privacy_request", "something_broken", "cosmetic_only", mode="before")
    @classmethod
    def _null_is_false(cls, v):
        return False if v is None else v

    def true_facts(self) -> list[str]:
        names = ["many_users_blocked", "security_or_legal_risk", "money_or_contract_dispute",
                 "privacy_request", "something_broken", "cosmetic_only"]
        out = [n for n in names if getattr(self, n)]
        if self.something_broken:
            out.append(f"workaround={self.workaround_available} (fix_in_help_centre={self.fix_in_help_centre}"
                       f"{'/' + self.fix_section if self.fix_section else ''}, "
                       f"alternative={self.alternative_workflow_available}, "
                       f"others_unaffected={self.others_unaffected})")
        return out


class Classification(BaseModel):
    """Stage S4 output: what the LLM must return (validated strictly)."""
    model_config = ConfigDict(extra="ignore")

    language: Language
    category: Category
    priority: Optional[Priority] = None     # ignored when facts are given: code calculates it
    facts: PriorityFacts
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
    decider_input_tokens: int = 0       # Jev tokens (CLASSIFIER=jev), priced separately
    needs_review: Optional[float] = None
    facts: Optional[PriorityFacts] = None
    priority_basis: Optional[str] = None
    language_basis: Optional[str] = None

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
