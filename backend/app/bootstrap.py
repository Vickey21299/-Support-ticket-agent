"""Wiring shared by the CLI, FastAPI and the eval: build the agent and load tickets."""
import json
from typing import Optional

from app.clients.llm import LLMNotConfigured, get_llm
from app.core.config import Settings, get_settings, make_helpdesk
from app.core.logging import TicketLogger
from app.knowledge.faq import load_knowledge
from app.pipeline.service import TicketAgent, new_run_id
from app.schemas import Ticket
from app.store.journal import Journal


def build_agent(settings: Optional[Settings] = None, *, dry_run: bool = True,
                run_id: Optional[str] = None, with_logger: bool = True) -> tuple[TicketAgent, str]:
    s = settings or get_settings()
    run_id = run_id or new_run_id()
    try:
        llm = get_llm(s)
    except LLMNotConfigured:
        llm = None
    agent = TicketAgent(
        kb=load_knowledge(str(s.faq_path)),
        llm=llm,
        threshold=s.reply_threshold,
        helpdesk=make_helpdesk(s) if s.helpdesk_configured else None,
        journal=None if dry_run else Journal(s.state_db),
        logger=TicketLogger(s.log_dir, run_id, dry_run) if with_logger else None,
        max_post_attempts=s.max_post_attempts,
    )
    return agent, run_id


def load_tickets(source: str, agent: TicketAgent, settings: Optional[Settings] = None,
                 limit: Optional[int] = None) -> list[Ticket]:
    s = settings or get_settings()
    if source == "api":
        if not agent.helpdesk:
            raise RuntimeError("Helpdesk not configured (see .env.example)")
        raw = list(agent.helpdesk.iter_tickets(status="open"))
    elif source == "file":
        raw = json.loads((s.data_dir / "tickets.json").read_text(encoding="utf-8"))
        raw = [t for t in raw if not t.get("handled")]
    else:
        raise ValueError(f"unknown source {source!r}")
    tickets = [Ticket.model_validate(t) for t in raw]
    return tickets[:limit] if limit else tickets
