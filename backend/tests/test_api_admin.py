"""GET /status, POST /fetch, POST /practice/reset: fake helpdesk, no network."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.clients.helpdesk import HelpdeskError

TICKETS = [{"id": "T001", "subject": "a", "body": "b", "handled": None},
           {"id": "T002", "subject": "c", "body": "d", "handled": "reply"}]


class AdminHelpdesk:
    def __init__(self):
        self.resets = 0

    def status(self):
        return {"mode": "practice", "open_tickets": 1, "handled_tickets": 1, "live_ends_at": None, "candidate": "x"}

    def examples(self):
        return [{"id": "E01"}]

    def iter_tickets(self, status="open", limit=10):
        assert status == "all"
        yield from TICKETS

    def reset(self):
        self.resets += 1
        return {"ok": True, "reopened_tickets": 2}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    hd = AdminHelpdesk()
    monkeypatch.setattr(main, "make_helpdesk", lambda: hd)
    monkeypatch.setattr(main, "get_settings",
                        lambda: type("S", (), {"data_dir": tmp_path / "data",
                                               "state_db": tmp_path / "none.db"})())
    hd.data_dir = tmp_path / "data"
    return hd


client = TestClient(main.app)


def test_status_is_read_only(fake):
    r = client.get("/status")
    assert r.status_code == 200
    assert r.json() == {"mode": "practice", "open_tickets": 1, "handled_tickets": 1, "live_ends_at": None}
    assert fake.resets == 0


def test_fetch_saves_snapshot(fake):
    r = client.post("/fetch")
    assert r.status_code == 200
    body = r.json()
    assert (body["examples"], body["tickets"], body["open_in_snapshot"]) == (1, 2, 1)
    assert json.loads((fake.data_dir / "tickets.json").read_text(encoding="utf-8")) == TICKETS
    assert json.loads((fake.data_dir / "examples.json").read_text(encoding="utf-8")) == {"examples": [{"id": "E01"}]}
    assert fake.resets == 0


def test_reset_refuses_without_confirm(fake):
    r = client.post("/practice/reset")
    assert r.status_code == 400
    assert fake.resets == 0


def test_reset_with_confirm(fake):
    r = client.post("/practice/reset", params={"confirm": "true"})
    assert r.status_code == 200
    assert r.json()["reset"] == {"ok": True, "reopened_tickets": 2}
    assert fake.resets == 1


def test_reset_refused_during_live_run(fake):
    assert main._live_lock.acquire(blocking=False)
    try:
        r = client.post("/practice/reset", params={"confirm": "true"})
    finally:
        main._live_lock.release()
    assert r.status_code == 409
    assert fake.resets == 0


def test_helpdesk_error_is_passed_through(fake, monkeypatch):
    def boom():
        raise HelpdeskError(403, {"error": "forbidden"})
    monkeypatch.setattr(fake, "reset", boom)
    r = client.post("/practice/reset", params={"confirm": "true"})
    assert r.status_code == 403


def test_missing_keys_give_503(monkeypatch):
    def missing():
        raise RuntimeError("Missing HELPDESK_BASE_URL")
    monkeypatch.setattr(main, "make_helpdesk", missing)
    assert client.get("/status").status_code == 503
    assert client.post("/fetch").status_code == 503


def test_list_tickets(fake):
    r = client.get("/tickets")
    assert r.status_code == 200
    assert (r.json()["count"], r.json()["handled"]) == (2, 1)
    assert client.get("/tickets", params={"status": "handled"}).status_code == 400


def test_ticket_details_without_journal(fake, monkeypatch):
    monkeypatch.setattr(fake, "ticket", lambda tid: {"id": tid, "handled": {"action": "reply"}}, raising=False)
    r = client.get("/tickets/T002")
    assert r.status_code == 200
    assert r.json() == {"helpdesk": {"id": "T002", "handled": {"action": "reply"}}, "agent_journal": None}
