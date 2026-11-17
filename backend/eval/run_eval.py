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
from app.schemas import Ticket

RESULTS_DIR = Path(__file__).resolve().parent / "results"
FIELDS = ["language", "category", "priority", "action"]


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
        "rows": rows,
    }
    _write(report)
    return report


def _write(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = RESULTS_DIR / f"{report['ts'][:19].replace(':', '').replace('-', '')}-{report['tag']}"
    stem.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Eval `{report['tag']}`: {report['ts']}", "",
             f"model `{report['model']}` · threshold {report['threshold']} · n={report['n']} · "
             f"tokens {report['tokens_in']} in / {report['tokens_out']} out", "",
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
    lines += ["", "## Replies (with English back-translation)", ""]
    for r in report["rows"]:
        if r["draft_reply"]:
            lines += [f"**{r['id']}** ({', '.join(r['faq_ids'])})", "", f"> {r['draft_reply']}", "",
                      f"EN: {r['back_translation_en']}", ""]
    stem.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"eval written to {stem}.md")


def main(tag: str = "run", source: str = "file") -> int:
    report = evaluate(tag, source)
    print(json.dumps({k: report[k] for k in ["tag", "accuracy", "all_fields_correct", "safety_violations"]},
                     indent=2))
    return 0
