"""Client for the Roosterly helpdesk API.

Errors the API produces on purpose, and how they are handled here:
- 429 rate_limited        -> wait Retry-After seconds, then retry (does not count as an attempt)
- 503 service_unavailable -> nothing was saved, retry with exponential backoff + jitter
- 409 already_handled     -> never retried; raised as AlreadyHandled so the caller can mark the ticket done
Network errors on a POST are NOT retried here: the request may have been saved, so the caller
(pipeline/service.py) must check the ticket's server state first.
The client throttles itself below the 5 requests/second limit.
"""
import random
import threading
import time

import requests


class HelpdeskError(Exception):
    def __init__(self, status: int, payload):
        super().__init__(f"HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


class AlreadyHandled(HelpdeskError):
    pass


class HelpdeskClient:
    MAX_RPS = 4          # stay safely below the 5/s limit
    MAX_RETRIES = 6      # for 503 / GET network errors
    MAX_429_WAITS = 10

    def __init__(self, base_url: str, key: str, email: str, name: str | None = None,
                 timeout: float = 20, session: requests.Session | None = None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {key}",
            "X-Candidate-Email": email,
            "Content-Type": "application/json",
        })
        if name:
            self.session.headers["X-Candidate-Name"] = name
        self._lock = threading.Lock()
        self._last_call = 0.0

    # --- low level -------------------------------------------------------
    def _throttle(self):
        with self._lock:
            wait = (1.0 / self.MAX_RPS) - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        attempt = 0
        waits_429 = 0
        while True:
            self._throttle()
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout):
                attempt += 1
                if method != "GET" or attempt >= self.MAX_RETRIES:
                    raise
                self._sleep(self._backoff(attempt))
                continue

            if resp.status_code == 429 and waits_429 < self.MAX_429_WAITS:
                waits_429 += 1
                self._sleep(self._retry_after(resp) + random.uniform(0, 0.3))
                continue
            if resp.status_code == 503:
                attempt += 1
                if attempt < self.MAX_RETRIES:
                    self._sleep(self._backoff(attempt))
                    continue

            payload = self._json(resp)
            if resp.status_code == 409:
                raise AlreadyHandled(409, payload)
            if resp.status_code >= 400:
                raise HelpdeskError(resp.status_code, payload)
            return payload

    @staticmethod
    def _retry_after(resp) -> float:
        try:
            return max(0.0, float(resp.headers.get("Retry-After", "1")))
        except ValueError:
            return 1.0

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(0.5 * 2 ** (attempt - 1), 8) + random.uniform(0, 0.25)

    @staticmethod
    def _json(resp):
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text[:500]}

    # --- endpoints -------------------------------------------------------
    def status(self):
        return self._request("GET", "/status")

    def examples(self) -> list[dict]:
        data = self._request("GET", "/examples")
        return data.get("examples", data) if isinstance(data, dict) else data

    def iter_tickets(self, status: str = "open", limit: int = 10):
        cursor = None
        while True:
            params = {"limit": limit, "status": status}
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/tickets", params=params)
            yield from page.get("tickets", page.get("data", []))
            cursor = page.get("next_cursor")
            if not cursor:
                break

    def ticket(self, ticket_id: str) -> dict:
        return self._request("GET", f"/tickets/{ticket_id}")

    def is_handled(self, ticket_id: str) -> bool:
        return bool(self.ticket(ticket_id).get("handled"))

    def act(self, ticket_id: str, action: str, body: dict):
        if action not in ("reply", "handoff", "close"):
            raise ValueError(f"unknown action {action!r}")
        return self._request("POST", f"/tickets/{ticket_id}/{action}", json=body)

    def reset(self):
        return self._request("POST", "/practice/reset")
