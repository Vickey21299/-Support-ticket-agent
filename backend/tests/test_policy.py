from app.clients.llm import LLMResult
from app.pipeline.policy import decide
from app.pipeline.redact import sanitize
from app.pipeline.rules import evaluate
from app.schemas import Classification, Ticket, Verification
from tests.fakes import KB, cls_json, ver_json

T = Ticket(id="T1", subject="Wachtwoord", body="Ik ben mijn wachtwoord vergeten. Groet, Marloes")


def run(body=None, cls=None, ver="default", threshold=0.75, meta=None):
    ticket = T if body is None else Ticket(id="T1", subject="x", body=body)
    red = sanitize(ticket.subject, ticket.body)
    rules = evaluate(red)
    c = Classification.model_validate(cls or cls_json())
    v = Verification.model_validate(ver_json()) if ver == "default" else (
        Verification.model_validate(ver) if ver else None)
    return decide(ticket, red, rules, c, meta, v, KB, threshold)


def test_good_reply_passes():
    d = run()
    assert d.action == "reply" and d.draft_reply and d.handoff_note is None
    assert d.api_payload()["draft_reply"]


def test_low_confidence_becomes_handoff():
    d = run(cls=cls_json(confidence=0.5))
    assert d.action == "handoff" and "confidence" in d.policy_notes[0]
    assert d.handoff_note  # summary used as note


def test_logprob_confidence_overrides_self_report():
    d = run(meta=LLMResult(data={}, model="m", action_probability=0.4))
    assert d.action == "handoff" and d.confidence == 0.4


def test_reply_without_faq_citation_is_blocked():
    assert run(cls=cls_json(faq_ids=[])).action == "handoff"
    assert run(cls=cls_json(faq_ids=["F99"])).action == "handoff"


def test_unverified_or_failed_verification_blocks_reply():
    assert run(ver=None).action == "handoff"
    assert run(ver=ver_json(supported=False, unsupported_claims=["free trial"])).action == "handoff"
    assert run(ver=ver_json(language_detected="en")).action == "handoff"
    assert run(ver=ver_json(violations=["promises refund"])).action == "handoff"
    assert run(ver=ver_json(answers_question=False)).action == "handoff"


def test_unknown_link_blocks_reply():
    d = run(cls=cls_json(draft_reply="Kijk op www.example.com voor info. Team Roosterly"))
    assert d.action == "handoff" and "links" in " ".join(d.policy_notes)


def test_rule_forces_handoff_and_priority_floor():
    d = run(body="Ik wil mijn geld terug, onze advocaat belt jullie.", cls=cls_json(priority="P4"))
    assert d.action == "handoff"
    assert d.priority == "P1"
    assert "legal_threat" in d.rule_hits
    assert "always a human" in d.handoff_note


def test_close_only_for_other_with_confidence():
    spam = cls_json(action="close", category="other", draft_reply=None, confidence=0.95)
    assert run(body="Verdien snel geld met crypto", cls=spam).action == "close"
    assert run(body="Verdien snel geld", cls={**spam, "category": "billing"}).action == "handoff"
    assert run(body="Verdien snel geld", cls={**spam, "confidence": 0.5}).action == "handoff"


def test_payment_data_never_leaves():
    body = "Nieuwe kaart 4111 1111 1111 1111 graag aanpassen"
    leaky = cls_json(action="handoff", draft_reply=None, category="billing",
                     handoff_note="Update card to 4111 1111 1111 1111.", reason="Card 4111111111111111 change.")
    d = run(body=body, cls=leaky)
    assert d.action == "handoff"
    assert "4111" not in d.handoff_note and "4111" not in d.reason
    assert "payment_data_redacted" in d.flags
