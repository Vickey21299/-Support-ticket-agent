# Agent API (FastAPI)

The HTTP interface of **this agent**. It is not the Roosterly helpdesk API, which is described in
[`../api_reference.md`](../api_reference.md). It is a thin wrapper around the same pipeline the CLI uses
(`app/main.py`), so the API and the CLI always make the same decision for the same ticket.

## Start it

```powershell
cd backend
pip install -r requirements.txt      # once; .env must contain the helpdesk key, your email and GEMINI_API_KEY
uvicorn app.main:app --reload
```

| URL | What |
|---|---|
| http://127.0.0.1:8000/docs | **Swagger UI**: try every endpoint in the browser (open it, click *Try it out*, fill in the parameters, click *Execute*) |
| http://127.0.0.1:8000/redoc | the same reference, read-only layout |
| http://127.0.0.1:8000/openapi.json | machine-readable OpenAPI schema |

In PowerShell, call it with **`curl.exe`**: plain `curl` in Windows PowerShell 5.1 is a different command.

## Safety rules

- **Nothing is posted by default.** Only `dry_run=false` on `/triage/{id}` or `/runs` sends a decision to the helpdesk.
- **Reset needs `confirm=true`**, and it is refused while a live run is in progress.
- **One live run at a time**: a second one gets `409`.
- **A customer never gets two answers.** Posting a ticket that is already handled returns the outcome `already_handled`.
  Note: the model is still called first, so that attempt costs one Gemini call.
- Keys stay in `.env`; no endpoint returns secrets. Card numbers, IBANs and CVCs are masked before any model, log or reply.

## Endpoints at a glance

| Method | Path | Does | Posts to helpdesk? | Calls Gemini (costs)? |
|---|---|---|---|---|
| GET | `/health` | configuration check | no | no |
| GET | `/status` | helpdesk open/handled + local journal | no | no |
| GET | `/tickets` | list tickets with their handled state | no | no |
| GET | `/tickets/{ticket_id}` | one ticket: helpdesk record + the decision we stored | no | no |
| POST | `/fetch` | save a snapshot to `backend/data/` | no | no |
| POST | `/triage` | decide on a ticket you send in the body | **never** | yes, 1 ticket |
| POST | `/triage/{ticket_id}` | decide on one helpdesk ticket | only with `dry_run=false` | yes, 1 ticket |
| POST | `/runs` | process all open tickets in the background | only with `dry_run=false` | yes, every ticket |
| GET | `/runs/{run_id}` | progress and results of a run | no | no |
| POST | `/eval` | score the agent on the 10 labelled examples | never | yes, 10 tickets (≈ $0.02) |
| POST | `/practice/reset` | re-open all practice tickets | **yes** (reset) | no |

## Reference

### `GET /health`
Shows whether the helpdesk and the LLM are configured (no secrets).
```json
{"status": "ok", "helpdesk_configured": true, "llm_configured": true, "llm_provider": "gemini", "reply_threshold": 0.7}
```

### `GET /status`
The helpdesk's open/handled counts plus the local journal's counts.
```json
{"mode": "practice", "open_tickets": 30, "handled_tickets": 0, "live_ends_at": null, "local_journal": {"completed": 30}}
```

### `GET /tickets?status=all|open`
Every ticket (`all`, the default) or only the open ones, with its `handled` state from the helpdesk.
```json
{"count": 30, "handled": 1, "tickets": [{"id": "T005", "subject": "Nieuwe medewerker", "handled": {"at": "...", "action": "reply"}}, ...]}
```

### `GET /tickets/{ticket_id}`
One ticket, from two sources:
- **`helpdesk`**: what the helpdesk has. For a handled ticket it only stores the action and the time: `"handled": {"at": ..., "action": "reply"}`.
- **`agent_journal`**: the full decision this agent stored, such as `draft_reply`, `handoff_note`, `reason`, `priority`
  (+ `priority_basis`), `language` (+ `language_basis`), `faq_ids`, `facts`, `verification` (incl. the English
  back-translation) and `policy_notes`. It is `null` if the agent never processed the ticket.

After a practice reset, `helpdesk.handled` is `null`, but the journal keeps the previous decision until the ticket is
processed again.

### `POST /fetch`
A read-only snapshot, the same code as `python fetch_data.py`. It writes `data/status.json`, `data/examples.json` and
`data/tickets.json`. The offline eval and `source=file` runs read these files.
```json
{"status": {"mode": "practice", "open_tickets": 30, "handled_tickets": 0, "live_ends_at": null},
 "examples": 10, "tickets": 30, "open_in_snapshot": 30, "files": ["...status.json", "...examples.json", "...tickets.json"]}
```

### `POST /triage` (body: a ticket)
Decides on any ticket text you send, for example to test a new case. It **never posts.**
```json
{"id": "TEST1", "subject": "Wachtwoord", "body": "Hoi, ik ben mijn wachtwoord vergeten. Hoe kom ik er weer in?", "customer_plan": "Basis"}
```
It returns the full decision (same fields as `agent_journal.decision` above).

### `POST /triage/{ticket_id}?dry_run=true|false`
Fetches the ticket from the helpdesk and decides on it.
- `dry_run=true` (default): shows the decision and posts nothing.
- `dry_run=false`: posts the decision **once** (it is stored in the journal before posting).

```json
{"ticket_id": "T005", "outcome": "posted", "error": null, "decision": {"action": "reply", "language": "nl", "priority": "P4", "draft_reply": "Hoi Anouk, ...", ...}}
```

### `POST /runs?dry_run=true|false&source=api|file&limit=N`
Processes all open tickets in the background and returns at once (`202`):
```json
{"run_id": "run-20261118T...", "status_url": "/runs/run-20261118T..."}
```
- `source=api` (default): open tickets from the helpdesk. `source=file`: the open tickets in `data/tickets.json`
  (dry run only).
- `limit`: only the first N tickets.

### `GET /runs/{run_id}`
The run's progress: `status` (`running` / `finished` / `error`), `total`, one result per ticket
(`ticket_id`, `outcome`, `action`, `error`) and, when finished, `counts` and the `log` file path.

### `POST /eval?tag=<name>`
Runs the full agent (dry run) on the 10 labelled `/examples` and scores it against Nordavo's labels. It writes
`eval/results/<UTC time>-<tag>.md` and `.json`. Gemini makes the predictions; code does the scoring and writes the files.
The response includes `accuracy` per field, `all_fields_correct`, `safety_violations`, `fact_accuracy`, tokens, `cost`
and `rows`. Needs `data/examples.json` (run `/fetch` first on a fresh clone).

### `POST /practice/reset?confirm=true`
Re-opens **all** practice tickets on the helpdesk.
- Without `confirm=true`: `400` and nothing happens.
- During a live run: `409`.
```json
{"reset": {"ok": true, "reopened_tickets": 1}, "status": {"mode": "practice", "open_tickets": 30, "handled_tickets": 0, ...}}
```

### Outcomes (per ticket)

| `outcome` | Meaning |
|---|---|
| `dry_run` | decided, nothing posted |
| `posted` | decision posted to the helpdesk |
| `already_handled` | the helpdesk refused (409): the ticket was already handled, nothing sent twice |
| `reconciled` | a stored decision was already on the helpdesk (e.g. after a crash), so it was not posted again |
| `deferred` | the model failed; the ticket stays open for the next run |
| `failed` | posting failed after retries; replayed on the next run |

### Errors

| Code | When |
|---|---|
| `400` | reset without `confirm=true`; `GET /tickets` with a status other than `open`/`all` |
| `404` | unknown `run_id`, or a ticket the helpdesk does not know |
| `409` | a live run is already in progress (live `/runs`, reset) |
| `503` | helpdesk or LLM keys missing from `.env`, or the model could not decide |
| other | helpdesk errors are passed through with their own status code |

## Workflows

All of these can be done in Swagger UI (`/docs`) or with `curl.exe`.

### 1. Check where things stand (free)
```powershell
curl.exe http://127.0.0.1:8000/status
curl.exe "http://127.0.0.1:8000/tickets?status=open"
```

### 2. Fetch the data (free)
```powershell
curl.exe -X POST http://127.0.0.1:8000/fetch
```
Do this on a fresh clone before `/eval`, and again after a reset so the snapshot is current.

### 3. Try one ticket without posting
```powershell
curl.exe -X POST "http://127.0.0.1:8000/triage/T005?dry_run=true"
```

### 4. Post one ticket, check it, reset
```powershell
curl.exe -X POST "http://127.0.0.1:8000/triage/T005?dry_run=false"      # posts once
curl.exe http://127.0.0.1:8000/tickets/T005                             # helpdesk: handled; journal: what we sent
curl.exe http://127.0.0.1:8000/status                                   # 29 open / 1 handled
curl.exe -X POST "http://127.0.0.1:8000/practice/reset?confirm=true"    # back to 30 open
curl.exe -X POST http://127.0.0.1:8000/fetch                            # snapshot up to date again
```
A correct post shows: the helpdesk's `handled.action` equals the journal's `decision.action`, and the journal's
`outcome` is `posted`.

### 5. Run all tickets
```powershell
curl.exe -X POST "http://127.0.0.1:8000/runs?dry_run=true"      # look first; returns a run_id
curl.exe http://127.0.0.1:8000/runs/<run_id>                    # poll until status = finished
curl.exe -X POST "http://127.0.0.1:8000/runs?dry_run=false"     # the real run: one decision per ticket
```

### 6. Evaluate
```powershell
curl.exe -X POST "http://127.0.0.1:8000/eval?tag=check"          # ≈ $0.02; report in eval/results/
```
The free, model-less **language** eval is CLI-only: `python -m app.cli langeval`.

## CLI equivalents

| API | CLI (from `backend/`) |
|---|---|
| `GET /status` | `python -m app.cli status` |
| `POST /fetch` | `python fetch_data.py` |
| `POST /triage/{id}?dry_run=true` | `python -m app.cli -v triage --id T005` |
| `POST /runs?dry_run=false` | `python -m app.cli run --live` (`--limit 1` = first open ticket only) |
| `POST /eval?tag=x` | `python -m app.cli eval --tag x` |
| `POST /practice/reset?confirm=true` | `python -m app.cli reset --yes` |
| none | `python -m app.cli langeval` (language detection only, no cost) |
