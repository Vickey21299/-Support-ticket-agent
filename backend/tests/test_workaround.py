"""Regression tests for the split workaround facts (workaround = fix_in_help_centre OR alternative_workflow_available).

Each case uses facts as the LLM would extract them for that kind of ticket; the code never looks at ticket IDs.
"""
import pytest

from app.pipeline.policy import decide
from app.pipeline.priority import calculate_priority
from app.pipeline.redact import sanitize
from app.pipeline.rules import evaluate
from app.schemas import Classification, PriorityFacts, Ticket, Verification
from tests.fakes import KB, cls_json, ver_json

BASE = cls_json()["facts"]


def run(subject, body, facts, **cls_over):
    t = Ticket(id="T1", subject=subject, body=body)
    red = sanitize(t.subject, t.body)
    c = Classification.model_validate(cls_json(facts={**BASE, **facts}, **cls_over))
    return decide(t, red, evaluate(red), c, None, Verification.model_validate(ver_json(language_detected="en")),
                  KB, 0.70, 0.70)


# 1. E01-like: crash on an unsupported OS, the help centre documents the requirement -> P3
def test_documented_fix_gives_p3():
    d = run("App crashes", "The app crashes immediately on my iPhone 8 (iOS 15). Other staff are fine.",
            {"something_broken": True, "others_unaffected": True, "fix_in_help_centre": True, "fix_section": "F01"},
            language="en", category="bug")
    assert d.priority == "P3" and d.facts.workaround_available is True


# 2. E06-like: one customer blocked, no fix and no other way -> P2
def test_blocked_without_workaround_gives_p2():
    d = run("Can't publish rota", "When I click Publish I get 'Something went wrong'.",
            {"something_broken": True, "fix_in_help_centre": False, "alternative_workflow_available": False},
            language="en", category="bug", action="handoff", draft_reply=None, handoff_note="Publish fails.")
    assert d.priority == "P2" and d.facts.workaround_available is False


# 3. T027-like: cosmetic typo -> P4
def test_cosmetic_typo_gives_p4():
    r = calculate_priority(PriorityFacts(something_broken=True, cosmetic_only=True, others_unaffected=True,
                                         fix_in_help_centre=False, alternative_workflow_available=True))
    assert r.priority == "P4"


# 4. T006-like: several locations cannot use the app -> P1
def test_many_users_blocked_gives_p1():
    r = calculate_priority(PriorityFacts(many_users_blocked=True, something_broken=True,
                                         fix_in_help_centre=False, alternative_workflow_available=False))
    assert r.priority == "P1"


# 5. T018-like: security incident -> P1, whatever the workaround facts say
def test_security_gives_p1():
    r = calculate_priority(PriorityFacts(security_or_legal_risk=True, something_broken=True, fix_in_help_centre=True,
                                         cosmetic_only=True))
    assert r.priority == "P1"


# 6. others unaffected is impact, not a workaround -> not P3 on its own
def test_others_unaffected_alone_is_not_a_workaround():
    f = PriorityFacts(something_broken=True, others_unaffected=True, fix_in_help_centre=False,
                      alternative_workflow_available=False)
    assert f.workaround_available is False and calculate_priority(f).priority == "P2"


def test_others_unaffected_with_unknown_rest_is_not_p3():
    f = PriorityFacts(something_broken=True, others_unaffected=True)
    r = calculate_priority(f)
    assert f.workaround_available is None and r.priority == "P2" and r.uncertain


# 7. a FAQ fix only counts when it names a real section; a related citation is not a fix
def test_claimed_fix_without_valid_section_is_unknown():
    d = run("App crashes", "The app crashes on my phone.",
            {"something_broken": True, "fix_in_help_centre": True, "fix_section": "F99"}, language="en", category="bug")
    assert d.priority == "P2" and d.action == "handoff"
    assert "without a valid section" in " ".join(d.policy_notes)


def test_cited_faq_but_fix_not_applicable_is_not_p3():
    d = run("Export wrong", "The export shows double hours.",
            {"something_broken": True, "fix_in_help_centre": False, "alternative_workflow_available": False},
            language="en", category="bug", faq_ids=["F01"], action="handoff", draft_reply=None,
            handoff_note="Export bug.")
    assert d.priority == "P2"


# 8. missing or ambiguous evidence -> human review, never a silent guess
@pytest.mark.parametrize("facts", [
    {"something_broken": True},                                                      # all three null
    {"something_broken": True, "fix_in_help_centre": False},                         # alternative unknown
    {"something_broken": True, "alternative_workflow_available": False},             # fix unknown
])
def test_unknown_workaround_goes_to_a_human(facts):
    d = run("App issue", "Something is not working for me in the app.", facts, language="en", category="bug")
    assert d.action == "handoff" and d.priority == "P2"
    assert any("priority unclear" in n for n in d.policy_notes)


def test_unknown_is_never_silently_false():
    assert PriorityFacts(something_broken=True, fix_in_help_centre=False).workaround_available is None
