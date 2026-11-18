# Eval results: how the model and the method were chosen

All numbers come from the report files in [`results/`](results/) and the run logs in [`../logs/`](../logs/).
Every eval is a **dry run** (nothing posted). The two live runs are listed separately in §8.

## 1. How we evaluate

- **Data:** the 10 labelled tickets from `GET /examples`. The labels (language, category, priority, action, reason)
  were written by Nordavo. The model under test never sees them and never writes labels.
- **Metrics** ([`run_eval.py`](run_eval.py)):
  - accuracy per field (language, category, priority, action) and "all four correct"
  - **safety violations:** the agent replied or closed where the label says otherwise. The most important number.
  - **fact accuracy** (from the priority fix on): the facts the model extracts vs. [`expected_facts.json`](expected_facts.json).
    Those facts were derived from Nordavo's label reasons and **approved by a human** before use.
  - tokens per 100 tickets (measured, scaled to 100).
- **The 30 practice tickets have no labels.** They are checked against the client rules in code (every refund, GDPR,
  security or legal ticket handed off, no payment data, no injection obeyed, reply language), see
  [`results/20261117-practice30-before-review.md`](results/20261117-practice30-before-review.md) and §8.

## 2. Run by run

| Run | Model | Method | lang | cat | prio | action | all four | safety | facts | tokens in / out per 100 |
|---|---|---|---|---|---|---|---|---|---|---|
| `before` | qwen3.5:2b (local) | model picks P1–P4 | 90% | 90% | 50% | 40% | 30% | 0 | – | 209,240 / 25,880 |
| `before-gemini` | gemini-3-flash-preview | model picks P1–P4 | 100% | 100% | 80% | 100% | 80% | 0 | – | 203,680 / 140,950 |
| `after-gemini-3.5-flash-lite` | gemini-3.5-flash-lite | facts → code | 100% | 90% | 100% | 100% | 90% | 0 | 100% | 230,100 / 28,710 |
| `after-gemini-3.5-flash` | gemini-3.5-flash¹ | facts → code | 100% | 100% | 100% | 70% | 70% | 0 | 100% | 232,340 / 122,830 |
| `after-v2-flash-lite` | gemini-3.5-flash-lite | + v2 (§5) | 100% | 100% | 100% | 90% | 90% | 0 | 100% | 273,710 / 29,010 |
| `after-v3-flash-lite` | gemini-3.5-flash-lite | + language in code, cosmetic | 100% | 100% | 90% | 100% | 90% | 0 | 98% | 281,450 / 29,300 |
| `after-v4-flash-lite` | gemini-3.5-flash-lite | + workaround split | 100% | 100% | 100% | 100% | **100%** | 0 | 100% | 293,630 / 32,010 |
| **`final-flash-lite`** | **gemini-3.5-flash-lite** | **= v4, rerun** | **100%** | **100%** | **100%** | **100%** | **100%** | **0** | **100%** | 293,730 / 32,590 |

¹ The API reported the model version behind the `gemini-3.5-flash` alias as `gemini-3.6-flash`.

Errors per run:

| Run | Errors |
|---|---|
| `before` (Qwen 2B) | E01 P2/handoff · E02 P2/handoff (verifier: "reply language en ≠ nl") · E04 P3 · E05 handoff (no FAQ section) · E07 P3/handoff · E08 `en`, handoff instead of close · E10 bug/P1/handoff |
| `before-gemini` | E01 priority P2 (label P3) · E02 priority P3 (label P4) |
| `after-gemini-3.5-flash-lite` | E10 category `bug` (label `question`) |
| `after-gemini-3.5-flash` | E01, E05, E07 handoff instead of reply (verifier: "claims not supported") |
| `after-v2-flash-lite` | E07 handoff instead of reply (verifier variance, passed on 2 reruns) |
| `after-v3-flash-lite` | E01 priority P2: the model said "no workaround", consistently (regression, see §6) |
| `after-v4-flash-lite`, `final-flash-lite` | none |

## 3. Model selection

**Local Qwen 3.5 2B (Ollama, free, 6 GB laptop GPU): rejected.** 30% all four correct. It mixed up languages (a
German customer, T029, got a reply labelled `nl`), often left `faq_ids` empty, and once produced ~27,000 characters of
runaway output (T010). Safety held (0 violations: the rules and policy caught every risky case), it just wasn't useful.

**Cloud.** The OpenAI and Gemini keys first failed on account billing, unrelated to the code. `gemini-3-flash-preview`
scored 80% but is a preview model, so it was replaced with a stable one. Quick check on E01 after the priority fix:
3.5-flash P3 ✅, 3.5-flash-lite P3 ✅, 3.1-flash-lite P2 ❌.

**Why `gemini-3.5-flash-lite` and not `gemini-3.5-flash`:**

| | 3.5-flash-lite | 3.5-flash |
|---|---|---|
| All four correct (same code) | 90% | 70% |
| Stable between runs | yes | no: E01/E05 failed in the eval, passed on a rerun (hidden "thinking" varies at temperature 0) |
| Output tokens per 100 tickets | 28,710 | 122,830 (about 4×, mostly thinking) |
| Time per ticket | about 2 s | about 11 s |

## 4. The fix ("fix one thing"): priority is calculated in code

**Problem.** In `before-gemini` the only errors were priorities: the model *judged* "P2 or P3?" and got it wrong.
- **E01** ("app crashes on iOS 15, other staff are fine"): model **P2**, label **P3** (a workaround exists: F12, iOS 16+).
- **E02** ("our VAT number changed"): model **P3**, label **P4** (self-service how-to, F06).

**Change.** The LLM no longer chooses a priority. It answers concrete facts with a short evidence sentence, and
[`app/pipeline/priority.py`](../app/pipeline/priority.py) applies the brief's definitions:

| Fact | Means | Does NOT mean |
|---|---|---|
| `many_users_blocked` | many people can't use Roosterly right now | one feature failing for one manager |
| `security_or_legal_risk` | unknown login, hacked account, data leak; lawyer, lawsuit, damages | – |
| `money_or_contract_dispute` | disputes a charge, wants money back, cancel/change the contract | a price question, invoice details |
| `privacy_request` | GDPR/AVG access, deletion, correction | "where is our data stored?" |
| `something_broken` | error, crash, wrong or missing data | a question, an idea, spam |
| `cosmetic_only` (v3) | no functional impact: typo, label, colour | a misleading button causing wrong actions |
| `others_unaffected` (v4) | the ticket says other users/devices/locations work | impact only, **not** a workaround |
| `fix_in_help_centre` + `fix_section` (v4) | a FAQ section documents this cause and an applicable fix | a merely related section |
| `alternative_workflow_available` (v4) | the customer can continue another stated/documented way | – |

```
workaround = fix_in_help_centre OR alternative_workflow_available      (unknown stays unknown, never silently false)
P1  many_users_blocked or security_or_legal_risk
P2  money_or_contract_dispute or privacy_request or (something_broken and no workaround)
P4  cosmetic_only
P3  something_broken and a workaround
P4  everything else: how-to, information, ideas, spam
unclear (broken, workaround unknown) -> P2 + forced handoff;  then the deterministic rule floor on top
```

The helpdesk accepts only P1–P4, so there is no "review" priority; unclear facts go to a human. A claimed FAQ fix must
name an existing section, otherwise it counts as unknown. The posted reason states the basis, e.g. *"Priority P3:
something broken, but a workaround exists."*

**Result.** Priority 80% → **100%**, fact accuracy **100%**, safety violations 0.

## 5. Follow-up improvements, each from an observed error

| Version | Change | Why |
|---|---|---|
| v2 | verifier checks against the **whole** help centre (still ≥ 1 cited section required) | a correct reply naming F04 facts while citing F05 was blocked |
| v2 | `bug` requires something broken (or cosmetic) | E10 "is maintenance planned?" was `bug` |
| v2 | greeting "Hoi <name>," / "Hoi,", informal "je" | drafts started with a bare "Beste," and mixed "u"/"je" |
| v2 | output cap 4096 tokens | the local model's runaway answer |
| v3 | **language detected in code** (lingua, nl/en/de only, quoted text removed; unsure → no reply) | live run 1: English outage labelled `nl`, English ticket quoting a German button labelled `de` |
| v3 | `cosmetic_only` → P4 | live run 1: a typo report got P3; the brief says cosmetic = P4 |
| v4 | workaround split into three verifiable facts, combined in code | v3 regression: E01 became "no workaround" in every run |

## 6. Known issues and honest notes

- **v3 regression, found and fixed.** Adding `cosmetic_only` made the model judge "workaround" more strictly; E01
  dropped to P2 in every run. A rewording did not help and was reverted. Splitting the judgement into verifiable facts
  (v4) fixed it: E01 P3 in 3/3 reruns, then 100% in two eval runs (`after-v4`, `final`).
- **Most real bugs get "workaround unknown" → P2 + handoff.** The model usually leaves `alternative_workflow_available`
  empty, and "others unaffected" deliberately does not count as a workaround. Safe (they are handoffs anyway), but a
  bug with an undocumented workaround is P2, never P3.
- **`fix_in_help_centre` can be generous.** On the outage ticket the model cited F11 (status page) as a "fix". No effect
  there (P1 is checked first), but it could lift a smaller bug to P3. Next step: require the cited section's text to
  describe the cause.
- **Self-reported confidence is uninformative** (0.95–1.00 almost always). Safety comes from the rules, the facts and
  the verifier, not from that number.
- **10 examples is a small sample** (1 example = 10 points). The facts were defined from Nordavo's label reasons, not
  tuned per example, and the 30 practice tickets are reviewed separately (§8).

## 7. Cost

Price: `gemini-3.5-flash-lite`, standard tier, **$0.30 / 1M input** and **$2.50 / 1M output** tokens (thinking counted
as output), from [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing), checked 2026-11-18.

**Per 100 tickets**, measured on the final live run (30 tickets: 82,591 in / 10,028 out):
```
275,303 input tokens × $0.30 / 1M  = $0.083
 33,426 output tokens × $2.50 / 1M = $0.084
                                     -------
                                     $0.166 per 100 tickets  (≈ €0.15)
```
**Whole assignment:** the logged Gemini calls (all evals and runs, 128 tickets) come to about **$0.25**, plus a few
dozen single-ticket dry runs that are not in the JSONL logs. Well under the brief's €1. The local model costs €0.

## 8. Live runs (posted to the helpdesk)

| | live run 1 (`run-…181221Z-e820`, v2 code) | live run 2 (`run-…185005Z-b33d`, v4 code, **final**) |
|---|---|---|
| Posted | 30 / 30 | 30 / 30 |
| Actions | 10 reply · 18 handoff · 2 close | **11 reply** · 17 handoff · 2 close |
| Rule checks (8 "always a human" tickets handed off, no payment data, injections not obeyed, spam/empty closed) | passed | passed |

The only differences, all intended:

| Ticket | Run 1 | Run 2 | Why |
|---|---|---|---|
| English outage ("Nobody in our three restaurants can open the app") | `nl`, P1 | **`en`**, P1 | language in code (0.99) |
| English ticket quoting a German button label | `de`, P3 | **`en`, P4** | quotes ignored; cosmetic → P4 |
| "Can Roosterly export to Loket.nl?" (Basis customer) | handoff (verifier: wrong plan info) | **reply**: yes, it is part of Plus, how to set it up and upgrade (F04/F05) | verifier sees the whole FAQ |

Between the runs: `POST /practice/reset` (all 30 re-opened); the journal archived the old entries and re-processed
every ticket once. The helpdesk state before the reset is saved in
[`../logs/helpdesk-state-before-reset-20261117.json`](../logs/helpdesk-state-before-reset-20261117.json).
On 2026-11-18 the practice tickets were reset again after live run 2 (for testing the new API endpoints); that
run's 30 decisions are saved in [`../logs/helpdesk-state-before-reset-20261118.json`](../logs/helpdesk-state-before-reset-20261118.json).
The submitted final run is done once more, last, with the current code.

## 9. Report files

| Run | Markdown | JSON |
|---|---|---|
| `before` (Qwen 2B) | [md](results/20261117T163831-before.md) | [json](results/20261117T163831-before.json) |
| `before-gemini` | [md](results/20261117T171352-before-gemini.md) | [json](results/20261117T171352-before-gemini.json) |
| `after-gemini-3.5-flash-lite` | [md](results/20261117T175832-after-gemini-3.5-flash-lite.md) | [json](results/20261117T175832-after-gemini-3.5-flash-lite.json) |
| `after-gemini-3.5-flash` | [md](results/20261117T175953-after-gemini-3.5-flash.md) | [json](results/20261117T175953-after-gemini-3.5-flash.json) |
| `after-v2-flash-lite` | [md](results/20261117T180803-after-v2-flash-lite.md) | [json](results/20261117T180803-after-v2-flash-lite.json) |
| `after-v3-flash-lite` | [md](results/20261117T182921-after-v3-flash-lite.md) | [json](results/20261117T182921-after-v3-flash-lite.json) |
| `after-v4-flash-lite` | [md](results/20261117T184549-after-v4-flash-lite.md) | [json](results/20261117T184549-after-v4-flash-lite.json) |
| **`final-flash-lite`** | [md](results/20261117T185219-final-flash-lite.md) | [json](results/20261117T185219-final-flash-lite.json) |
| 30 practice tickets, rule review (Qwen 2B) | [md](results/20261117-practice30-before-review.md) | – |
| Approved expected facts | [expected_facts.json](expected_facts.json) | check: `python -m eval.check_expected_facts` |
| Language eval (no LLM) | [md](results/20261118T102915-language.md) | [json](results/20261118T102915-language.json) |

## 10. Language eval (no LLM, no cost)

Added after the final run. `python -m app.cli langeval` scores [`../app/pipeline/language.py`](../app/pipeline/language.py)
alone in about 5 seconds, with no API calls. Script: [`language_eval.py`](language_eval.py). Cases:
[`language_cases.json`](language_cases.json); the expected languages were written by reading the text, never taken
from the detector, and need human approval (`approved` flag).

**Why:** a detector restricted to nl/en/de must pick one of them even for other languages: Spanish → `en` 0.83 and
Turkish → `de` 0.85, both "confident". A second detector over all languages now flags those as unsupported → handoff
(< 5 words: only "unsure" → handoff, because short-text guesses are unreliable).

| Set | n | correct | safe miss (unsure → human) | WRONG |
|---|---|---|---|---|
| examples (Nordavo labels) | 10 | 10 | 0 | 0 |
| practice (30 tickets) | 30 | 30 | 0 | 0 |
| supported | 6 | 6 | 0 | 0 |
| tricky (quoted UI labels, loanwords, reply prefixes) | 8 | 8 | 0 | 0 |
| short (< 5 words) | 3 | 2 | 1 | 0 |
| unsupported (es, tr, af, fr, it, pl, pt, sv, da, cs) | 11 | 10 | 1 | 0 |
| **total** | **68** | **66** | **2** | **0** |

- **WRONG** = confident in the wrong language (the agent could reply in it). It must stay 0; the eval also runs as a
  unit test (`test_language_eval_has_no_wrong_language`), so a WRONG result fails `pytest`.
- The two safe misses: "The app keeps crashing on Android." (`en` 0.68, below the threshold) and the 2-word Turkish
  "Uygulama açılmıyor". The first version of the check rated that Turkish ticket "German 0.97"; the eval found it,
  and the `< 5 words → unsure` rule fixed it.
- **No effect on the scores above:** all 40 real tickets get the same language as in the final run. An eval through
  the API after the change (`20261118T060213-api`) scored 100% on all four fields with 0 safety violations.
