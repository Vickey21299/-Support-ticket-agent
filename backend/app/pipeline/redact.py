"""S2 Sanitize [CODE]: mask payment data and flag prompt-injection attempts.

Masked text is what the LLM, the logs and every outgoing message see. The injection flag is
informational (logged, mentioned in handoff notes); the real defence is that ticket text is
passed to the model as delimited data and that policy.py has the final say.
"""
import re

from app.schemas import Redaction

# 13-19 digits, optionally separated by spaces/dashes (card numbers). Phone numbers are shorter.
_CARD = re.compile(r"(?<![\d])(?:\d[ \-]?){12,18}\d(?![\d])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b", re.IGNORECASE)
_CVC = re.compile(
    r"\b(cvc2?|cvv2?|csc|beveiligingscode|security\s+code|kartenprüfnummer|prüfnummer)\b(\s*[:=]?\s*)\d{3,4}\b",
    re.IGNORECASE)
_EXPIRY = re.compile(
    r"\b(geldig\s+tot|vervaldatum|valid\s+(?:until|thru|through)|exp(?:iry|ires|iration)?(?:\s+date)?"
    r"|gültig\s+bis|ablaufdatum)(\s*[:=]?\s*)\d{1,2}\s*/\s*\d{2,4}",
    re.IGNORECASE)

_INJECTION = [re.compile(p, re.IGNORECASE) for p in [
    r"\b(negeer|vergeet)\s+(alle\s+)?(eerdere|vorige|voorgaande|bovenstaande)\s+(instructies|opdrachten)",
    r"\bignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?)",
    r"\bignoriere\s+(alle\s+)?(vorherigen|bisherigen|obigen)\s+anweisungen",
    r"\b(systeembericht|system\s*(message|prompt)|systemnachricht)\b",
    r"\b(notitie|bericht|note|message|hinweis|nachricht)\s+(voor|for|für|an)\s+(de\s+|the\s+|den\s+|die\s+)?"
    r"(ai|ki|bot|model|llm|assistent|assistant)",
    r"\b(ai|ki)[- ]?(assistent|assistant|agent)\b",
    r"\b(you\s+are\s+now|je\s+bent\s+nu|du\s+bist\s+jetzt)\b",
    r"\b(zet|set|setze)\s+(de\s+|the\s+|die\s+)?prio(riteit|rity|rität)?\b",
]]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def mask_text(text: str) -> tuple[str, list[str]]:
    """Return (masked_text, list of redaction types applied)."""
    found: list[str] = []

    def card(m):
        found.append("card" if _luhn_ok(re.sub(r"\D", "", m.group(0))) else "long_number")
        return "[CARD]"

    def iban(m):
        if sum(c.isdigit() for c in m.group(0)) < 10:
            return m.group(0)
        found.append("iban")
        return "[IBAN]"

    def labelled(kind):
        def repl(m):
            found.append(kind)
            return f"{m.group(1)}{m.group(2)}[REDACTED]"
        return repl

    text = _CVC.sub(labelled("cvc"), text or "")
    text = _EXPIRY.sub(labelled("expiry"), text)
    text = _IBAN.sub(iban, text)
    text = _CARD.sub(card, text)
    return text, found


def contains_payment_data(text: str) -> bool:
    return bool(mask_text(text)[1])


def detect_injection(text: str) -> bool:
    return any(p.search(text or "") for p in _INJECTION)


def sanitize(subject: str, body: str) -> Redaction:
    s, s_types = mask_text(subject)
    b, b_types = mask_text(body)
    types = sorted(set(s_types + b_types))
    return Redaction(
        subject=s,
        body=b,
        has_payment_data=bool(types),
        injection_suspected=detect_injection(subject) or detect_injection(body),
        redaction_types=types,
    )
