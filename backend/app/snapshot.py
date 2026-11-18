"""Read-only snapshot of the helpdesk: status, labelled examples and all tickets -> backend/data/.

Used by `python fetch_data.py` and by `POST /fetch` in the API. Never posts anything.
"""
import json
from pathlib import Path


def save_json(data_dir: Path, name: str, obj) -> Path:
    path = data_dir / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def fetch_snapshot(client, data_dir: Path) -> dict:
    """GET /status, /examples and /tickets?status=all, save them, and return a summary."""
    data_dir.mkdir(parents=True, exist_ok=True)
    status = client.status()
    examples = client.examples()
    tickets = list(client.iter_tickets(status="all"))
    files = [save_json(data_dir, "status.json", status),
             save_json(data_dir, "examples.json", {"examples": examples}),
             save_json(data_dir, "tickets.json", tickets)]
    return {
        "status": {k: status.get(k) for k in ("mode", "open_tickets", "handled_tickets", "live_ends_at")},
        "examples": len(examples),
        "tickets": len(tickets),
        "open_in_snapshot": sum(1 for t in tickets if not t.get("handled")),
        "files": [str(p) for p in files],
    }
