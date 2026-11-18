"""S6 Policy [CODE]: merge rules + LLM + verifier into the final decision. The most careful option wins.

A reply survives only if ALL checks pass; any failure turns it into a handoff, and the reason is
recorded in policy_notes and the handoff note. Priority never drops below the rule floor.
"""
import re
from typing import Optional

from app.clients.llm import LLMResult
from app.knowledge.faq import Knowledge
from app.pipeline.language import LanguageResult
from app.pipeline.priority import calculate_priority
from app.pipeline.redact import contains_payment_data, mask_text
from app.schemas import Classification, Decision, Redaction, RuleResult, Ticket, Verification, most_severe

_HOST = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:nl|com|de|eu|io|net|org|app))\b", re.IGNORECASE)
_MAX_REASON = 400


def _hosts(text: str) -> set[str]:
    return {h.lower() for h in _HOST.findall(text or "")}


def _clean(text: Optional[str]) -> Optional[str]:
    """Last line of defence: never let payment data leave, whatever produced the text."""
    return mask_text(text)[0].strip() if text else text


def _flags(red: Redaction) -> list[str]:
    return [f for f, on in [("payment_data_redacted", red.has_payment_data),
                            ("injection_suspected", red.injection_suspected)] if on]


def close_empty(ticket: Ticket, red: Redaction, rules: RuleResult) -> Decision:
    return Decision(
        ticket_id=ticket.id, action="close", language="nl", category="other", priority="P4",
        reason="Empty ticket: no subject or message to act on, so it is closed without a reply.",
        rule_hits=rules.hits, flags=_flags(red),
    )


def reply_problems(cls: Classification, ver: Optional[Verification], kb: Knowledge,
                   confidence: float, threshold: float, language: Optional[str] = None) -> list[str]:
    language = language or cls.language
    problems = []
    if confidence < threshold:
        problems.append(f"confidence {confidence:.2f} is below the {threshold:.2f} reply threshold")
    if not [f for f in cls.faq_ids if f in kb.sections]:
        problems.append("no valid help-centre section cited")
    draft = cls.draft_reply or ""
    if contains_payment_data(draft):
        problems.append("draft contains payment-like data")
    unknown = _hosts(draft) - kb.allowed_hosts
    if unknown:
        problems.append(f"draft mentions links not in the help centre ({', '.join(sorted(unknown))})")
    if ver is None:
        problems.append("reply was not verified")
    else:
        if ver.language_detected != language:
            problems.append(f"verifier: reply language '{ver.language_detected}' != ticket language '{language}'")
        if not ver.answers_question:
            problems.append("verifier: draft does not answer everything the customer asked")
        if ver.unsupported_claims or not ver.supported:
            problems.append("verifier: draft has claims not supported by the help centre")
        if ver.violations:
            problems.append("verifier: rule violation in draft (" + "; ".join(ver.violations)[:120] + ")")
    return problems


def _handoff_note(cls: Classification, red: Redaction, rules: RuleResult, notes: list[str]) -> str:
    parts = [(cls.handoff_note or cls.summary_en).strip()]
    if rules.hits:
        parts.append(f"Client rule: always a human ({', '.join(rules.hits)}).")
    if cls.action == "reply" and notes:
        parts.append("Auto-escalated instead of replying: " + "; ".join(notes) + ".")
    if red.has_payment_data:
        parts.append("The customer sent payment details; they were redacted and not stored.")
    if red.injection_suspected:
        parts.append("The ticket contains text that tries to instruct the AI; it was ignored.")
    return " ".join(p for p in parts if p)


def effective_confidence(cls: Classification, meta: Optional[LLMResult]) -> float:
    """Best available confidence: the lowest per-field probability (Jev), else the action probability,
    else the model's self-reported confidence."""
    if meta and meta.field_confidence:
        fields = [meta.field_confidence[f] for f in ("action", "category", "priority") if f in meta.field_confidence]
        if fields:
            return min(fields)
    if meta and meta.action_probability is not None:
        return meta.action_probability
    return cls.confidence


def decide(ticket: Ticket, red: Redaction, rules: RuleResult, cls: Classification,
           meta: Optional[LLMResult], ver: Optional[Verification], kb: Knowledge,
           threshold: float, review_threshold: float = 0.70,
           lang: Optional[LanguageResult] = None) -> Decision:
    notes: list[str] = []
    action = cls.action

    # 0. language: decided by code when it is confident; otherwise the model's label, and no reply
    language, language_basis = cls.language, f"model ({cls.language})"
    if lang and lang.code and lang.confident:
        language, language_basis = lang.code, f"detected {lang.describe()}"
        if cls.language != lang.code and action == "reply":
            notes.append(f"model wrote for '{cls.language}' but the customer wrote in '{lang.code}'")
            action = "handoff"
    elif lang is not None and lang.unsupported and action != "close":
        notes.append(f"customer wrote in '{lang.unsupported}', not a supported language (nl/en/de): a human answers")
        action = "handoff"
    elif lang is not None and action == "reply":
        notes.append(f"language unclear ({lang.describe()}): not replying without a human")
        action = "handoff"
    confidence = effective_confidence(cls, meta)
    needs_review = meta.needs_review if meta else None

    # 1. deterministic rules win
    if rules.forced_action == "handoff" and action != "handoff":
        notes.append(f"client rules require a human ({', '.join(rules.hits)})")
        action = "handoff"

    # 1a. priority is calculated from the extracted facts; unclear facts -> a human checks.
    #     A claimed help-centre fix must name an existing section, otherwise it counts as unknown.
    facts = cls.facts
    if facts.fix_in_help_centre and (facts.fix_section or "").strip().upper() not in kb.sections:
        notes.append(f"claimed help-centre fix without a valid section ({facts.fix_section or 'none'}): treated as unknown")
        facts = facts.model_copy(update={"fix_in_help_centre": None})
    prio = calculate_priority(facts)
    if prio.uncertain and action != "handoff":
        notes.append(f"priority unclear ({prio.basis})")
        action = "handoff"

    # 1b. the decision model says a human should look first
    if needs_review is not None and needs_review >= review_threshold and action != "handoff":
        notes.append(f"needs_review probability {needs_review:.2f} >= {review_threshold:.2f}")
        action = "handoff"

    # 2. close only for spam/empty with enough confidence
    if action == "close":
        if cls.category != "other":
            notes.append(f"close is only for spam/empty tickets, not '{cls.category}'")
            action = "handoff"
        elif confidence < threshold:
            notes.append(f"confidence {confidence:.2f} too low to close without a human")
            action = "handoff"

    # 3. reply only if every check passes
    if action == "reply":
        problems = reply_problems(cls, ver, kb, confidence, threshold, language)
        if problems:
            notes += problems
            action = "handoff"

    # category must agree with the facts: no "bug" when nothing is broken (e.g. "is maintenance planned?")
    category = cls.category
    if category == "bug" and not (facts.something_broken or facts.cosmetic_only):
        category = "question"

    priority = most_severe(prio.priority, rules.min_priority)
    basis = prio.basis if priority == prio.priority else f"client-rule floor ({', '.join(rules.hits)})"
    reason = f"{cls.reason.strip().rstrip('.')}. Priority {priority}: {basis}."
    if notes:
        reason = f"{reason} Escalated to a human: {notes[0]}."
    if len(reason) > _MAX_REASON:
        reason = reason[:_MAX_REASON - 1].rstrip() + "…"

    return Decision(
        ticket_id=ticket.id,
        action=action,
        language=language,
        category=category,
        priority=priority,
        reason=_clean(reason),
        draft_reply=_clean(cls.draft_reply) if action == "reply" else None,
        handoff_note=_clean(_handoff_note(cls, red, rules, notes)) if action == "handoff" else None,
        confidence=confidence,
        llm_action=cls.action,
        faq_ids=cls.faq_ids,
        rule_hits=rules.hits,
        flags=_flags(red),
        policy_notes=notes,
        verification=ver,
        model=meta.model if meta else None,
        input_tokens=meta.input_tokens if meta else 0,
        output_tokens=meta.output_tokens if meta else 0,
        decider_input_tokens=meta.extra_input_tokens if meta else 0,
        needs_review=needs_review,
        facts=facts,
        priority_basis=basis,
        language_basis=language_basis,
    )
