"""Read-only: fetch status, labelled examples and all tickets, save them to backend/data/.

Usage:  python fetch_data.py          (same as POST /fetch in the API)
Never posts a decision, so it is safe to run any time.
"""
import sys

from app.clients.helpdesk import HelpdeskError
from app.core.config import get_settings, make_helpdesk
from app.snapshot import fetch_snapshot


def main():
    try:
        summary = fetch_snapshot(make_helpdesk(), get_settings().data_dir)
    except (HelpdeskError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    print("  ", summary["status"])
    print(f"   {summary['examples']} examples, {summary['tickets']} tickets ({summary['open_in_snapshot']} open)")
    for path in summary["files"]:
        print(f"  saved {path}")


if __name__ == "__main__":
    main()
