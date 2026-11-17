"""FastAPI layer: thin HTTP wrapper around the same pipeline the CLI uses.

    uvicorn app.main:app --reload     (from backend/)

Every endpoint is a dry run unless dry_run=false is passed explicitly.
"""
import threading
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException

from app.bootstrap import build_agent, load_tickets
from app.clients.helpdesk import HelpdeskError
from app.clients.llm import LLMNotConfigured
from app.core.config import get_settings
from app.schemas import Decision, Ticket

app = FastAPI(title="Roosterly ticket agent", version="0.1.0")

_runs: dict[str, dict] = {}
_live_lock = threading.Lock()   # one live run at a time


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "helpdesk_configured": s.helpdesk_configured,
            "llm_configured": s.llm_configured, "llm_provider": s.llm_provider or None,
            "reply_threshold": s.reply_threshold}


@app.post("/triage", response_model=Decision)
def triage(ticket: Ticket):
    """Decide on a ticket given in the body. Never posts anything."""
    agent, _ = build_agent(dry_run=True)
    res = agent.process(ticket, dry_run=True)
    if not res.decision:
        raise HTTPException(503, res.error or "could not decide")
    return res.decision


@app.post("/triage/{ticket_id}")
def triage_by_id(ticket_id: str, dry_run: bool = True):
    agent, _ = build_agent(dry_run=dry_run)
    if not agent.helpdesk:
        raise HTTPException(503, "helpdesk not configured")
    try:
        ticket = Ticket.model_validate(agent.helpdesk.ticket(ticket_id))
    except HelpdeskError as exc:
        raise HTTPException(exc.status, exc.payload)
    res = agent.process(ticket, dry_run=dry_run)
    return {"ticket_id": ticket_id, "outcome": res.outcome, "error": res.error,
            "decision": res.decision.model_dump() if res.decision else None}


def _do_run(run_id: str, dry_run: bool, source: str, limit: Optional[int]):
    state = _runs[run_id]
    try:
        agent, _ = build_agent(dry_run=dry_run, run_id=run_id)
        tickets = load_tickets(source, agent, limit=limit)
        state["total"] = len(tickets)

        def on_result(res):
            state["results"].append({"ticket_id": res.ticket_id, "outcome": res.outcome,
                                     "action": res.decision.action if res.decision else None,
                                     "error": res.error})
        summary = agent.run_all(tickets, dry_run=dry_run, run_id=run_id, on_result=on_result)
        state.update(status="finished", counts=summary.counts, log=str(agent.logger.path))
    except Exception as exc:  # report, don't crash the server
        state.update(status="error", error=str(exc))
    finally:
        if not dry_run:
            _live_lock.release()


@app.post("/runs", status_code=202)
def start_run(background: BackgroundTasks, dry_run: bool = True, source: str = "api", limit: Optional[int] = None):
    if not dry_run and not _live_lock.acquire(blocking=False):
        raise HTTPException(409, "a live run is already in progress")
    from app.pipeline.service import new_run_id
    run_id = new_run_id()
    _runs[run_id] = {"run_id": run_id, "dry_run": dry_run, "status": "running", "results": []}
    background.add_task(_do_run, run_id, dry_run, source, limit)
    return {"run_id": run_id, "status_url": f"/runs/{run_id}"}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in _runs:
        raise HTTPException(404, "unknown run")
    return _runs[run_id]


@app.post("/eval")
def run_eval(tag: str = "api"):
    from eval.run_eval import evaluate
    try:
        return evaluate(tag=tag, source="file")
    except LLMNotConfigured as exc:
        raise HTTPException(503, str(exc))
