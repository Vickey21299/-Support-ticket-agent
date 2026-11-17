"""Check that the priority table turns the expected facts into Nordavo's labelled priority.

    python -m eval.check_expected_facts

No model is called. This only checks the facts in eval/expected_facts.json against the labels in
data/examples.json, so you can review the facts and the table before they are used in the agent.
"""
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def calculate_priority(f: dict) -> str:
    from app.pipeline.priority import calculate_priority as engine
    from app.schemas import PriorityFacts
    return engine(PriorityFacts(**f)).priority


def main() -> int:
    facts = json.loads((BACKEND / "eval" / "expected_facts.json").read_text(encoding="utf-8"))
    examples = json.loads((BACKEND / "data" / "examples.json").read_text(encoding="utf-8"))["examples"]
    labels = {e["id"]: e for e in examples}
    print(f"status: {facts['status']}\n")
    ok = 0
    for ex_id, item in facts["examples"].items():
        true_facts = [k for k, v in item["facts"].items() if v is True]
        calc = calculate_priority(item["facts"])
        nordavo = labels[ex_id]["label"]["priority"]
        match = calc == nordavo
        ok += match
        print(f"{ex_id}  {labels[ex_id]['body'][:55]:<57} facts={','.join(true_facts) or '-':<45} "
              f"table={calc} nordavo={nordavo} {'OK' if match else 'MISMATCH'}")
    print(f"\n{ok}/{len(facts['examples'])} priorities match Nordavo's labels")
    return 0 if ok == len(facts["examples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
