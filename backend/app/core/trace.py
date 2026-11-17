"""Human-readable step-by-step trace of the pipeline (what happens at each stage, per ticket).

    10:42:01  T001  S2 sanitize    redactions=- injection=False
    10:42:01  T001  S3 rules       no rule hit
    10:42:15  T001  S4 llm         action=reply category=question priority=P3 conf=0.95 faq=F01 (13.8s, 2248 in/306 out)

INFO shows one line per stage; DEBUG (-v / LOG_LEVEL=DEBUG) adds the reason, notes and the English
back-translation. Goes to the terminal and to logs/trace-<run>.log. The ticket body and the draft text
are never traced, and every line passes through the payment-data mask.
This is separate from the JSONL decision log (core/logging.py), which stays one line per ticket.
"""
import logging
import sys
from pathlib import Path
from typing import Optional

from app.pipeline.redact import mask_text

log = logging.getLogger("agent")


class _MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_text(record.getMessage())[0]
        record.args = ()
        return True


def setup_trace(level: str = "INFO", file: Optional[Path] = None) -> None:
    log.handlers.clear()
    log.setLevel(getattr(logging, level.upper(), logging.INFO))
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if file:
        file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(file, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(_MaskFilter())
        log.addHandler(h)


def step(ticket_id: str, stage: str, message: str, level: int = logging.INFO) -> None:
    log.log(level, f"{ticket_id:<6} {stage:<13} {message}")


def detail(ticket_id: str, stage: str, message: str) -> None:
    step(ticket_id, stage, message, logging.DEBUG)
