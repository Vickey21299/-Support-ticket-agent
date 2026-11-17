"""Pipeline service: runs S1-S8 for one ticket and for a whole run. Used by the CLI, FastAPI and the eval.

    analyse(ticket)            S2-S6, pure decision, never posts (used by eval, /triage, dry runs)
    process(ticket)            S1-S8 with the journal and exactly-once posting
    run_all(tickets)           process() for every ticket, returns a summary

Every stage writes a trace line (app/core/trace.py) so a run can be followed step by step.
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
from app.core.trace import detail, step
from app.knowledge.faq import Knowledge
from app.pipeline import classifier, jev_classifier, policy, rules
from app.pipeline.language import detect_language
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


def _secs(t0: float) -> str:
    return f"{time.monotonic() - t0:.1f}s"


class TicketAgent:
    def __init__(self, kb: Knowledge, llm: Optional[LLMClient], threshold: float,
                 helpdesk: Optional[HelpdeskClient] = None, journal: Optional[Journal] = None,
                 logger: Optional[TicketLogger] = None, max_post_attempts: int = 3,
                 decider=None, review_threshold: float = 0.70):
        self.kb = kb
        self.llm = llm
        self.threshold = threshold
        self.helpdesk = helpdesk
        self.journal = journal
        self.logger = logger
        self.max_post_attempts = max_post_attempts
        self.decider = decider                  # optional Jev decision engine (CLASSIFIER=jev)
        self.review_threshold = review_threshold

    # --- S2-S6: decide (no side effects) -----------------------------------
    def analyse(self, ticket: Ticket) -> Decision:
        tid = ticket.id
        step(tid, "S0 ticket", f"subject={ticket.subject[:60]!r} plan={ticket.customer_plan} "
                               f"channel={ticket.channel} body_chars={len(ticket.body)}")

        red = sanitize(ticket.subject, ticket.body)                                          # S2
        step(tid, "S2 sanitize", f"redactions={','.join(red.redaction_types) or '-'} "
                                 f"injection_suspected={red.injection_suspected}")

        lang = detect_language(red.subject, red.body)                                       # S2b
        step(tid, "S2b language", lang.describe())

        rule_result = rules.evaluate(red)                                                    # S3
        step(tid, "S3 rules", f"forced={rule_result.forced_action} floor={rule_result.min_priority} "
                              f"hits={','.join(rule_result.hits)}" if rule_result.hits else "no rule hit")
        if rule_result.forced_action == "close":
            d = policy.close_empty(ticket, red, rule_result)
            step(tid, "S6 policy", "empty ticket -> close (no LLM call)")
            return d
        if self.llm is None:
            raise LLMNotConfigured("No LLM configured")

        jd = None
        if self.decider:                                                                     # S4a (Jev)
            t0 = time.monotonic()
            jd = self.decider.decide(ticket, red)
            step(tid, "S4a jev", " ".join(f"{k}={v}({jd.confidence[k]:.2f})" for k, v in jd.labels.items())
                 + f" needs_review={jd.needs_review:.2f} ({_secs(t0)})")

        t0 = time.monotonic()
        step(tid, "S4 llm", f"calling {getattr(self.llm, 'model', '?')} ...")
        cls, meta = classifier.classify(self.llm, self.kb, ticket, red, rule_result,
                                        upstream=jev_classifier.upstream_hint(jd),
                                        language=lang.code if lang.confident else None)   # S4 / S4b
        if jd:
            cls, meta = jev_classifier.merge(cls, meta, jd)
        step(tid, "S4 llm", f"action={cls.action} lang={cls.language} category={cls.category} "
                            f"conf={cls.confidence:.2f} faq={','.join(cls.faq_ids) or '-'} "
                            f"({_secs(t0)}, {meta.input_tokens} in/{meta.output_tokens} out)")
        step(tid, "S4 facts", f"true: {', '.join(cls.facts.true_facts()) or 'none'}")
        detail(tid, "S4 facts", f"evidence: {cls.facts.evidence}")
        detail(tid, "S4 llm", f"reason: {cls.reason}")
        detail(tid, "S4 llm", f"summary_en: {cls.summary_en}")
        if cls.draft_reply:
            detail(tid, "S4 llm", f"draft_reply ({cls.language}, sent to the customer): {cls.draft_reply}")
        if cls.handoff_note:
            detail(tid, "S4 llm", f"handoff_note (English, for the support team): {cls.handoff_note}")

        ver, vmeta = None, None
        if cls.action == "reply" and rule_result.forced_action is None:                     # S5
            t0 = time.monotonic()
            ver, vmeta = classifier.verify(self.llm, self.kb, red, cls,
                                           lang.code if lang.confident else None)
            step(tid, "S5 verify", f"passed={ver.passed} lang={ver.language_detected} "
                                   f"answers_question={ver.answers_question} "
                                   f"unsupported={len(ver.unsupported_claims)} violations={len(ver.violations)} "
                                   f"({_secs(t0)})")
            detail(tid, "S5 verify", f"back_translation_en (only for you to check, NOT sent): {ver.back_translation_en}")
            for c in ver.unsupported_claims:
                detail(tid, "S5 verify", f"unsupported claim: {c}")
            for v in ver.violations:
                detail(tid, "S5 verify", f"violation: {v}")
        else:
            step(tid, "S5 verify", "skipped (not a reply)")

        decision = policy.decide(ticket, red, rule_result, cls, meta, ver, self.kb, self.threshold,
                                 self.review_threshold, lang)                               # S6
        if vmeta:
            decision.input_tokens += vmeta.input_tokens
            decision.output_tokens += vmeta.output_tokens
        changed = f" (model said {decision.llm_action})" if decision.llm_action != decision.action else ""
        step(tid, "S6 policy", f"FINAL action={decision.action}{changed} priority={decision.priority} "
                               f"({decision.priority_basis}) language={decision.language} "
                               f"({decision.language_basis}) conf={decision.confidence:.2f}")
        for n in decision.policy_notes:
            step(tid, "S6 policy", f"escalated because: {n}")
        return decision

    # --- S1-S8 for one ticket -----------------------------------------------
    def process(self, ticket: Ticket, dry_run: bool = True) -> TicketResult:
        start = time.monotonic()
        result = self._process(ticket, dry_run)
        if self.logger:
            self.logger.log(ticket.id, result.outcome, result.decision,
                            int((time.monotonic() - start) * 1000), result.error)
        step(ticket.id, "S8 done", f"outcome={result.outcome} ({_secs(start)})"
             + (f" error={result.error}" if result.error else ""))
        return result

    def _process(self, ticket: Ticket, dry_run: bool) -> TicketResult:
        if dry_run:
            try:
                return TicketResult(ticket.id, "dry_run", self.analyse(ticket))
            except (LLMError, LLMNotConfigured) as exc:
                step(ticket.id, "S4 llm", f"FAILED -> deferred: {exc}")
                return TicketResult(ticket.id, "deferred", error=str(exc))

        if not (self.helpdesk and self.journal):
            raise RuntimeError("live processing needs a helpdesk client and a journal")

        row = self.journal.get(ticket.id)                                 # S1
        if row and row["status"] == "completed":
            # We only get here for tickets the server lists as OPEN, so it was re-opened (practice reset).
            step(ticket.id, "S1 journal", "completed earlier but open on server (reset) -> archive, start fresh")
            self.journal.archive(ticket.id)
            row = None

        if row and row["decision"]:
            decision = row["decision"]        # crash recovery: replay the stored decision, never re-generate
            step(ticket.id, "S1 journal", f"found stored decision ({row['status']}) -> replay "
                                          f"action={decision.action}, no new LLM call")
            if self._remote_handled(ticket.id):
                step(ticket.id, "S7 post", "server already shows it handled -> reconciled, no POST")
                self.journal.complete(ticket.id, "reconciled")
                return TicketResult(ticket.id, "reconciled", decision)
        else:
            step(ticket.id, "S1 journal", "new ticket")
            try:
                decision = self.analyse(ticket)
            except (LLMError, LLMNotConfigured) as exc:
                step(ticket.id, "S4 llm", f"FAILED -> deferred, left open for next run: {exc}")
                return TicketResult(ticket.id, "deferred", error=str(exc))   # leave open, retry next run
            self.journal.plan(decision)                                  # S7a persist before posting
            step(ticket.id, "S7a persist", "decision saved as 'planned' before posting")

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
        for attempt in range(1, self.max_post_attempts + 1):
            self.journal.attempt(tid)           # recorded for auditing; the limit is per run
            step(tid, "S7b post", f"POST /tickets/{tid}/{decision.action} (attempt {attempt})")
            try:
                self.helpdesk.act(tid, decision.action, decision.api_payload())
                self.journal.complete(tid, "posted")
                step(tid, "S7b post", "OK -> completed")
                return TicketResult(tid, "posted", decision)
            except AlreadyHandled:
                self.journal.complete(tid, "already_handled")
                step(tid, "S7b post", "409 already handled -> completed, not retried")
                return TicketResult(tid, "already_handled", decision)
            except HelpdeskError as exc:
                last_error = str(exc)
                step(tid, "S7b post", f"HTTP {exc.status}: {str(exc)[:120]}")
                if exc.status == 503:
                    break                       # nothing saved; client already retried. Replay next run.
                if exc.status < 500:
                    break                       # 4xx (e.g. 422): our request is wrong, retrying won't help
                # other 5xx: ambiguous -> check remote state below
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"   # ambiguous: the POST may have been saved
                step(tid, "S7b post", f"{last_error[:120]} -> checking server state")

            if self._remote_handled(tid):
                self.journal.complete(tid, "reconciled")
                step(tid, "S7b post", "server shows it handled -> reconciled, no second POST")
                return TicketResult(tid, "reconciled", decision)

        self.journal.fail(tid, last_error or "attempts exhausted")
        step(tid, "S7b post", "FAILED -> stored decision will be replayed next run")
        return TicketResult(tid, "failed", decision, last_error or "attempts exhausted")

    # --- whole run -------------------------------------------------------------
    def run_all(self, tickets: Iterable[Ticket], dry_run: bool = True, run_id: Optional[str] = None,
                on_result=None) -> RunSummary:
        summary = RunSummary(run_id or new_run_id(), dry_run)
        tickets = list(tickets)
        for i, ticket in enumerate(tickets, 1):
            step(ticket.id, "----", f"ticket {i}/{len(tickets)}")
            res = self.process(ticket, dry_run=dry_run)
            summary.results.append(res)
            if on_result:
                on_result(res)
        return summary


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]
