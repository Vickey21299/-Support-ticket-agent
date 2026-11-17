"""Read-only: fetch status, labelled examples and all tickets, save them to backend/data/.

Usage:  python fetch_data.py
Never posts a decision, so it is safe to run any time.
"""
import json
import sys

from app.clients.helpdesk import HelpdeskError
from app.core.config import get_settings, make_helpdesk


def save(name, obj):
    path = get_settings().data_dir / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  saved {path}")


def main():
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    try:
        client = make_helpdesk()

        print("GET /status")
        status = client.status()
        print("  ", {k: status.get(k) for k in ("mode", "open_tickets", "handled_tickets")})
        save("status.json", status)

        print("GET /examples")
        examples = client.examples()
        save("examples.json", {"examples": examples})
        print(f"   {len(examples)} examples")

        print("GET /tickets?status=all (paginated)")
        tickets = list(client.iter_tickets(status="all"))
        save("tickets.json", tickets)
        print(f"   {len(tickets)} tickets")
    except (HelpdeskError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
