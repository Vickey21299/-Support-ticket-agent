"""Regression checks: language detected in code, cosmetic -> P4, and how policy uses both (no network, no LLM).

The texts are written like the failing practice tickets, but the code never looks at ticket IDs.
"""
import pytest

from app.pipeline.language import customer_text, detect_language
from app.pipeline.policy import decide
from app.pipeline.priority import calculate_priority
from app.pipeline.redact import sanitize
from app.pipeline.rules import evaluate
from app.schemas import Classification, PriorityFacts, Ticket, Verification
from tests.fakes import KB, cls_json, ver_json


# --- language detection ----------------------------------------------------------------
@pytest.mark.parametrize("subject,body,expected", [
    ("URGENT app down", "Nobody in our three restaurants can open the app since 08:00. We get 'Error 503'.", "en"),
    ("Typo", "In the German version the button says 'Schicht tauschenn'. Small thing.", "en"),   # quoted German
    ("Nieuwe medewerker", "Goedemorgen, hoe voeg ik een nieuwe medewerker toe aan ons rooster?", "nl"),
    ("Schichten tauschen", "Wie können meine Mitarbeiter untereinander Schichten tauschen?", "de"),
    ("Knop", "De knop 'Shift swap' doet niks op mijn telefoon. Wat moet ik doen?", "nl"),       # quoted English
])
def test_detects_the_customers_own_language(subject, body, expected):
    r = detect_language(subject, body)
    assert r.code == expected and r.confident


def test_quoted_text_is_ignored():
    assert "Schicht" not in customer_text("Typo", "The button says 'Schicht tauschenn'.")


@pytest.mark.parametrize("subject,body", [("Re:", ""), ("", "   "), ("", "4111 1111 1111 1111")])
def test_no_text_means_no_language(subject, body):
    assert detect_language(subject, body).code is None


@pytest.mark.parametrize("subject,body", [("ok", ""), ("Typo", "")])
def test_very_short_text_is_unsure(subject, body):
    assert not detect_language(subject, body).confident


# --- priority regressions ----------------------------------------------------------------
def f(**kw):
    return PriorityFacts(**kw)


def test_cosmetic_is_p4():
    assert calculate_priority(f(something_broken=True, fix_in_help_centre=True, cosmetic_only=True)).priority == "P4"


def test_blocked_outweighs_cosmetic():
    assert calculate_priority(f(something_broken=True, fix_in_help_centre=False, alternative_workflow_available=False, cosmetic_only=True)).priority == "P2"


def test_security_never_downgraded_by_cosmetic():
    assert calculate_priority(f(security_or_legal_risk=True, cosmetic_only=True)).priority == "P1"


def test_functional_defect_with_workaround_is_p3():
    assert calculate_priority(f(something_broken=True, fix_in_help_centre=True)).priority == "P3"


def test_one_customer_blocked_is_p2():
    assert calculate_priority(f(something_broken=True, fix_in_help_centre=False, alternative_workflow_available=False)).priority == "P2"


# --- policy uses the detected language ----------------------------------------------------
def run(subject, body, **cls_over):
    t = Ticket(id="T1", subject=subject, body=body)
    red = sanitize(t.subject, t.body)
    c = Classification.model_validate(cls_json(**cls_over))
    ver = Verification.model_validate(ver_json(language_detected=cls_over.get("language", "nl")))
    return decide(t, red, evaluate(red), c, None, ver, KB, 0.70, 0.70, detect_language(t.subject, t.body))


def test_code_language_overrides_model_label_on_handoff():
    d = run("URGENT app down", "Nobody in our three restaurants can open the app since this morning.",
            language="nl", action="handoff", draft_reply=None, handoff_note="App down for everyone.")
    assert d.language == "en" and d.action == "handoff" and "detected en" in d.language_basis


def test_reply_written_for_the_wrong_language_is_not_sent():
    d = run("Wachtwoord", "Hoi, ik ben mijn wachtwoord vergeten. Hoe kom ik er weer in?", language="en")
    assert d.action == "handoff" and d.language == "nl"
    assert "customer wrote in 'nl'" in d.policy_notes[0]


def test_unclear_language_never_replies():
    d = run("ok", "", language="nl")
    assert d.action == "handoff" and "language unclear" in d.policy_notes[0]


@pytest.mark.parametrize("subject,body,expected", [
    ("No puedo iniciar sesión", "Hola, desde ayer no puedo entrar en la aplicación. ¿Me pueden ayudar? Gracias, Lucía", "es"),
    ("Giriş sorunu", "Merhaba, dünden beri uygulamaya giriş yapamıyorum. Yardım edebilir misiniz? Teşekkürler, Ayşe", "tr"),
    ("Kan nie inteken nie", "Hallo, ek kan sedert gister nie by die toepassing inteken nie. Kan julle help? Dankie, Pieter", "af"),
    ("Problème de connexion", "Bonjour, je n'arrive plus à me connecter à l'application depuis hier. Pouvez-vous m'aider ?", "fr"),
])
def test_unsupported_language_is_flagged(subject, body, expected):
    r = detect_language(subject, body)
    assert r.unsupported == expected and not r.confident and r.code in ("nl", "en", "de")


def test_unsupported_language_never_replies():
    d = run("No puedo iniciar sesión", "Hola, desde ayer no puedo entrar en la aplicación. ¿Me pueden ayudar?",
            language="en")
    assert d.action == "handoff" and d.language in ("nl", "en", "de")
    assert "'es', not a supported language" in d.policy_notes[0]


def test_unsupported_language_spam_can_still_be_closed():
    d = run("Oferta SEO", "Hola, ofrecemos servicios de SEO baratos para su sitio web. ¡Contáctenos hoy!",
            language="en", action="close", category="other", draft_reply=None, faq_ids=[])
    assert d.action == "close"


def test_matching_language_still_replies():
    d = run("Wachtwoord", "Hoi, ik ben mijn wachtwoord vergeten. Hoe kom ik er weer in?", language="nl")
    assert d.action == "reply" and d.language == "nl"


def test_cosmetic_bug_keeps_bug_category():
    facts = {**cls_json()["facts"], "cosmetic_only": True}
    d = run("Typo", "In the German version the button says 'Schicht tauschenn'. Small thing.",
            language="en", category="bug", action="handoff", draft_reply=None, handoff_note="Typo in DE UI.",
            facts=facts)
    assert d.category == "bug" and d.priority == "P4" and d.language == "en"


# --- language eval: no case may be confidently wrong (no LLM, no network) ----------------
def test_language_eval_has_no_wrong_language():
    from eval.language_eval import evaluate
    rep = evaluate(write=False)
    wrong = [r for r in rep["rows"] if r["outcome"] == "WRONG"]
    assert rep["total"]["n"] >= 28 and not wrong, wrong
