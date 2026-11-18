# Future work

What we would build next, why, and how we would decide whether it ships.
Every item comes from a measured weakness (see [`backend/eval/RESULTS.md`](backend/eval/RESULTS.md) §6) or a design
option we built but did not evaluate. Nothing here is implemented in the submitted version unless it says so.

**The rule for every item:** run the same eval before and after. An item **ships (go)** only if it meets its acceptance
criteria *and* keeps the existing bar:

> all-four accuracy ≥ the current 100% on the labelled examples · **0 safety violations** · 0 WRONG in the language
> eval · all client rule checks pass on the 30 practice tickets · cost ≤ €1 per 100 tickets.

If it misses the bar, it does **not** ship (no-go), and we keep the result in `RESULTS.md` as a documented experiment.

## Priority order

| # | Goal | Why (evidence) | Effort | Risk |
|---|---|---|---|---|
| 1 | More labelled tickets | 10 examples: 1 ticket = 10 points | low | none |
| 2 | Calibrated "unsure" signal (Jev, limited role) | model confidence is almost always 0.95–1.00 | medium | low |
| 3 | Stricter help-centre "fix" check | the model cited the status page as a "fix" for an outage | low | low |
| 4 | Fewer bugs stuck at "workaround unknown" | most real bugs → P2 + handoff | medium | medium |
| 5 | Clear "threat to leave" rule | vague rule hands off most annoyed customers | low (client decision) | none |
| 6 | Cheaper path for tickets that are handed off anyway | the LLM still runs on rule-forced handoffs | medium | low |
| 7 | Production feedback loop | no learning from human corrections yet | high | none |

## 1. More labelled tickets

- **Why:** the eval has 10 labelled examples, so one ticket moves a score by 10 points. 100% on 10 is strong evidence
  but a small sample.
- **What:** have a support lead label the 30 practice tickets (language, category, priority, action), the same way
  Nordavo labelled `/examples`. Never use the model's own output as a label. Then score on 40 tickets.
- **Accept (go) if:** the labels are written and approved by a human, and the eval runs on all 40. This item changes
  the measurement, not the agent, so it always ships; any errors it reveals become the next items.

## 2. Calibrated "unsure" signal: Jev in a limited role

- **Why:** Gemini's self-reported confidence is uninformative (0.95–1.00 almost always), so it cannot tell us when to
  hand off. Safety today comes from the rules, facts and verifier, not from that number.
- **What we already have:** a Jev decider ([`jev_classifier.py`](backend/app/pipeline/jev_classifier.py),
  `CLASSIFIER=jev`) that returns a real probability per option. It is built and unit-tested with a fake SDK, but has
  **never run on real tickets** (it needs `TYPESAFE_API_KEY` and `typesafe-sdk`).
- **What we would change:** use Jev only for **action** and **needs_review**, as an extra check that can only make the
  agent more careful (low probability for `reply` → handoff). Language stays in code (local `lingua`), and priority stays
  calculated from facts: both already beat a model label (priority went 80% → 100% when a model stopped picking it).
- **Accept (go) if:** the existing bar holds, **and** on the eval the Jev probability separates right from wrong
  decisions (errors get clearly lower probabilities than correct ones), **and** it does not turn more than one correct
  reply into a handoff. Cost: one extra call per ticket, must stay under €1 per 100.
- **No-go if:** its probabilities are as flat as Gemini's, or it blocks good replies. Then it stays an option, not the default.

## 3. Stricter help-centre "fix" check

- **Why:** `fix_in_help_centre` can be generous. On the outage ticket the model cited F11 (status page) as a "fix". It
  had no effect there (P1 is checked first), but it could lift a smaller bug from P2 to P3.
- **What:** the cited `fix_section` must describe the customer's *cause*, not just a related topic: a check by the
  verifier or a keyword match between the ticket's symptom and the section text.
- **Accept (go) if:** the existing bar holds, fact accuracy stays 100%, and the outage case no longer counts as "fix found".

## 4. Fewer bugs stuck at "workaround unknown"

- **Why:** the model usually leaves `alternative_workflow_available` empty, and "other staff are fine" deliberately does
  not count as a workaround. So most real bugs become P2 + handoff. That is safe (bugs are handed off anyway), but a bug
  with an undocumented workaround is P2, never P3.
- **What:** add short, verifiable workaround examples per FAQ area to the prompt, or a question that asks for the
  concrete alternative steps (and treats an empty answer as unknown).
- **Accept (go) if:** the existing bar holds, priority accuracy stays 100%, and no ticket gets a *lower* priority without
  a quoted workaround as evidence. Priority may only drop with evidence, never by default.

## 5. Clear "threat to leave" rule (client decision)

- **Why:** "threat to leave" is in the client's always-a-human list, but it is vague: read literally, it hands off most
  annoyed customers, including ones the FAQ could answer.
- **What:** ask Nordavo/Roosterly for a concrete definition, e.g. "explicitly says they will cancel or switch". Then
  tighten the keyword rule in [`rules.py`](backend/app/pipeline/rules.py) to match.
- **Accept (go) if:** the client confirms the definition in writing and the rule checks still pass. We do not change a
  client rule on our own.

## 6. Cheaper path for tickets that are handed off anyway

- **Why:** when a deterministic rule already forces a handoff (refund, GDPR, security, legal), the LLM still runs to
  extract facts and write the English handoff note.
- **What:** measure first how many tickets are rule-forced handoffs and what they cost. If that is significant, test a
  smaller or cheaper call for them, while keeping a useful handoff note for the human.
- **Accept (go) if:** cost per 100 tickets goes down measurably, the existing bar holds, and a human reviewer rates the
  handoff notes as no worse. No-go if the notes lose information the support team needs.

## 7. Production feedback loop

- **Why:** today the agent does not learn from what humans do after a handoff, or from corrected replies.
- **What:** log the human's final category, priority and action on handed-off tickets (no ticket bodies or payment data
  in the logs). Periodically turn those into new labelled eval cases, and alert when the share of handoffs, or of
  language "unsure" results, changes sharply.
- **Accept (go) if:** it adds no personal or payment data to the logs, and each new batch of labels is reviewed by a
  human before it enters the eval.

## Out of scope (decided)

- **Replies in languages other than nl/en/de.** The helpdesk API accepts only these three. A ticket in another language
  is detected locally and goes to a human instead of getting a reply in the wrong language. If the API ever accepts
  more languages, that detection is the starting point.
- **Replacing deterministic decisions with a model.** Language detection and the P1–P4 calculation stay in code. A model
  may add caution (force a handoff), never remove it.
