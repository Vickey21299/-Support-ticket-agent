"""Exactly-once posting, crash recovery and failure handling (S1, S7)."""
import requests

from app.pipeline.service import TicketAgent
from app.schemas import Ticket
from app.store.journal import Journal
from tests.fakes import KB, FakeHelpdesk, FakeLLM, cls_json, http_error

T = Ticket(id="T1", subject="Wachtwoord", body="Ik ben mijn wachtwoord vergeten.")


def agent(llm=None, hd=None, journal=None):
    return TicketAgent(KB, llm or FakeLLM(), 0.75, helpdesk=hd or FakeHelpdesk(),
                       journal=journal or Journal(":memory:"), max_post_attempts=3)


def test_posts_once_and_skips_on_rerun():
    a = agent()
    assert a.process(T, dry_run=False).outcome == "posted"
    # second run: server now says handled -> ticket would not be in the open list,
    # but even if it were, the journal replays nothing and the server 409 stops a duplicate
    assert len(a.helpdesk.posts) == 1


def test_409_is_treated_as_done_not_retried():
    hd = FakeHelpdesk()
    hd.handled["T1"] = {"action": "reply"}
    a = agent(hd=hd)
    res = a.process(T, dry_run=False)
    assert res.outcome == "already_handled" and hd.posts == []
    assert a.journal.get("T1")["status"] == "completed"


def test_timeout_after_save_is_reconciled_without_second_post():
    hd = FakeHelpdesk(failures=["saved_then_timeout"])
    a = agent(hd=hd)
    res = a.process(T, dry_run=False)
    assert res.outcome == "reconciled"
    assert len(hd.posts) == 1


def test_timeout_before_save_retries():
    hd = FakeHelpdesk(failures=[requests.ConnectionError("reset")])
    res = agent(hd=hd).process(T, dry_run=False)
    assert res.outcome == "posted" and len(hd.posts) == 1


def test_503_exhausted_marks_failed_and_next_run_replays_same_decision():
    j = Journal(":memory:")
    hd = FakeHelpdesk(failures=[http_error(503)])
    llm = FakeLLM()
    a = agent(llm=llm, hd=hd, journal=j)
    assert a.process(T, dry_run=False).outcome == "failed"
    calls_after_first = len(llm.calls)

    # next run: the LLM must NOT be asked again; the stored decision is posted
    res = a.process(T, dry_run=False)
    assert res.outcome == "posted"
    assert len(llm.calls) == calls_after_first
    assert len(hd.posts) == 1


def test_crash_after_plan_before_post_replays_stored_decision():
    j = Journal(":memory:")
    first = agent(journal=j)
    decision = first.analyse(T)
    j.plan(decision)                      # ... process crashed here

    llm = FakeLLM(classify=cls_json(action="handoff", draft_reply=None, handoff_note="different"))
    hd = FakeHelpdesk()
    res = agent(llm=llm, hd=hd, journal=j).process(T, dry_run=False)
    assert res.outcome == "posted" and llm.calls == []
    assert hd.posts[0][1] == "reply"      # original decision, not the new LLM's opinion


def test_crash_after_post_before_journal_update_is_reconciled():
    j = Journal(":memory:")
    hd = FakeHelpdesk()
    a = agent(hd=hd, journal=j)
    d = a.analyse(T)
    j.plan(d)
    hd._save("T1", d.action, d.api_payload())   # POST succeeded, then crash before complete()

    res = a.process(T, dry_run=False)
    assert res.outcome == "reconciled" and len(hd.posts) == 1


def test_422_is_not_retried():
    hd = FakeHelpdesk(failures=[http_error(422)])
    res = agent(hd=hd).process(T, dry_run=False)
    assert res.outcome == "failed" and hd.posts == []


def test_llm_down_leaves_ticket_open():
    hd = FakeHelpdesk()
    a = agent(llm=FakeLLM(fail=True), hd=hd)
    res = a.process(T, dry_run=False)
    assert res.outcome == "deferred" and hd.posts == [] and a.journal.get("T1") is None


def test_invalid_llm_output_retried_once_then_deferred():
    bad = {"language": "klingon"}
    llm = FakeLLM(classify=bad)
    res = agent(llm=llm).process(T, dry_run=False)
    assert res.outcome == "deferred" and len(llm.calls) == 2


def test_empty_ticket_closes_without_llm():
    llm = FakeLLM(fail=True)
    hd = FakeHelpdesk()
    res = agent(llm=llm, hd=hd).process(Ticket(id="T2", subject="Re:", body=""), dry_run=False)
    assert res.outcome == "posted" and hd.posts[0][1] == "close" and llm.calls == []


def test_practice_reset_reprocesses_completed_ticket():
    j = Journal(":memory:")
    hd = FakeHelpdesk()
    a = agent(hd=hd, journal=j)
    a.process(T, dry_run=False)
    hd.handled.clear()                    # server reset re-opened the ticket
    assert a.process(T, dry_run=False).outcome == "posted"
    assert len(hd.posts) == 2


def test_dry_run_never_posts_or_journals():
    hd = FakeHelpdesk()
    a = agent(hd=hd)
    res = a.process(T, dry_run=True)
    assert res.outcome == "dry_run" and hd.posts == [] and a.journal.get("T1") is None
