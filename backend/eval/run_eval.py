"""Eval on the 10 labelled examples from GET /examples.

Labels come from the helpdesk (written by Nordavo), never from the model under test.
Writes eval/results/<timestamp>-<tag>.json and .md, including an English back-translation of every
reply so a non-Dutch reader can judge the drafts.

    python -m app.cli eval --tag before
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.bootstrap import build_agent
from app.clients.llm import LLMNotConfigured
from app.core.config import get_settings, make_helpdesk
from app.core.pricing import cost_per_100, price_for
from app.schemas import Ticket

RESULTS_DIR = Path(__file__).resolve().parent / "results"
EXPECTED_FACTS = Path(__file__).resolve().parent / "expected_facts.json"
FIELDS = ["language", "category", "priority", "action"]
FACT_NAMES = ["many_users_blocked", "security_or_legal_risk", "money_or_contract_dispute", "privacy_request",
              "something_broken", "cosmetic_only", "others_unaffected", "fix_in_help_centre",
              "alternative_workflow_available", "workaround_available"]
BROKEN_ONLY = {"others_unaffected", "fix_in_help_centre", "alternative_workflow_available", "workaround_available"}


def load_expected_facts() -> dict:
    """Human-approved expected facts per example (see expected_facts.json); {} if not present."""
    if not EXPECTED_FACTS.exists():
        return {}
    return json.loads(EXPECTED_FACTS.read_text(encoding="utf-8")).get("examples", {})


def compare_facts(expected: dict, got: dict | None) -> dict[str, bool]:
    """Per fact: did the model extract it as expected? workaround only counts when something is broken."""
    if not expected:
        return {}
    got = got or {}
    from app.schemas import PriorityFacts
    expected = {**expected, "workaround_available": PriorityFacts(**expected).workaround_available}  # derived, like the agent
    out = {}
    for name in FACT_NAMES:
        if name in BROKEN_ONLY:
            if not expected.get("something_broken"):
                continue
            # "established or not": true vs. not true (false and null both mean "not shown")
            out[name] = bool(got.get(name)) == bool(expected.get(name))
            continue
        out[name] = got.get(name) == expected.get(name)
    return out


def load_examples(source: str) -> list[dict]:
    if source == "api":
        return make_helpdesk().examples()
    data = json.loads((get_settings().data_dir / "examples.json").read_text(encoding="utf-8"))
    return data.get("examples", data) if isinstance(data, dict) else data


def safety_violations(pred_action: str, label_action: str) -> list[str]:
    v = []
    if pred_action == "reply" and label_action != "reply":
        v.append(f"replied where label is {label_action}")
    if pred_action == "close" and label_action != "close":
        v.append(f"closed where label is {label_action}")
    return v


def evaluate(tag: str = "run", source: str = "file") -> dict:
    agent, run_id = build_agent(dry_run=True, run_id=f"eval-{tag}")
    if agent.llm is None:
        raise LLMNotConfigured("The eval needs an LLM (set LLM_PROVIDER in .env)")
    rows = []
    expected_facts = load_expected_facts()
    for ex in load_examples(source):
        label = ex["label"]
        res = agent.process(Ticket.model_validate(ex), dry_run=True)
        d = res.decision
        pred = {f: getattr(d, f) for f in FIELDS} if d else {f: None for f in FIELDS}
        rows.append({
            "id": ex["id"],
            "subject": ex.get("subject"),
            "label": {f: label[f] for f in FIELDS},
            "pred": pred,
            "correct": {f: pred[f] == label[f] for f in FIELDS},
            "safety": safety_violations(pred["action"], label["action"]) if d else ["no decision"],
            "label_reason": label.get("reason"),
            "pred_reason": d.reason if d else res.error,
            "policy_notes": d.policy_notes if d else [],
            "faq_ids": d.faq_ids if d else [],
            "draft_reply": d.draft_reply if d else None,
            "back_translation_en": d.verification.back_translation_en if d and d.verification else None,
            "tokens_in": d.input_tokens if d else 0,
            "tokens_out": d.output_tokens if d else 0,
            "decider_tokens_in": d.decider_input_tokens if d else 0,
            "facts": d.facts.model_dump() if d and d.facts else None,
            "priority_basis": d.priority_basis if d else None,
            "facts_correct": compare_facts((expected_facts.get(ex["id"]) or {}).get("facts", {}),
                                           d.facts.model_dump() if d and d.facts else None),
        })

    n = len(rows)
    acc = {f: sum(r["correct"][f] for r in rows) / n for f in FIELDS}
    report = {
        "tag": tag,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": getattr(agent.llm, "model", None),
        "threshold": agent.threshold,
        "n": n,
        "accuracy": acc,
        "all_fields_correct": sum(all(r["correct"].values()) for r in rows) / n,
        "safety_violations": sum(bool(r["safety"]) for r in rows),
        "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_out": sum(r["tokens_out"] for r in rows),
        "decider_tokens_in": sum(r["decider_tokens_in"] for r in rows),
        "fact_accuracy": _fact_accuracy(rows),
        "classifier": get_settings().classifier,
        "rows": rows,
    }
    s = get_settings()
    report["cost"] = cost_per_100(report["tokens_in"], report["tokens_out"], n,
                                  price_for(s.llm_model, s.price_in_per_m, s.price_out_per_m))
    _write(report)
    return report


def _fact_accuracy(rows: list[dict]) -> dict | None:
    checks = [(name, ok) for r in rows for name, ok in (r.get("facts_correct") or {}).items()]
    if not checks:
        return None
    per = {}
    for name, ok in checks:
        per.setdefault(name, []).append(ok)
    return {"overall": sum(ok for _, ok in checks) / len(checks),
            **{name: sum(v) / len(v) for name, v in per.items()}}


def _write(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = RESULTS_DIR / f"{report['ts'][:19].replace(':', '').replace('-', '')}-{report['tag']}"
    Path(f"{stem}.json").write_text(  # not with_suffix: tags may contain dots (3.5)
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Eval `{report['tag']}`: {report['ts']}", "",
             f"classifier `{report['classifier']}` · model `{report['model']}` · threshold {report['threshold']} · "
             f"n={report['n']} · tokens {report['tokens_in']} in / {report['tokens_out']} out"
             + (f" · Jev {report['decider_tokens_in']} in" if report["decider_tokens_in"] else ""), "",
             "| metric | score |", "|---|---|"]
    lines += [f"| {f} | {report['accuracy'][f]:.0%} |" for f in FIELDS]
    lines += [f"| all four correct | {report['all_fields_correct']:.0%} |",
              f"| **safety violations** | **{report['safety_violations']}** |", "",
              "| id | label (lang/cat/prio/action) | predicted | ok | safety |", "|---|---|---|---|---|"]
    for r in report["rows"]:
        lab = "/".join(str(r["label"][f]) for f in FIELDS)
        pred = "/".join(str(r["pred"][f]) for f in FIELDS)
        ok = "".join("✓" if r["correct"][f] else "✗" for f in FIELDS)
        lines.append(f"| {r['id']} | {lab} | {pred} | {ok} | {'; '.join(r['safety'])} |")
    fa = report.get("fact_accuracy")
    if fa:
        lines += ["", "## Priority facts (extracted by the model vs. approved expected facts)", "",
                  f"overall fact accuracy: **{fa['overall']:.0%}**  ·  "
                  + "  ·  ".join(f"{k} {v:.0%}" for k, v in fa.items() if k != "overall"), "",
                  "| id | facts the model said are true | priority basis | wrong facts |", "|---|---|---|---|"]
        for r in report["rows"]:
            f = r.get("facts") or {}
            true = [k for k in FACT_NAMES if k not in BROKEN_ONLY and f.get(k)]
            if f.get("something_broken"):
                true.append(f"workaround={f.get('workaround_available')} (fix={f.get('fix_in_help_centre')}"
                            f"/{f.get('fix_section')}, alt={f.get('alternative_workflow_available')}, "
                            f"others_unaffected={f.get('others_unaffected')})")
            wrong = [k for k, ok in (r.get("facts_correct") or {}).items() if not ok]
            lines.append(f"| {r['id']} | {', '.join(true) or '-'} | {r.get('priority_basis') or '-'} | "
                         f"{', '.join(wrong) or '-'} |")
    c = report.get("cost")
    if c:
        lines += ["", "## Cost per 100 tickets", "",
                  f"{c['tokens_in_per_100']:,} input tokens x ${c['usd_per_1m_in']}/1M + "
                  f"{c['tokens_out_per_100']:,} output tokens x ${c['usd_per_1m_out']}/1M "
                  f"= **${c['usd_per_100']} (about EUR {c['eur_per_100']})** per 100 tickets, "
                  f"scaled from {c['tickets_measured']} measured tickets (writing LLM; Jev tokens listed separately)."]
    lines += ["", "## Replies (with English back-translation)", ""]
    for r in report["rows"]:
        if r["draft_reply"]:
            lines += [f"**{r['id']}** ({', '.join(r['faq_ids'])})", "", f"> {r['draft_reply']}", "",
                      f"EN: {r['back_translation_en']}", ""]
    Path(f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"eval written to {stem}.md")


def main(tag: str = "run", source: str = "file") -> int:
    report = evaluate(tag, source)
    print(json.dumps({k: report.get(k) for k in ["tag", "accuracy", "all_fields_correct", "safety_violations",
                                                  "fact_accuracy", "cost"]},
                     indent=2))
    return 0
