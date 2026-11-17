"""Eval runner end-to-end with a fake LLM: scoring, safety count, report files (no network)."""
from eval import run_eval
from app.pipeline.service import TicketAgent
from tests.fakes import KB, FakeLLM, cls_json

EXAMPLES = [
    {"id": "E1", "subject": "Wachtwoord", "body": "Wachtwoord vergeten",
     "label": {"language": "nl", "category": "question", "priority": "P4", "action": "reply", "reason": "F01"}},
    {"id": "E2", "subject": "Geld terug", "body": "Kunnen we ons geld terugkrijgen?",
     "label": {"language": "nl", "category": "billing", "priority": "P2", "action": "handoff", "reason": "refund"}},
    {"id": "E3", "subject": "Prijs", "body": "Wat kost het?",
     "label": {"language": "nl", "category": "billing", "priority": "P4", "action": "handoff", "reason": "x"}},
]


def test_eval_scores_and_writes_report(tmp_path, monkeypatch):
    llm = FakeLLM(classify=cls_json())                     # always proposes a verified reply
    agent = TicketAgent(KB, llm, 0.70)
    monkeypatch.setattr(run_eval, "build_agent", lambda **kw: (agent, "eval-test"))
    monkeypatch.setattr(run_eval, "load_examples", lambda source: EXAMPLES)
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)

    report = run_eval.evaluate(tag="t")

    assert report["n"] == 3
    assert report["accuracy"]["action"] == 2 / 3           # E1 reply ok, E2 forced handoff ok, E3 wrong
    assert report["safety_violations"] == 1                # E3: replied where the label says handoff
    md = next(tmp_path.glob("*-t.md")).read_text(encoding="utf-8")
    assert "safety violations" in md and "back-translation" in md
    assert next(tmp_path.glob("*-t.json"))
