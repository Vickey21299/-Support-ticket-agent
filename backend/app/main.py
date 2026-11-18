"""FastAPI layer: thin HTTP wrapper around the same pipeline the CLI uses.

    uvicorn app.main:app --reload     (from backend/)

Every endpoint is a dry run unless dry_run=false is passed explicitly.
GET /status and POST /fetch only read. POST /practice/reset re-opens all practice tickets and
refuses unless confirm=true is passed (same as `cli reset --yes`).
"""
import threading
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException

from app.bootstrap import build_agent, load_tickets
from app.clients.helpdesk import HelpdeskError
from app.clients.llm import LLMNotConfigured
from app.core.config import get_settings, make_helpdesk
from app.schemas import Decision, Ticket
from app.snapshot import fetch_snapshot

app = FastAPI(title="Roosterly ticket agent", version="0.1.0")

_runs: dict[str, dict] = {}
_live_lock = threading.Lock()   # one live run at a time


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "helpdesk_configured": s.helpdesk_configured,
            "llm_configured": s.llm_configured, "llm_provider": s.llm_provider or None,
            "reply_threshold": s.reply_threshold}


def _helpdesk():
    try:
        return make_helpdesk()
    except RuntimeError as exc:          # helpdesk keys missing from .env
        raise HTTPException(503, str(exc))


def _helpdesk_status(client) -> dict:
    st = client.status()
    out = {k: st.get(k) for k in ("mode", "open_tickets", "handled_tickets", "live_ends_at")}
    s = get_settings()
    if s.state_db.exists():
        from app.store.journal import Journal
        out["local_journal"] = Journal(s.state_db).counts()
    return out


@app.get("/status")
def status():
    """Helpdesk open/handled counts plus the local journal. Read-only."""
    try:
        return _helpdesk_status(_helpdesk())
    except HelpdeskError as exc:
        raise HTTPException(exc.status, exc.payload)


@app.get("/tickets")
def list_tickets(status: str = "all"):
    """Every ticket (status=all) or only open ones (status=open), with its handled state. Read-only."""
    if status not in ("all", "open"):
        raise HTTPException(400, "status must be open or all")
    try:
        tickets = list(_helpdesk().iter_tickets(status=status))
    except HelpdeskError as exc:
        raise HTTPException(exc.status, exc.payload)
    rows = [{"id": t["id"], "subject": t.get("subject"), "handled": t.get("handled")} for t in tickets]
    return {"count": len(rows), "handled": sum(1 for r in rows if r["handled"]), "tickets": rows}


@app.get("/tickets/{ticket_id}")
def ticket_details(ticket_id: str):
    """One ticket as the helpdesk has it, plus the decision this agent stored for it (reply text, reason, ...).

    The helpdesk only keeps the action and time; the full decision lives in the local journal.
    Read-only. After a practice reset the journal keeps the old decision until the ticket is processed again.
    """
    try:
        helpdesk = _helpdesk().ticket(ticket_id)
    except HelpdeskError as exc:
        raise HTTPException(exc.status, exc.payload)
    s = get_settings()
    entry = None
    if s.state_db.exists():
        from app.store.journal import Journal
        row = Journal(s.state_db).get(ticket_id)
        if row:
            entry = {k: row[k] for k in ("status", "outcome", "attempts", "last_error", "updated_at")}
            entry["decision"] = row["decision"].model_dump(mode="json") if row["decision"] else None
    return {"helpdesk": helpdesk, "agent_journal": entry}


@app.post("/fetch")
def fetch():
    """Read-only snapshot (status, examples, all tickets) to backend/data/, like `python fetch_data.py`."""
    try:
        return fetch_snapshot(_helpdesk(), get_settings().data_dir)
    except HelpdeskError as exc:
        raise HTTPException(exc.status, exc.payload)


@app.post("/practice/reset")
def practice_reset(confirm: bool = False):
    """Re-open ALL practice tickets (POST /practice/reset on the helpdesk). Needs confirm=true."""
    if not confirm:
        raise HTTPException(400, "This re-opens ALL practice tickets. Pass confirm=true to proceed.")
    if not _live_lock.acquire(blocking=False):
        raise HTTPException(409, "a live run is in progress; reset after it finishes")
    try:
        client = _helpdesk()
        result = client.reset()
        return {"reset": result, "status": _helpdesk_status(client)}
    except HelpdeskError as exc:
        raise HTTPException(exc.status, exc.payload)
    finally:
        _live_lock.release()


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
