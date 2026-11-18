# Engineering decisions

How the Roosterly ticket agent got from 30% to 100% on the labelled examples, one decision at a time.
Every step followed the same loop: **run the eval → read the errors → change one thing → run the eval again.**
All numbers come from the eval reports in [`backend/eval/results/`](backend/eval/results/); the full per-run detail
is in [`backend/eval/RESULTS.md`](backend/eval/RESULTS.md).

## 0. How we measured

Before choosing anything, we built the yardstick.

- **Data:** the 10 labelled tickets from `GET /examples`. The labels (language, category, priority, action) were written
  by Nordavo. The model under test never sees them and never writes labels.
- **Scores:** accuracy per field, "all four correct", and **safety violations** (the agent replied or closed where the
  label says a human is needed). Safety is the number that must stay at 0.
- **Cost:** input/output tokens per 100 tickets, measured on every run.
- **The 30 practice tickets** have no labels, so they were checked against the client rules in code (every refund,
  GDPR, security or legal ticket handed off, no payment data, no prompt injection obeyed, correct reply language).

This eval is what made every later decision a measured one instead of a guess.

## 1. Model: local Qwen 3.5 2B → cloud Gemini

**First try: a local model.** `qwen3.5:2b` via Ollama: free, private, runs on a 6 GB laptop GPU.

| Run | Model | lang | cat | prio | action | all four | safety |
|---|---|---|---|---|---|---|---|
| `before` | qwen3.5:2b (local) | 90% | 90% | 50% | 40% | **30%** | 0 |

What went wrong: it mixed up languages (a German customer got a reply labelled `nl`), often cited no FAQ section,
judged priority badly, and once produced ~27,000 characters of runaway output. Safety held only because the
deterministic rules and policy layer caught every risky case.

**Decision:** reject the local model. It was safe but not useful. (We kept the Ollama client, so it can still be
switched on with `LLM_PROVIDER=ollama`.)

**Second try: cloud.** `gemini-3-flash-preview`, same code:

| Run | Model | lang | cat | prio | action | all four | safety |
|---|---|---|---|---|---|---|---|
| `before-gemini` | gemini-3-flash-preview | 100% | 100% | 80% | 100% | **80%** | 0 |

Big jump, and the **only** remaining errors were priorities. It was a preview model, though, so we had to pick a
stable one.

## 2. Choosing between Gemini 3.5 Flash and 3.5 Flash-Lite

We ran both stable models on the same code (after the priority fix in §3):

| | gemini-3.5-flash-lite | gemini-3.5-flash |
|---|---|---|
| All four correct | **90%** | 70% |
| Stable between runs | **yes** | no: E01/E05 failed, then passed on a rerun (hidden "thinking" varies even at temperature 0) |
| Output tokens per 100 tickets | **28,710** | 122,830 (about 4×, mostly thinking) |
| Time per ticket | **~2 s** | ~11 s |

**Decision:** `gemini-3.5-flash-lite`. The bigger model was *less* accurate here, less predictable, about 4× more
expensive in output tokens, and 5× slower. For a triage agent that must make the same decision twice on the same
ticket, stability matters more than raw model size.

## 3. Priority: stop asking the LLM, calculate it in code

**Problem.** With Gemini, every remaining error was a priority judgement:

- **E01** "app crashes on iOS 15, other staff are fine": model said **P2**, label **P3** (a workaround exists: FAQ F12, update to iOS 16+).
- **E02** "our VAT number changed": model said **P3**, label **P4** (a self-service how-to, FAQ F06).

Asking a model "is this P2 or P3?" is asking it to apply a policy it can interpret loosely. The brief already defines
the policy precisely, so this is a job for code.

**Change.** The LLM no longer picks a priority. It answers concrete yes/no **facts**, each with a short evidence
sentence from the ticket, and [`priority.py`](backend/app/pipeline/priority.py) applies the brief's P1–P4 definitions:

```
P1  many_users_blocked or security_or_legal_risk
P2  money_or_contract_dispute or privacy_request or (something_broken and no workaround)
P3  something_broken and a workaround exists
P4  everything else: how-to, information, ideas, spam
unclear (broken, workaround unknown)  ->  P2 + forced handoff to a human
then the deterministic keyword rule floor on top (it can only raise priority, never lower it)
```

The expected facts for the 10 examples were derived from Nordavo's label reasons and **approved by a human** before
they were used, so we could score the model's fact extraction directly.

**Result:**

| | priority accuracy | fact accuracy | safety |
|---|---|---|---|
| model picks priority | 80% | – | 0 |
| facts → code calculates | **100%** | **100%** | 0 |

**Principle we kept from here on:** *AI extracts, code decides.* Deterministic code may make the agent more careful
(force a handoff, raise a priority), never less.

## 4. The other factors, each fixed from an observed error

With priority solved, we moved to the remaining errors one by one. Each change was triggered by a specific failure in
an eval or in the first live run, not by speculation.

| Version | Problem observed | Change | all four |
|---|---|---|---|
| after (3.5-flash-lite) | E10 "is maintenance planned?" labelled `bug` | – | 90% |
| **v2** | `bug` without anything broken; a correct reply blocked because the verifier only checked the one cited FAQ section; drafts mixed formal "u" and informal "je" | `bug` requires something broken; verifier checks against the whole help centre (still ≥ 1 cited section); fixed greeting and tone; output capped at 4096 tokens | 90% |
| **v3** | Live run 1: an English outage labelled `nl`; an English ticket quoting a German button labelled `de`; a typo report got P3 | **Language detected in code** (`lingua`, nl/en/de, quoted text removed; unsure → no reply); new fact `cosmetic_only` → P4 | 90% (regression) |
| **v4** | v3 regression: E01 dropped to "no workaround" → P2 in every run | "Workaround" split into three verifiable facts (`fix_in_help_centre` + section, `alternative_workflow_available`, `others_unaffected`), combined in code | **100%** |
| **final** | rerun of v4 to confirm it is not luck | – | **100%** |

**The v3 regression is the most useful lesson.** Adding one fact made the model judge "workaround" more strictly, and
E01 broke in every run. Rewording the prompt did not help and was reverted. What fixed it was the same move as §3:
replace one vague judgement ("is there a workaround?") with smaller facts the model can verify against the ticket
and the FAQ, then let code combine them.

## 5. Language detection: from the LLM to a local detector

**Problem.** At first the LLM labelled the ticket's language as part of its decision. That failed in ways the eval and
the first live run made visible:

- the local Qwen model gave a German customer (T029) a reply labelled `nl`;
- Gemini (live run 1) labelled an English outage ticket ("Nobody in our three restaurants can open the app") as `nl`;
- an English ticket that **quoted a German button label** was labelled `de`.

The language decides which language the reply is written in, so a wrong label means a customer gets an answer they
cannot read. And the brief lists exactly three languages the helpdesk accepts. That makes this a narrow, well-defined
classification task, which does not need an LLM.

**Change.** Language is detected **in code, locally**, with the open-source
[`lingua-language-detector`](https://pypi.org/project/lingua-language-detector/) package:

```
pip install lingua-language-detector==2.1.1      # pinned in backend/requirements.txt
```

Implemented in [`backend/app/pipeline/language.py`](backend/app/pipeline/language.py):

1. **Only nl / en / de.** The detector is built for just these three languages, so it can never return a language
   the helpdesk rejects.
2. **The customer's own words only.** Before detection, the code strips quoted text (UI labels, button names, copied
   messages), links, email addresses, numbers, masked payment data and `Re:`/`Fw:` prefixes. An English ticket that
   quotes a German button is still English.
3. **Unsure means no reply.** If the top confidence is below 0.70 (very short or mixed text), the result is marked
   `unsure` and `policy.py` forces a handoff instead of sending a reply in a language we guessed.

**Why a local detector instead of asking the LLM:**

| | LLM label (before) | `lingua`, local (after) |
|---|---|---|
| Deterministic | no: can change between runs | yes: same text, same answer |
| Cost and latency | part of the paid model call | free, offline, milliseconds, no API key |
| Restricted to nl/en/de | only by the prompt | yes, by construction |
| Ignores quoted UI text | no: the German button label made it `de` | yes: quotes removed first |
| Confidence you can act on | self-reported, almost always 0.95–1.00 | a real score; < 0.70 → handoff |
| Trade-off | – | a ~96 MB wheel in the install |

`lingua` fits this job because it handles short, informal texts better than detectors that need long input, and it
can be restricted to a fixed set of languages. The behaviour is covered by unit tests in
[`backend/tests/test_language.py`](backend/tests/test_language.py) (quoted labels ignored, empty and very
short text marked unsure, an unclear language never replies, a reply in the wrong language is never sent).

**Result (live run 1 → live run 2):** the English outage ticket went from `nl` to **`en` (confidence 0.99)**, and the
English ticket quoting a German button went from `de` to **`en`**. This was shipped in v3; language accuracy on the
labelled examples stayed at 100%.

**Same principle again:** a judgement that code can make reliably is taken away from the model.

### 5b. Tickets in other languages (after the final run)

**Problem.** A detector restricted to nl/en/de *must* pick one of them, whatever the customer wrote. Tested on purpose:
Spanish came out as `en` (0.83) and Turkish as `de` (0.85), both above the 0.70 threshold. So the agent could have
replied in the wrong language. Afrikaans came out as `nl` (0.97).

**Option rejected:** replace it with an all-language detector. On our 40 real tickets it picked the right top
language every time, but its scores are spread over ~75 languages (a Dutch example scored only `nl` 0.35 against
Afrikaans), so the 0.70 threshold would have turned good Dutch replies into handoffs.

**Change:** keep the nl/en/de detector for the label and confidence, and add a second local detector over all
languages that is only asked "which language is on top?":

| All-language top pick | Result |
|---|---|
| nl / en / de | unchanged: the nl/en/de detector decides |
| another language, ≥ 5 words | `unsupported` (e.g. `es`): no reply, handoff with "customer wrote in 'es'" |
| another language, < 5 words | `unsure`: no reply (on a word or two it guesses wildly: "ok" came out as Zulu) |

Spam in any language can still be closed. The helpdesk only accepts nl/en/de, so the posted `language` stays one of
those; the real language is in the reason for the human. Out of scope (and not needed for the brief): replying in
other languages.

**How we measured it, for free:** a separate language eval (`python -m app.cli langeval`) runs the detector alone, with
no LLM and no API cost, in about 5 seconds. It covers the 10 examples (Nordavo's labels), the 30 practice tickets and 28
hand-written cases (expected languages written by reading the text, never taken from the detector). Outcomes: correct,
safe miss (unsure → human) or **WRONG** (confident in the wrong language), and WRONG must be 0.

| Set | Correct |
|---|---|
| 10 examples (Nordavo labels) | 10 / 10 |
| 30 practice tickets | 30 / 30 |
| supported + tricky cases (quoted UI labels, loanwords, reply prefixes) | 14 / 14 |
| short texts | 2 / 3 (1 unsure) |
| 11 other languages (es, tr, af, fr, it, pl, pt, sv, da, cs; 2-word Turkish) | 10 / 11 (1 unsure) |
| **total** | **66 / 68, 0 WRONG** |

The eval found a real gap in the first version: a 2-word Turkish ticket was "German 0.97" because it was below the
5-word minimum. The fix is the `< 5 words → unsure` row above. The eval also runs as a unit test, so a WRONG result
fails `pytest`. All 40 real tickets are detected exactly as in the final run, so the LLM eval (100%) still holds; an
eval run through the API after the change confirmed 100% with 0 safety violations.

## 6. Dutch: write directly, verify in English

Most tickets are Dutch. Options considered: translate to English → answer → translate back, or write Dutch directly.

**Decision:** the model writes Dutch directly (one call, no lost nuance, menu names exactly as in the FAQ). A second
call back-translates each reply to English and checks every claim against the help centre. That is how a reviewer who
does not read Dutch can still verify the reply. Cost: one extra call per reply, which is worth it.

## 7. Final result

| Run | Model / method | lang | cat | prio | action | all four | safety | facts |
|---|---|---|---|---|---|---|---|---|
| `before` | qwen3.5:2b, model picks priority | 90% | 90% | 50% | 40% | 30% | 0 | – |
| `before-gemini` | gemini-3-flash-preview, model picks priority | 100% | 100% | 80% | 100% | 80% | 0 | – |
| `after` | gemini-3.5-flash-lite, facts → code | 100% | 90% | 100% | 100% | 90% | 0 | 100% |
| `v4` | + workaround split | 100% | 100% | 100% | 100% | **100%** | 0 | 100% |
| **`final`** | **= v4, rerun** | **100%** | **100%** | **100%** | **100%** | **100%** | **0** | **100%** |

- **Live run on the 30 practice tickets:** 30/30 posted (11 reply, 17 handoff, 2 close), all client rule checks passed.
- **Cost:** about **$0.17 per 100 tickets** (≈ €0.15); the whole assignment cost about $0.25, well under the €1 budget.
- **Safety violations: 0 in every run**, including the 30% local-model run, because safety comes from the rules,
  facts and verifier, not from the model.

## 8. Honest caveats

- **10 examples is a small sample**: one ticket = 10 points. The facts were defined from Nordavo's label reasons, not
  tuned per example, and the 30 practice tickets were reviewed separately against the client rules.
- **Most real bugs get "workaround unknown" → P2 + handoff.** That is safe (they are handoffs anyway), but a bug with an
  undocumented workaround is P2, never P3.
- **`fix_in_help_centre` can be generous** (the model once cited the status page as a "fix" for an outage). Next step:
  require the cited section to describe the customer's cause.
- **Self-reported model confidence is uninformative** (almost always 0.95–1.00), so no decision depends on it alone.

## Decisions at a glance

1. Build the eval first; every later change is measured against it.
2. Local Qwen 3.5 2B rejected (30%); Gemini used.
3. `gemini-3.5-flash-lite` over `gemini-3.5-flash`: more accurate, stable, ~4× fewer output tokens, 5× faster.
4. Priority is calculated in code from facts the LLM extracts (80% → 100%).
5. Fix one observed error at a time (v2 → v3 → v4); when a judgement is vague, split it into verifiable facts.
6. Language detected locally in code with `lingua` (nl/en/de only, quotes removed, unsure → handoff), not by the LLM;
   a second all-language check sends tickets in other languages to a human. Tested with a free language eval
   (66/68 correct, 0 wrong).
7. Dutch written directly and checked via English back-translation.
8. Result: 100% on all four fields, 0 safety violations, ≈ €0.15 per 100 tickets.
