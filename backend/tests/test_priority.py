"""Priority engine: facts -> P1-P4, uncertainty -> handoff, rule floor on top."""
import json
from pathlib import Path

import pytest

from app.pipeline.policy import decide
from app.pipeline.priority import calculate_priority
from app.pipeline.redact import sanitize
from app.pipeline.rules import evaluate
from app.schemas import Classification, PriorityFacts, Ticket, Verification
from tests.fakes import KB, cls_json, ver_json


def facts(**kw):
    return PriorityFacts(**kw)


@pytest.mark.parametrize("kw,expected", [
    ({"security_or_legal_risk": True}, "P1"),
    ({"many_users_blocked": True, "something_broken": True}, "P1"),
    ({"money_or_contract_dispute": True}, "P2"),
    ({"privacy_request": True}, "P2"),
    ({"something_broken": True, "fix_in_help_centre": False, "alternative_workflow_available": False}, "P2"),
    ({"something_broken": True, "fix_in_help_centre": True}, "P3"),
    ({}, "P4"),
    ({"fix_in_help_centre": True}, "P4"),                  # workaround without anything broken: ignored
    ({"security_or_legal_risk": True, "money_or_contract_dispute": True}, "P1"),   # most severe wins
])
def test_table(kw, expected):
    r = calculate_priority(facts(**kw))
    assert r.priority == expected and not r.uncertain and r.basis


def test_broken_with_unknown_workaround_is_severe_and_uncertain():
    r = calculate_priority(facts(something_broken=True, fix_in_help_centre=None))
    assert r.priority == "P2" and r.uncertain


def test_null_facts_are_false():
    f = PriorityFacts.model_validate({"something_broken": None, "privacy_request": None})
    assert f.something_broken is False and calculate_priority(f).priority == "P4"


def test_approved_expected_facts_reproduce_nordavo_labels():
    """The approved facts for the 10 examples must give Nordavo's priority through this engine."""
    backend = Path(__file__).resolve().parents[1]
    data = json.loads((backend / "eval" / "expected_facts.json").read_text(encoding="utf-8"))
    for ex_id, item in data["examples"].items():
        assert calculate_priority(PriorityFacts(**item["facts"])).priority == item["expected_priority"], ex_id


# --- through the policy ------------------------------------------------------------
def run(body, **cls_over):
    t = Ticket(id="T1", subject="x", body=body)
    red = sanitize(t.subject, t.body)
    c = Classification.model_validate(cls_json(**cls_over))
    return decide(t, red, evaluate(red), c, None, Verification.model_validate(ver_json()), KB, 0.70)


def test_model_priority_label_is_ignored():
    d = run("Hoe reset ik mijn wachtwoord?", priority="P1")
    assert d.priority == "P4" and d.action == "reply"
    assert "Priority P4" in d.reason


def test_uncertain_priority_forces_handoff():
    f = {**cls_json()["facts"], "something_broken": True, "fix_in_help_centre": None}
    d = run("De app doet raar.", facts=f)
    assert d.action == "handoff" and d.priority == "P2" and "priority unclear" in d.policy_notes[0]


def test_rule_floor_beats_calculated_priority():
    d = run("Onze advocaat neemt contact op.")          # facts say P4, legal rule floor says P1
    assert d.priority == "P1" and "client-rule floor" in d.priority_basis


def test_missing_facts_is_invalid_output():
    with pytest.raises(Exception):
        Classification.model_validate({k: v for k, v in cls_json().items() if k != "facts"})


def test_bug_without_anything_broken_becomes_question():
    d = run("Is er vanavond onderhoud gepland?", category="bug")      # facts: nothing broken
    assert d.category == "question"


def test_bug_with_something_broken_stays_bug():
    f = {**cls_json()["facts"], "something_broken": True, "fix_in_help_centre": True, "fix_section": "F01"}
    assert run("De app crasht op mijn telefoon.", category="bug", facts=f).category == "bug"


def test_verifier_sees_the_whole_help_centre():
    from app.pipeline.prompts import verify_user
    from app.pipeline.redact import sanitize as s
    text = verify_user(s("x", "y"), "draft", KB, ["F01"], "nl")
    assert "[F01]" in text and "[F10]" in text and "cited: F01" in text
