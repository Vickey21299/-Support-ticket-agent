"""Pipeline service: runs S1-S8 for one ticket and for a whole run. Used by the CLI, FastAPI and the eval.

    analyse(ticket)            S2-S6, pure decision, never posts (used by eval, /triage, dry runs)
    process(ticket)            S1-S8 with the journal and exactly-once posting
    run_all(tickets)           process() for every ticket, returns a summary
"""
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

import requests

from app.clients.helpdesk import AlreadyHandled, HelpdeskClient, HelpdeskError
from app.clients.llm import LLMClient, LLMError, LLMNotConfigured
from app.core.logging import TicketLogger
from app.knowledge.faq import Knowledge
from app.pipeline import classifier, policy, rules
from app.pipeline.redact import sanitize
from app.schemas import Decision, Ticket
from app.store.journal import Journal


@dataclass
class TicketResult:
    ticket_id: str
    outcome: str        # posted | already_handled | reconciled | dry_run | deferred | failed | skipped
    decision: Optional[Decision] = None
    error: Optional[str] = None


@dataclass
class RunSummary:
    run_id: str
    dry_run: bool
    results: list[TicketResult] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.outcome] = out.get(r.outcome, 0) + 1
        return out


class TicketAgent:
    def __init__(self, kb: Knowledge, llm: Optional[LLMClient], threshold: float,
                 helpdesk: Optional[HelpdeskClient] = None, journal: Optional[Journal] = None,
                 logger: Optional[TicketLogger] = None, max_post_attempts: int = 3):
        self.kb = kb
        self.llm = llm
        self.threshold = threshold
        self.helpdesk = helpdesk
        self.journal = journal
        self.logger = logger
        self.max_post_attempts = max_post_attempts

    # --- S2-S6: decide (no side effects) -----------------------------------
    def analyse(self, ticket: Ticket) -> Decision:
        red = sanitize(ticket.subject, ticket.body)                       # S2
        rule_result = rules.evaluate(red)                                 # S3
        if rule_result.forced_action == "close":
            return policy.close_empty(ticket, red, rule_result)
        if self.llm is None:
            raise LLMNotConfigured("No LLM configured")
        cls, meta = classifier.classify(self.llm, self.kb, ticket, red, rule_result)   # S4
        ver, vmeta = None, None
        if cls.action == "reply" and rule_result.forced_action is None:
            ver, vmeta = classifier.verify(self.llm, self.kb, red, cls)                 # S5
        decision = policy.decide(ticket, red, rule_result, cls, meta, ver, self.kb, self.threshold)  # S6
        if vmeta:
            decision.input_tokens += vmeta.input_tokens
            decision.output_tokens += vmeta.output_tokens
        return decision

    # --- S1-S8 for one ticket -----------------------------------------------
    def process(self, ticket: Ticket, dry_run: bool = True) -> TicketResult:
        start = time.monotonic()
        result = self._process(ticket, dry_run)
        if self.logger:
            self.logger.log(ticket.id, result.outcome, result.decision,
                            int((time.monotonic() - start) * 1000), result.error)
        return result

    def _process(self, ticket: Ticket, dry_run: bool) -> TicketResult:
        if dry_run:
            try:
                return TicketResult(ticket.id, "dry_run", self.analyse(ticket))
            except (LLMError, LLMNotConfigured) as exc:
                return TicketResult(ticket.id, "deferred", error=str(exc))

        if not (self.helpdesk and self.journal):
            raise RuntimeError("live processing needs a helpdesk client and a journal")

        row = self.journal.get(ticket.id)                                 # S1
        if row and row["status"] == "completed":
            # We only get here for tickets the server lists as OPEN, so it was re-opened (practice reset).
            self.journal.archive(ticket.id)
            row = None

        if row and row["decision"]:
            decision = row["decision"]        # crash recovery: replay the stored decision, never re-generate
            if self._remote_handled(ticket.id):
                self.journal.complete(ticket.id, "reconciled")
                return TicketResult(ticket.id, "reconciled", decision)
        else:
            try:
                decision = self.analyse(ticket)
            except (LLMError, LLMNotConfigured) as exc:
                return TicketResult(ticket.id, "deferred", error=str(exc))   # leave open, retry next run
            self.journal.plan(decision)                                  # S7a persist before posting

        return self._post_once(decision)

    # --- S7b: exactly-once posting -----------------------------------------
    def _remote_handled(self, ticket_id: str) -> bool:
        try:
            return self.helpdesk.is_handled(ticket_id)
        except (HelpdeskError, requests.RequestException):
            return False  # unknown: a POST will still be stopped by the server's 409

    def _post_once(self, decision: Decision) -> TicketResult:
        tid = decision.ticket_id
        last_error = ""
        for _ in range(self.max_post_attempts):
            self.journal.attempt(tid)           # recorded for auditing; the limit is per run
            try:
                self.helpdesk.act(tid, decision.action, decision.api_payload())
                self.journal.complete(tid, "posted")
                return TicketResult(tid, "posted", decision)
            except AlreadyHandled:
                self.journal.complete(tid, "already_handled")
                return TicketResult(tid, "already_handled", decision)
            except HelpdeskError as exc:
                last_error = str(exc)
                if exc.status == 503:
                    break                       # nothing saved; client already retried. Replay next run.
                if exc.status < 500:
                    break                       # 4xx (e.g. 422): our request is wrong, retrying won't help
                # other 5xx: ambiguous -> check remote state below
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"   # ambiguous: the POST may have been saved

            if self._remote_handled(tid):
                self.journal.complete(tid, "reconciled")
                return TicketResult(tid, "reconciled", decision)

        self.journal.fail(tid, last_error or "attempts exhausted")
        return TicketResult(tid, "failed", decision, last_error or "attempts exhausted")

    # --- whole run -------------------------------------------------------------
    def run_all(self, tickets: Iterable[Ticket], dry_run: bool = True, run_id: Optional[str] = None,
                on_result=None) -> RunSummary:
        summary = RunSummary(run_id or new_run_id(), dry_run)
        for ticket in tickets:
            res = self.process(ticket, dry_run=dry_run)
            summary.results.append(res)
            if on_result:
                on_result(res)
        return summary


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]
