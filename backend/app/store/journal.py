"""S1 / S7a Journal [CODE]: local SQLite record of what we decided and posted, for crash safety.

States:  planned  -> decision stored, POST not yet confirmed
         completed -> server confirmed (2xx, 409, or remote state shows handled)
         failed    -> gave up for this run; the stored decision is replayed next run
A stored decision is always replayed as-is, so the LLM can never change its answer between runs.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.schemas import Decision

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    decision    TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    outcome     TEXT,
    last_error  TEXT,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    ticket_id   TEXT NOT NULL,
    status      TEXT NOT NULL,
    decision    TEXT,
    outcome     TEXT,
    archived_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Journal:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def get(self, ticket_id: str) -> Optional[dict]:
        row = self._db.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["decision"] = Decision.model_validate_json(d["decision"]) if d["decision"] else None
        return d

    def plan(self, decision: Decision) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO tickets(ticket_id,status,decision,attempts,updated_at) VALUES(?,?,?,0,?) "
                "ON CONFLICT(ticket_id) DO UPDATE SET status='planned', decision=excluded.decision, "
                "attempts=0, outcome=NULL, last_error=NULL, updated_at=excluded.updated_at",
                (decision.ticket_id, "planned", decision.model_dump_json(), _now()))

    def attempt(self, ticket_id: str) -> int:
        with self._lock:
            self._db.execute("UPDATE tickets SET attempts=attempts+1, updated_at=? WHERE ticket_id=?",
                             (_now(), ticket_id))
            return self._db.execute("SELECT attempts FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()[0]

    def complete(self, ticket_id: str, outcome: str) -> None:
        self._set(ticket_id, "completed", outcome=outcome)

    def fail(self, ticket_id: str, error: str) -> None:
        self._set(ticket_id, "failed", error=error[:500])

    def _set(self, ticket_id, status, outcome=None, error=None):
        with self._lock:
            self._db.execute("UPDATE tickets SET status=?, outcome=?, last_error=?, updated_at=? WHERE ticket_id=?",
                             (status, outcome, error, _now(), ticket_id))

    def archive(self, ticket_id: str) -> None:
        """Ticket was re-opened on the server (practice reset): keep the old row in history, start fresh."""
        with self._lock:
            self._db.execute(
                "INSERT INTO history SELECT ticket_id,status,decision,outcome,? FROM tickets WHERE ticket_id=?",
                (_now(), ticket_id))
            self._db.execute("DELETE FROM tickets WHERE ticket_id=?", (ticket_id,))

    def counts(self) -> dict:
        return {r["status"]: r["n"] for r in
                self._db.execute("SELECT status, COUNT(*) n FROM tickets GROUP BY status")}

    def close(self):
        self._db.close()
