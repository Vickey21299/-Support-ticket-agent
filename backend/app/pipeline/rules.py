"""S3 Deterministic rules [CODE]: the client's "always a human" list, in nl / en / de.

A hit forces a handoff and sets a priority floor. Rules never force a reply.
Patterns are deliberately broad: a false positive costs one human look, a false negative can
send a wrong answer to a customer. They run on the already-masked text.
"""
import re

from app.schemas import Redaction, RuleResult, most_severe

_F = re.IGNORECASE | re.DOTALL

# name -> (priority floor, patterns)
RULES: dict[str, tuple[str, list[str]]] = {
    "refund_or_disputed_charge": ("P2", [
        r"terug\s?betal", r"terug\s?(?:storten|stort|gestort|boeken|boeking)", r"terug\s?krijgen",
        r"\bkrijgen\s+(?:\w+\s+){0,4}terug\b", r"geld\s+terug", r"\bcrediteren|creditnota",
        r"(?:dubbel|twee\s*keer|2\s*x|tweemaal)\s+(?:\S+\s+){0,4}(?:afgeschreven|betaald|gefactureerd|in\s+rekening)",
        r"onterecht\s+(?:\S+\s+){0,3}(?:afgeschreven|gefactureerd|in\s+rekening|betaald)",
        r"\brefund", r"money\s+back", r"charged\s+(?:\w+\s+){0,2}(?:twice|double|wrongly|incorrectly)",
        r"double\s+charge", r"chargeback", r"dispute",
        r"r[üu]ckerstatt", r"geld\s+zur[üu]ck", r"doppelt\s+(?:\w+\s+){0,3}(?:abgebucht|berechnet)",
    ]),
    "cancellation_or_contract_change": ("P2", [
        r"\bop\s?zeg", r"\bopgezegd", r"\bzeg(?:gen|t)?\s+(?:\w+\s+){1,4}op\b",
        r"\babonnement\s+(?:\w+\s+){0,3}(?:beëindig|beeindig|stopzet|stop|annuleer|annuleren|opheffen)",
        r"\bcontract\s+(?:\w+\s+){0,3}(?:wijzig|aanpass|beëindig|beeindig|ontbind|verleng|ontbinden)",
        r"\bdowngrad", r"\bcancel(?:l?ation|l?ing|led)?\b", r"\bterminat", r"\bend\s+(?:our|my|the)\s+(?:contract|subscription)",
        r"\bk[üu]ndig", r"\bvertrag\w*\s+(?:\w+\s+){0,3}(?:beenden|ändern|aendern|auflösen)",
    ]),
    "gdpr_request": ("P2", [
        r"\bavg\b", r"\bgdpr\b", r"\bdsgvo\b", r"inzageverzoek", r"\binzage\s+(?:\w+\s+){0,4}(?:gegevens|data|persoonsgegevens)", r"persoonsgegevens",
        r"(?:gegevens|data)\s+(?:\w+\s+){0,5}(?:verwijder|wissen|wist|vernietig)",
        r"(?:verwijder|wis)\w*\s+(?:\w+\s+){0,4}(?:gegevens|data)\b",
        r"recht\s+op\s+(?:vergetelheid|inzage|verwijdering)", r"right\s+to\s+(?:be\s+forgotten|erasure|access)",
        r"(?:delete|erase|remove)\s+(?:all\s+)?(?:of\s+)?(?:my|our)\s+(?:personal\s+)?data", r"personal\s+data",
        r"subject\s+access\s+request", r"personenbezogene", r"daten\s+(?:\w+\s+){0,3}l[öo]sch", r"datenauskunft",
    ]),
    "security_incident": ("P1", [
        r"\bhack", r"gehackt|gehacked", r"datalek|data\s*breach|\bbreach\b|datenleck",
        r"(?:vreemde|onbekende|verdachte|vreemd)\s+(?:\w+\s+){0,2}(?:login|inlog|aanmelding|activiteit)",
        r"(?:ingelogd|inlog|login|logged\s+in|signed\s+in|angemeldet).{0,120}"
        r"(?:waren\s+(?:wij|we|ik)\s+niet|was\s+ik\s+niet|niet\s+(?:door\s+)?(?:ons|mij)|wasn'?t\s+(?:us|me)|not\s+(?:us|me)|nicht\s+wir)",
        r"phishing", r"onbevoegd|unauthori[sz]ed|unbefugt",
        r"account\s+(?:is\s+)?(?:overgenomen|gekaapt|compromised|übernommen)",
        r"suspicious\s+(?:\w+\s+)?(?:login|activity|sign)", r"verd[äa]chtig\w*\s+(?:\w+\s+)?(?:anmeld|login|aktivit)",
        r"wachtwoord\s+(?:is\s+)?(?:gelekt|gestolen|uitgelekt)", r"password\s+(?:was\s+)?(?:leaked|stolen)",
    ]),
    "legal_threat": ("P1", [
        r"\badvoca(?:at|ten)\b", r"\bjurist", r"rechtszaak|rechtbank|dagvaard|ingebrekestelling",
        r"juridische\s+stappen", r"aansprakelijk", r"schade\s?vergoeding|schadeclaim",
        r"\blawyer|\battorney|\bsolicitor", r"legal\s+action|lawsuit|\bsue\b|\bsuing\b|\bliable\b|\bliability\b",
        r"\banwalt|\bklage\b|schadens?ersatz|rechtliche\s+schritte",
    ]),
    "threat_to_leave": ("P2", [
        r"\boverstap\w*\s+naar\s+(?:een\s+)?(?:ander|andere|concurrent)", r"(?:andere|nieuwe)\s+(?:leverancier|aanbieder|partij|pakket|planningstool)",
        r"\bconcurrent", r"\b(?:stoppen|vertrekken|weggaan)\s+(?:met|bij)\s+(?:jullie|roosterly)",
        r"(?:switch|move|go)\s+(?:over\s+)?to\s+(?:another|a\s+different|a\s+competitor|your\s+competitor)",
        r"\bleav(?:e|ing)\s+(?:you|roosterly)", r"anbieter\s+wechseln|\bwechseln\s+zu",
    ]),
}

_COMPILED = {name: (floor, [re.compile(p, _F) for p in pats]) for name, (floor, pats) in RULES.items()}
_REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|wg|antw)\s*:\s*)+", re.IGNORECASE)


def is_empty(subject: str, body: str) -> bool:
    """No body and nothing meaningful in the subject (e.g. just 'Re:')."""
    if body.strip():
        return False
    subj = _REPLY_PREFIX.sub("", subject or "")
    return not re.search(r"\w", subj)


def evaluate(red: Redaction) -> RuleResult:
    if is_empty(red.subject, red.body):
        return RuleResult(forced_action="close", min_priority="P4", hits=["empty_ticket"])

    text = f"{red.subject}\n{red.body}"
    hits, floors = [], []
    for name, (floor, patterns) in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            hits.append(name)
            floors.append(floor)

    if red.has_payment_data:
        # We can't act on card/bank details and must not repeat them: a human handles it.
        hits.append("payment_details_in_ticket")
        floors.append("P2")

    if not hits:
        return RuleResult()
    return RuleResult(forced_action="handoff", min_priority=most_severe(*floors), hits=hits)
