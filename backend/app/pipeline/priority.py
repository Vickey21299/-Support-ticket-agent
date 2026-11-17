"""Priority engine [CODE]: the LLM extracts facts, this table turns them into P1-P4.

The table is the brief's priority definitions, made explicit:

    P1  many users blocked right now, or a security / legal risk
    P2  money or contract dispute, a GDPR/AVG request, or one customer blocked with no workaround
    P3  something is broken, but there is a workaround
    P4  cosmetic-only issues (no functional impact), and everything else: how-to, information, ideas, spam

Unclear facts (something is broken but the workaround is unknown) give the MORE severe option and
mark the result uncertain; policy.py then sends the ticket to a human. The helpdesk only accepts
P1-P4, so there is no "REVIEW" priority. The rule floor from rules.py is applied on top in policy.py.
"""
from dataclasses import dataclass

from app.schemas import PriorityFacts


@dataclass(frozen=True)
class PriorityResult:
    priority: str
    basis: str          # which facts decided it, in plain English (goes into the reason + log)
    uncertain: bool = False


def calculate_priority(f: PriorityFacts) -> PriorityResult:
    if f.security_or_legal_risk:
        return PriorityResult("P1", "security or legal risk")
    if f.many_users_blocked:
        return PriorityResult("P1", "many users blocked right now")
    if f.money_or_contract_dispute:
        return PriorityResult("P2", "money or contract dispute")
    if f.privacy_request:
        return PriorityResult("P2", "GDPR/AVG personal-data request")
    if f.something_broken and f.workaround_available is False:
        # "blocked" outweighs a cosmetic label: if the customer cannot work, it is not cosmetic
        return PriorityResult("P2", "something broken, no workaround: customer blocked")
    if f.cosmetic_only:
        return PriorityResult("P4", "cosmetic only, no functional impact")
    if f.something_broken:
        if f.workaround_available is True:
            return PriorityResult("P3", "something broken, but a workaround exists")
        return PriorityResult("P2", "something broken, workaround unknown: took the more severe option",
                              uncertain=True)
    return PriorityResult("P4", "nothing broken and no risk: how-to, information, idea or spam")
