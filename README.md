# Roosterly support-ticket agent

Reads every open ticket from the Roosterly helpdesk and posts exactly one decision per ticket: a `reply` in the
customer's language (from `faq.md` only), a `handoff` with an English note, or `close` for spam/empty.
Design and diagrams: [`backend/SYSTEM.md`](backend/SYSTEM.md).

## How to run

```bash
cd backend
pip install -r requirements.txt            # + requirements-jev.txt only for CLASSIFIER=jev
cp .env.example .env                       # fill in the helpdesk key, your email and an LLM key
python -m pytest -q                        # 86 unit tests, no network
python -m app.cli run                      # dry run on open tickets: decides, posts nothing
python -m app.cli eval --tag before        # score on the 10 labelled /examples -> eval/results/
python -m app.cli reset --yes && python -m app.cli run --live    # the final run: posts one decision per ticket
```
Other commands: `triage --id T005` (one ticket, dry run), `status`, `models`, `uvicorn app.main:app` (same pipeline over HTTP).

## Decisions

1. **AI recommends, code decides.** The LLM proposes labels and text; deterministic code has the final say. Keyword rules
   (nl/en/de) force a handoff for the client's "always a human" list (refund, cancellation, GDPR/AVG, security, legal,
   threat to leave, payment data), and a reply survives only if every check passes: confidence ≥ 0.70, a cited FAQ
   section, verifier OK, right language, no payment data, no unknown links. Unsure → handoff.
2. **Dutch handled directly, checked in English.** The model reads and writes Dutch (no translate-first: fewer calls, no
   lost nuance such as "zeggen we op" = "we'll cancel", and menu names stay exactly as in the FAQ). A second call
   back-translates every reply to English and checks each claim against the cited FAQ sections; that back-translation is
   how I check Dutch replies without reading Dutch (see the eval report). Cost: one extra call per reply.
3. **Exactly-once over speed.** A SQLite journal stores each decision *before* posting; a crash replays the stored decision
   instead of asking the model again. Classifier is swappable (`CLASSIFIER=llm|jev`) so Jev (TypeSafe AI, calibrated
   probabilities) can be A/B-tested against the LLM on the same eval.

**AI tools:** built with Claude Code as a pair programmer (design discussion, code, tests); I reviewed and ran every
step. **Assumptions:** questions the FAQ does not answer (e.g. webhooks, Shopify) and mixed tickets (bug + question) are
handed off; the injection text in a ticket is ignored but mentioned in the handoff note; an empty ticket is closed.

## Reliability

- **503:** nothing was saved → exponential backoff with jitter (6 tries); still failing → marked failed, replayed next run.
- **429:** wait `Retry-After`, then retry; the client also throttles itself to 4 requests/second.
- **409:** the ticket is already handled → recorded as done, never retried.
- **Timeout on a POST** (may or may not be saved): check `GET /tickets/{id}` first; only re-post if it is still open.
- **Crash:** before posting → the stored decision is replayed; after posting → the server shows it handled, no second POST.
- **Model down / invalid JSON:** one retry, then the ticket stays open for the next run; nothing half-decided is posted.
- **Security:** keys only in `.env`; ticket text is delimited data, never instructions; card numbers/IBAN/CVC are masked
  before the model, the logs and every outgoing text; logs hold no ticket body. Models never call the helpdesk.

## Eval and fix

TODO (needs an LLM key with credit): `eval --tag before` → fix the largest error → `eval --tag after`.

| | language | category | priority | action | safety violations | cost / 100 tickets |
|---|---|---|---|---|---|---|
| before | TODO | TODO | TODO | TODO | TODO | TODO |
| after | TODO | TODO | TODO | TODO | TODO | TODO |

Cost per 100 tickets = measured tokens on the eval, scaled to 100, × the model's price per token
(the calculation is printed in each `eval/results/*.md`).

## What I would improve

**Next step:** calibrate the 0.70 threshold on more labelled tickets, and A/B-test Jev against the LLM on the same eval;
keep whichever has fewer unsafe replies at the same handoff rate. **One change to the brief / client rules:** "threat to
leave" is vague and would hand off most annoyed customers; I would ask the client for a concrete definition (for example
"explicitly says they will cancel") so useful replies are not escalated without need.
