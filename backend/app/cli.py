"""One-command entry point.

    python -m app.cli run                    dry run on open helpdesk tickets (decides, never posts)
    python -m app.cli run --live             process and POST one decision per open ticket
    python -m app.cli run --source file      dry run on the saved snapshot data/tickets.json
    python -m app.cli triage --id T005       dry run one helpdesk ticket and print the decision
    python -m app.cli eval --tag before      score the agent on the 10 labelled /examples
    python -m app.cli models                 list models the LLM key can use
    python -m app.cli status                 helpdesk status (open / handled) + local journal
    python -m app.cli reset --yes            POST /practice/reset: re-opens all practice tickets
"""
import argparse
import json
import sys

from app.bootstrap import build_agent, load_tickets
from app.clients.llm import LLMNotConfigured
from app.core.config import get_settings, make_helpdesk
from app.core.pricing import cost_per_100, price_for
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
    decided = [r.decision for r in summary.results if r.decision and r.decision.model]
    if decided:
        s = get_settings()
        t_in = sum(d.input_tokens for d in decided)
        t_out = sum(d.output_tokens for d in decided)
        c = cost_per_100(t_in, t_out, len(decided), price_for(s.llm_model, s.price_in_per_m, s.price_out_per_m))
        print(f"tokens: {t_in} in / {t_out} out over {len(decided)} AI-decided tickets"
              + (f" -> about ${c['usd_per_100']} per 100 tickets" if c else ""))
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


def cmd_status(args) -> int:
    st = make_helpdesk().status()
    print({k: st.get(k) for k in ("mode", "open_tickets", "handled_tickets", "live_ends_at")})
    s = get_settings()
    if s.state_db.exists():
        from app.store.journal import Journal
        print("local journal:", Journal(s.state_db).counts())
    return 0


def cmd_reset(args) -> int:
    if not args.yes:
        print("This re-opens ALL practice tickets on the helpdesk. Re-run with --yes to confirm.")
        return 2
    print(make_helpdesk().reset())
    return cmd_status(args)


def cmd_models(args) -> int:
    from app.clients.llm import get_llm
    llm = get_llm(get_settings())
    for name in llm.list_models():
        print(name)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="Roosterly support-ticket agent")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="trace details too: reasons, notes, English back-translation (or LOG_LEVEL=DEBUG)")
    p.add_argument("-q", "--quiet", action="store_true", help="no step-by-step trace, only results")
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

    m = sub.add_parser("models", help="list models available to the configured LLM key")
    m.set_defaults(func=cmd_models)

    st = sub.add_parser("status", help="helpdesk status + local journal counts")
    st.set_defaults(func=cmd_status)

    rs = sub.add_parser("reset", help="re-open all practice tickets (POST /practice/reset)")
    rs.add_argument("--yes", action="store_true", help="confirm")
    rs.set_defaults(func=cmd_reset)

    args = p.parse_args(argv)
    s = get_settings()
    if args.cmd in ("run", "triage", "eval"):
        import os
        from datetime import datetime

        from app.core.trace import setup_trace
        level = "WARNING" if args.quiet else ("DEBUG" if args.verbose else os.environ.get("LOG_LEVEL", "INFO"))
        trace_file = s.log_dir / f"trace-{args.cmd}-{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
        setup_trace(level, trace_file)
        print(f"trace: {trace_file}  (level {level})", file=sys.stderr)
    try:
        return args.func(args)
    except (LLMNotConfigured, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
