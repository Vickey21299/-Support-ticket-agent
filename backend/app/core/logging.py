"""S8 Log [CODE]: exactly one JSONL line per processed ticket.

No ticket body and no draft text is written; every string is passed through the payment-data mask
anyway, as a second safety net.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.pipeline.redact import mask_text
from app.schemas import Decision


def _mask(obj):
    if isinstance(obj, str):
        return mask_text(obj)[0]
    if isinstance(obj, list):
        return [_mask(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _mask(v) for k, v in obj.items()}
    return obj


class TicketLogger:
    def __init__(self, log_dir: Path, run_id: str, dry_run: bool):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{'dryrun' if dry_run else 'run'}-{run_id}.jsonl"
        self.run_id = run_id
        self.dry_run = dry_run
        self._lock = threading.Lock()

    def log(self, ticket_id: str, outcome: str, decision: Optional[Decision] = None,
            latency_ms: int = 0, error: Optional[str] = None) -> dict:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "ticket_id": ticket_id,
            "outcome": outcome,
            "latency_ms": latency_ms,
        }
        if decision:
            v = decision.verification
            line.update({
                "action": decision.action,
                "llm_action": decision.llm_action,
                "language": decision.language,
                "category": decision.category,
                "priority": decision.priority,
                "confidence": round(decision.confidence, 3) if decision.confidence is not None else None,
                "faq_ids": decision.faq_ids,
                "rule_hits": decision.rule_hits,
                "flags": decision.flags,
                "policy_notes": decision.policy_notes,
                "verified": v.passed if v else None,
                "model": decision.model,
                "tokens_in": decision.input_tokens,
                "tokens_out": decision.output_tokens,
                "decider_tokens_in": decision.decider_input_tokens,
                "needs_review": round(decision.needs_review, 3) if decision.needs_review is not None else None,
                "facts_true": decision.facts.true_facts() if decision.facts else None,
                "priority_basis": decision.priority_basis,
                "language_basis": decision.language_basis,
                "reason": decision.reason,
            })
        if error:
            line["error"] = error[:300]
        line = _mask(line)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return line
