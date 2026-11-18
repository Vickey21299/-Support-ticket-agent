"""Language-detection eval: scores app/pipeline/language.py alone. No LLM, no API calls, no cost, ~5 s.

    python -m app.cli langeval

Sources:
  1. the 10 labelled /examples (Nordavo's `label.language`, from data/examples.json; run fetch_data.py first)
  2. the 30 practice tickets (text from data/tickets.json), expected language in language_cases.json
     (`practice_labels`, written by reading the tickets, not from the detector)
  3. eval/language_cases.json: hand-written supported, tricky, short and unsupported-language cases

Each case gets one outcome:
  correct     supported: detected the expected language, confident  | unsupported: flagged as that language
  safe_miss   detector unsure, or unsupported flagged as another non-supported language -> no reply, a human answers
  WRONG       confident in the wrong supported language -> the agent could reply in the wrong language
WRONG is the number that must stay 0 (like safety violations in the main eval).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.pipeline.language import detect_language

HERE = Path(__file__).resolve().parent
CASES = HERE / "language_cases.json"
RESULTS_DIR = HERE / "results"


def load_cases() -> tuple[list[dict], bool]:
    cases, approved = [], False
    ex_path = get_settings().data_dir / "examples.json"
    if ex_path.exists():
        data = json.loads(ex_path.read_text(encoding="utf-8"))
        for e in data.get("examples", data):
            lang = (e.get("label") or {}).get("language")
            if lang:
                cases.append({"id": e["id"], "group": "examples (Nordavo labels)", "subject": e.get("subject", ""),
                              "body": e.get("body", ""), "expected": lang})
    if CASES.exists():
        data = json.loads(CASES.read_text(encoding="utf-8"))
        approved = bool(data.get("approved"))
        tk_path = get_settings().data_dir / "tickets.json"
        if tk_path.exists() and data.get("practice_labels"):
            for t in json.loads(tk_path.read_text(encoding="utf-8")):
                if t["id"] in data["practice_labels"]:
                    cases.append({"id": t["id"], "group": "practice (30 tickets)", "subject": t.get("subject", ""),
                                  "body": t.get("body", ""), "expected": data["practice_labels"][t["id"]]})
        cases += data["cases"]
    return cases, approved


def score_case(case: dict) -> dict:
    r = detect_language(case["subject"], case["body"])
    exp = case["expected"]
    if exp == "none":                       # empty ticket: no language to detect, never confident
        outcome = "correct" if not r.code else ("safe_miss" if not r.confident else "WRONG")
    elif exp.startswith("other:"):
        if r.unsupported == exp.split(":", 1)[1]:
            outcome = "correct"
        elif r.unsupported or not r.confident:
            outcome = "safe_miss"
        else:
            outcome = "WRONG"
    else:
        if r.confident and r.code == exp:
            outcome = "correct"
        elif not r.confident:
            outcome = "safe_miss"
        else:
            outcome = "WRONG"
    return {"id": case["id"], "group": case["group"], "expected": exp, "detected": r.describe(),
            "outcome": outcome, "why": case.get("why", "")}


def evaluate(write: bool = True) -> dict:
    cases, approved = load_cases()
    rows = [score_case(c) for c in cases]
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["group"], {"n": 0, "correct": 0, "safe_miss": 0, "WRONG": 0})
        g["n"] += 1
        g[r["outcome"]] += 1
    total = {k: sum(g[k] for g in groups.values()) for k in ("n", "correct", "safe_miss", "WRONG")}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "cases_approved": approved,
              "total": total, "groups": groups, "rows": rows}
    if write:
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        (RESULTS_DIR / f"{stamp}-language.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (RESULTS_DIR / f"{stamp}-language.md").write_text(to_markdown(report), encoding="utf-8")
        report["files"] = [str(RESULTS_DIR / f"{stamp}-language.{ext}") for ext in ("md", "json")]
    return report


def to_markdown(rep: dict) -> str:
    t = rep["total"]
    lines = [f"# Language-detection eval ({rep['generated_at'][:19]}Z)", "",
             f"No LLM, no API cost. Hand-written cases approved: **{rep['cases_approved']}**.", "",
             "| group | n | correct | safe miss (unsure -> human) | WRONG |", "|---|---|---|---|---|"]
    for name, g in rep["groups"].items():
        lines.append(f"| {name} | {g['n']} | {g['correct']} | {g['safe_miss']} | {g['WRONG']} |")
    lines += [f"| **total** | **{t['n']}** | **{t['correct']}** | **{t['safe_miss']}** | **{t['WRONG']}** |", "",
              "| id | group | expected | detected | outcome | note |", "|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        lines.append(f"| {r['id']} | {r['group']} | {r['expected']} | {r['detected']} | {r['outcome']} | {r['why']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    rep = evaluate()
    t = rep["total"]
    for name, g in rep["groups"].items():
        print(f"  {name:28} {g['correct']}/{g['n']} correct, {g['safe_miss']} safe miss, {g['WRONG']} WRONG")
    print(f"  {'total':28} {t['correct']}/{t['n']} correct, {t['safe_miss']} safe miss, {t['WRONG']} WRONG")
    if not rep["cases_approved"]:
        print("  note: eval/language_cases.json is not approved yet (set approved=true after review)")
    for f in rep.get("files", []):
        print(f"  saved {f}")
    return 1 if t["WRONG"] else 0
