"""HTTP client: 503 retry, 429 Retry-After, 409, POST network errors (no real network)."""
import pytest
import requests

from app.clients.helpdesk import AlreadyHandled, HelpdeskClient, HelpdeskError


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(responses):
    sleeps = []
    c = HelpdeskClient("https://x", "k", "me@example.com", session=Session(responses), sleep=sleeps.append)
    return c, sleeps


def test_503_is_retried_then_succeeds():
    c, _ = client([Resp(503), Resp(503), Resp(200, {"ok": 1})])
    assert c.status() == {"ok": 1}


def test_429_waits_retry_after():
    c, sleeps = client([Resp(429, headers={"Retry-After": "2"}), Resp(200, {"ok": 1})])
    assert c.status() == {"ok": 1}
    assert any(s >= 2 for s in sleeps)


def test_409_raises_already_handled_without_retry():
    c, _ = client([Resp(409, {"error": "already_handled"})])
    with pytest.raises(AlreadyHandled):
        c.act("T1", "reply", {})
    assert len(c.session.calls) == 1


def test_503_gives_up_after_max_retries():
    c, _ = client([Resp(503)] * HelpdeskClient.MAX_RETRIES)
    with pytest.raises(HelpdeskError) as e:
        c.act("T1", "reply", {})
    assert e.value.status == 503


def test_post_network_error_is_not_retried_blindly():
    c, _ = client([requests.Timeout("t"), Resp(200)])
    with pytest.raises(requests.Timeout):
        c.act("T1", "reply", {})
    assert len(c.session.calls) == 1


def test_get_network_error_is_retried():
    c, _ = client([requests.ConnectionError("x"), Resp(200, {"ok": 1})])
    assert c.status() == {"ok": 1}


def test_pagination_follows_cursor():
    c, _ = client([Resp(200, {"tickets": [{"id": "A"}], "next_cursor": "A"}),
                   Resp(200, {"tickets": [{"id": "B"}], "next_cursor": None})])
    assert [t["id"] for t in c.iter_tickets()] == ["A", "B"]


def test_rejects_unknown_action():
    c, _ = client([])
    with pytest.raises(ValueError):
        c.act("T1", "delete", {})
