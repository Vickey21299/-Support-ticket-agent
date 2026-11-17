# Roosterly support-ticket agent

Reads every open ticket from the Roosterly helpdesk and posts exactly one decision per ticket: a `reply` in the
customer's language (from `faq.md` only), a `handoff` with an English note, or `close` for spam/empty.
Design: [`backend/SYSTEM.md`](backend/SYSTEM.md) · all eval outputs: [`backend/eval/RESULTS.md`](backend/eval/RESULTS.md).

## How to run

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env                      # helpdesk key, your email, GEMINI_API_KEY (model: gemini-3.5-flash-lite)
python -m pytest -q                       # 144 unit tests, no network
python -m app.cli -v run                  # dry run on open tickets: traces every step, posts nothing
python -m app.cli eval --tag final        # score on the 10 labelled /examples -> eval/results/
python -m app.cli reset --yes && python -m app.cli run --live    # final run: one decision per ticket
```
Also: `triage --id T005` or `triage --subject … --body …` (one ticket, dry run), `status`, `uvicorn app.main:app`.

## Decisions

1. **AI recommends, code decides.** Keyword rules (nl/en/de) force a handoff for the client's "always a human" list
   (refund, cancellation, GDPR/AVG, security, legal, threat to leave, card data). The LLM never picks a priority: it
   extracts facts (broken? documented fix? money dispute? cosmetic?) and `priority.py` applies the brief's P1–P4 table.
   A reply is sent only if every check passes (cited FAQ section, verifier, language, no payment data or unknown links).
2. **Dutch: detected in code, written directly, checked in English.** `lingua` detects nl/en/de after removing quoted
   text (UI labels); if unsure, no reply. The model writes Dutch directly (no translate-first: one call, no lost nuance,
   menu names as in the FAQ). A second call back-translates each reply and checks every claim against the help centre:
   that is how I verify Dutch I can't read. Cost: one extra call per reply.
3. **Exactly-once, and a small stable model.** A SQLite journal stores each decision *before* posting; after a crash the
   stored decision is replayed, never re-generated. `gemini-3.5-flash-lite`: best and most stable eval score, ~4× fewer
   output tokens than 3.5-flash; a local 2B model was tried and rejected (30%).

**AI tools:** built with Claude Code (design, code, tests, eval); a second AI assistant reviewed plans (e.g. extracting
facts with evidence). I made and approved the decisions, including the expected facts used in the eval.
**Assumptions:** unsure = any check fails, confidence < 0.70, or unclear facts/language → handoff. Questions the FAQ does
not answer (webhooks, Shopify) and mixed tickets are handed off; "other staff are fine" is impact, not a workaround.

## Reliability

- **503:** nothing saved → exponential backoff with jitter (6 tries); still failing → marked failed, replayed next run.
- **429:** wait `Retry-After`, then retry; the client throttles itself to 4 requests/second.
- **409:** already handled → recorded as done, never retried.
- **POST timeout** (maybe saved): `GET /tickets/{id}` first; re-post only if still open.
- **Crash:** before posting → stored decision replayed; after posting → server shows it handled, no second POST.
- **Model down / invalid JSON:** one retry, then the ticket stays open for the next run. Answer length capped.
- **Security:** keys only in `.env`; ticket text is delimited data, never instructions; card/IBAN/CVC masked before the
  model, the logs and every outgoing text; logs hold no ticket body; models never call the helpdesk.

## Eval and fix

10 labelled `/examples` (Nordavo's labels; the model never writes labels). Details per run: [`RESULTS.md`](backend/eval/RESULTS.md).

| | model / method | language | category | priority | action | all four | safety violations |
|---|---|---|---|---|---|---|---|
| before | gemini-3-flash-preview, model picks priority | 100% | 100% | 80% | 100% | 80% | 0 |
| **after** | gemini-3.5-flash-lite, priority calculated (final) | 100% | 100% | **100%** | 100% | **100%** | **0** |
| (rejected) | qwen3.5:2b local | 90% | 90% | 50% | 40% | 30% | 0 |

**The fix:** the model misjudged priority (E01 iOS crash: P2 instead of P3; E02 VAT change: P3 instead of P4). Now it
only extracts facts with evidence and code calculates P1–P4; unclear → more severe + handoff. Priority 80% → 100%, fact
accuracy 100%. Later fixes from the first live run: language in code, `cosmetic_only` → P4, and "workaround" split into
verifiable facts after it caused a regression. Final live run vs the first: 3 tickets changed, all as intended.
**Cost per 100 tickets** (final live run, $0.30 / $2.50 per 1M tokens in/out): 275,303 × $0.30/1M + 33,426 × $2.50/1M
= $0.083 + $0.084 = **$0.17 (≈ €0.15)**. Whole assignment ≈ $0.25.

## What I would improve

**Next step:** more labelled tickets, and a stricter check that a cited "fix" section really describes the customer's
cause (the model once cited the status page as a fix for an outage). **One change to the client rules:** "threat to
leave" is vague and would hand off most annoyed customers; I would ask for a concrete definition (e.g. "explicitly says
they will cancel") so useful replies are not escalated without need.
