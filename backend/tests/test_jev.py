"""Jev decision engine (CLASSIFIER=jev) with a fake SDK/client: no network, no key."""
from types import SimpleNamespace as NS

import pytest

from app.clients.llm import LLMError, LLMNotConfigured
from app.core.pricing import cost_per_100, price_for
from app.pipeline.jev_classifier import JevDecider
from app.pipeline.service import TicketAgent
from app.schemas import Ticket
from tests.fakes import KB, FakeLLM, cls_json

T = Ticket(id="T1", subject="Wachtwoord", body="Ik ben mijn wachtwoord vergeten.", customer_plan="Basis")


class FakeSDK:
    """Stands in for typesafe_sdk: Choice / Noul just record their arguments."""
    @staticmethod
    def Choice(**kw):
        return ("choice", kw)

    @staticmethod
    def Noul(**kw):
        return ("noul", kw)


def jev_response(action="reply", conf=0.9, review=0.1, category="question", language="nl", priority="P4"):
    def ch(choice, c):
        return NS(choice=choice, confidence=c, probabilities={choice: c})
    return NS(model="jev-test",
              usage=NS(input_tokens=300, output_tokens=10),
              choices={"language": ch(language, 0.99), "category": ch(category, conf),
                       "priority": ch(priority, conf), "action": ch(action, conf)},
              nouls={"needs_review": NS(noul=review)})


class FakeJevClient:
    def __init__(self, response=None, fail=False):
        self.response = response or jev_response()
        self.fail = fail
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self.fail:
            raise RuntimeError("503 from jev")
        return self.response


def agent(jev_client, llm=None):
    return TicketAgent(KB, llm or FakeLLM(), 0.70, decider=JevDecider("", client=jev_client, sdk=FakeSDK),
                       review_threshold=0.70)


def test_questions_and_masked_state_are_sent():
    client = FakeJevClient()
    agent(client).analyse(Ticket(id="T9", subject="kaart", body="Mijn kaart 4111 1111 1111 1111"))
    state, questions = client.calls[0]
    assert set(questions) == {"language", "category", "priority", "action", "needs_review"}
    assert set(questions["language"][1]["criteria"]) == {"nl", "en", "de"}      # helpdesk accepts only these
    assert "4111" not in state["body"]                                           # only masked text leaves


def test_confident_reply_passes_with_jev_labels():
    d = agent(FakeJevClient(jev_response(priority="P3", category="billing"))).analyse(T)
    assert d.action == "reply" and d.category == "billing"       # Jev's label wins over the writer's
    assert d.priority == "P4"        # priority is always calculated from the facts, never taken from a label
    assert d.confidence == pytest.approx(0.9)
    assert d.decider_input_tokens == 300 and "jev-test" in d.model


def test_low_jev_confidence_becomes_handoff():
    d = agent(FakeJevClient(jev_response(conf=0.55))).analyse(T)
    assert d.action == "handoff" and "confidence" in d.policy_notes[0]


def test_needs_review_forces_handoff():
    d = agent(FakeJevClient(jev_response(review=0.8))).analyse(T)
    assert d.action == "handoff" and "needs_review" in d.policy_notes[0]


def test_writer_can_veto_a_reply():
    writer = FakeLLM(classify=cls_json(action="handoff", draft_reply=None, handoff_note="Not covered."))
    d = agent(FakeJevClient(), llm=writer).analyse(T)
    assert d.action == "handoff" and d.handoff_note.startswith("Not covered.")


def test_close_needs_both_to_agree():
    spam_writer = FakeLLM(classify=cls_json(action="close", category="other", draft_reply=None, confidence=0.95))
    jev_close = FakeJevClient(jev_response(action="close", category="other"))
    assert agent(jev_close, llm=spam_writer).analyse(Ticket(id="S", subject="x", body="Crypto!")).action == "close"
    assert agent(jev_close).analyse(T).action == "handoff"      # writer wanted to reply -> not a clear close


def test_jev_failure_defers_ticket():
    res = agent(FakeJevClient(fail=True)).process(T, dry_run=True)
    assert res.outcome == "deferred" and "Jev" in res.error


def test_incomplete_jev_response_raises():
    bad = jev_response()
    del bad.choices["action"]
    with pytest.raises(LLMError):
        JevDecider("", client=FakeJevClient(bad), sdk=FakeSDK).decide(T, __import__(
            "app.pipeline.redact", fromlist=["sanitize"]).sanitize(T.subject, T.body))


def test_missing_key_is_a_clear_error():
    with pytest.raises(LLMNotConfigured, match="TYPESAFE_API_KEY"):
        JevDecider("")


# --- pricing ----------------------------------------------------------------------
def test_cost_per_100():
    prices = price_for("gpt-4.1-mini-2025-04-14")
    assert prices == (0.40, 1.60)
    c = cost_per_100(tokens_in=30_000, tokens_out=3_000, n_tickets=10, prices=prices)
    # 300k in * 0.40/M + 30k out * 1.60/M = 0.12 + 0.048
    assert c["usd_per_100"] == pytest.approx(0.168)
    assert price_for("unknown-model") is None
    assert price_for("x", 1.0, 2.0) == (1.0, 2.0)
