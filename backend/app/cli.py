"""One-command entry point.

    python -m app.cli run                    dry run on open helpdesk tickets (decides, never posts)
    python -m app.cli run --live             process and POST one decision per open ticket
    python -m app.cli run --source file      dry run on the saved snapshot data/tickets.json
    python -m app.cli triage --id T005       dry run one helpdesk ticket and print the decision
    python -m app.cli eval --tag before      score the agent on the 10 labelled /examples
"""
import argparse
import json
import sys

from app.bootstrap import build_agent, load_tickets
from app.core.config import get_settings
from app.schemas import Ticket


def _print_result(res):
    d = res.decision
    if d:
        print(f"{res.ticket_id:6} {res.outcome:16} {d.action:8} {d.language} {d.category:16} {d.priority} "
              f"conf={d.confidence if d.confidence is not None else '-':<5} {','.join(d.rule_hits)}")
    else:
        print(f"{res.ticket_id:6} {res.outcome:16} {res.error or ''}")


def cmd_run(args) -> int:
    dry = not args.live
    if args.live and args.source != "api":
        print("--live only works with --source api", file=sys.stderr)
        return 2
    agent, run_id = build_agent(dry_run=dry)
    if agent.llm is None:
        print("WARNING: no LLM configured; only empty tickets can be decided, the rest is deferred.\n")
    tickets = load_tickets(args.source, agent, limit=args.limit)
    print(f"run {run_id}  mode={'LIVE' if not dry else 'dry-run'}  tickets={len(tickets)}\n")
    summary = agent.run_all(tickets, dry_run=dry, run_id=run_id, on_result=_print_result)
    print(f"\nsummary: {summary.counts}")
    print(f"log: {agent.logger.path}")
    if agent.journal:
        print(f"journal: {agent.journal.counts()}")
    return 1 if summary.counts.get("failed") else 0


def cmd_triage(args) -> int:
    agent, _ = build_agent(dry_run=True, with_logger=False)
    if args.id:
        ticket = Ticket.model_validate(agent.helpdesk.ticket(args.id))
    else:
        ticket = Ticket(id="ADHOC", subject=args.subject or "", body=args.body or "")
    res = agent.process(ticket, dry_run=True)
    print(json.dumps(res.decision.model_dump() if res.decision else {"outcome": res.outcome, "error": res.error},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_eval(args) -> int:
    from eval.run_eval import main as eval_main
    return eval_main(tag=args.tag, source=args.source)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="Roosterly support-ticket agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="process all open tickets")
    r.add_argument("--live", action="store_true", help="really POST decisions (default: dry run)")
    r.add_argument("--source", choices=["api", "file"], default="api")
    r.add_argument("--limit", type=int)
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("triage", help="dry-run a single ticket")
    t.add_argument("--id")
    t.add_argument("--subject")
    t.add_argument("--body")
    t.set_defaults(func=cmd_triage)

    e = sub.add_parser("eval", help="score on the labelled examples")
    e.add_argument("--tag", default="run")
    e.add_argument("--source", choices=["api", "file"], default="file")
    e.set_defaults(func=cmd_eval)

    args = p.parse_args(argv)
    get_settings()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
