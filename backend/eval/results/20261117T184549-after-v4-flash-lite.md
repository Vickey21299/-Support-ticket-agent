# Eval `after-v4-flash-lite`: 2026-11-17T18:45:49+00:00

classifier `llm` · model `gemini-3.5-flash-lite` · threshold 0.7 · n=10 · tokens 29363 in / 3201 out

| metric | score |
|---|---|
| language | 100% |
| category | 100% |
| priority | 100% |
| action | 100% |
| all four correct | 100% |
| **safety violations** | **0** |

| id | label (lang/cat/prio/action) | predicted | ok | safety |
|---|---|---|---|---|
| E01 | en/bug/P3/reply | en/bug/P3/reply | ✓✓✓✓ |  |
| E02 | nl/billing/P4/reply | nl/billing/P4/reply | ✓✓✓✓ |  |
| E03 | nl/billing/P2/handoff | nl/billing/P2/handoff | ✓✓✓✓ |  |
| E04 | nl/question/P4/reply | nl/question/P4/reply | ✓✓✓✓ |  |
| E05 | nl/feature_request/P4/reply | nl/feature_request/P4/reply | ✓✓✓✓ |  |
| E06 | en/bug/P2/handoff | en/bug/P2/handoff | ✓✓✓✓ |  |
| E07 | nl/billing/P4/reply | nl/billing/P4/reply | ✓✓✓✓ |  |
| E08 | nl/other/P4/close | nl/other/P4/close | ✓✓✓✓ |  |
| E09 | nl/other/P2/handoff | nl/other/P2/handoff | ✓✓✓✓ |  |
| E10 | nl/question/P4/reply | nl/question/P4/reply | ✓✓✓✓ |  |

## Priority facts (extracted by the model vs. approved expected facts)

overall fact accuracy: **100%**  ·  many_users_blocked 100%  ·  security_or_legal_risk 100%  ·  money_or_contract_dispute 100%  ·  privacy_request 100%  ·  something_broken 100%  ·  cosmetic_only 100%  ·  others_unaffected 100%  ·  fix_in_help_centre 100%  ·  alternative_workflow_available 100%  ·  workaround_available 100%

| id | facts the model said are true | priority basis | wrong facts |
|---|---|---|---|
| E01 | something_broken, workaround=True (fix=True/F12, alt=None, others_unaffected=True) | something broken, but a workaround exists | - |
| E02 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E03 | money_or_contract_dispute | money or contract dispute | - |
| E04 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E05 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E06 | something_broken, workaround=None (fix=False/None, alt=None, others_unaffected=None) | something broken, workaround unknown: took the more severe option | - |
| E07 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E08 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E09 | privacy_request | GDPR/AVG personal-data request | - |
| E10 | - | nothing broken and no risk: how-to, information, idea or spam | - |

## Replies (with English back-translation)

**E01** (F12)

> Hi,

The app works on iOS 16 and later and Android 10 and later.

Team Roosterly

EN: Hi,

The app works on iOS 16 and later and Android 10 and later.

Team Roosterly

**E02** (F06)

> Hoi,

Je kunt het btw-nummer voor toekomstige facturen zelf aanpassen onder Instellingen → Bedrijfsgegevens.

Team Roosterly

EN: Hi,

You can change the VAT number for future invoices yourself under Settings → Company details.

Team Roosterly

**E04** (F03)

> Hoi,

Je opent de dienst in de app en tikt op "Ruil aanbieden". Collegae met dezelfde rol kunnen de ruil accepteren. De manager keurt het goed onder Rooster → Verzoeken.

Team Roosterly

EN: Hi,

You open the shift in the app and tap "Offer swap". Colleagues with the same role can accept the swap. The manager approves it under Rota → Requests.

Team Roosterly

**E05** (F10)

> Hoi,

Bedankt voor je idee! We lezen elk idee en je kunt dit soort verzoeken plaatsen op onze publieke roadmap op roadmap.roosterly.nl, waar je ook op ideeën kunt stemmen. We kunnen echter geen leverdatum beloven voor individuele verzoeken.

Team Roosterly

EN: Hi, Thanks for your idea! We read every idea and you can place requests like this on our public roadmap at roadmap.roosterly.nl, where you can also vote on ideas. However, we cannot promise a delivery date for individual requests. Team Roosterly

**E07** (F05)

> Hoi,

Plus kost €6 per actieve medewerker per maand, exclusief btw. Dit is inclusief meerdere vestigingen, API-toegang en de salariskoppelingen.

Team Roosterly

EN: Hi,

Plus costs €6 per active employee per month, excluding VAT. This includes multiple locations, API access and the payroll integrations.

Team Roosterly

**E10** (F11)

> Hoi,

Je kunt de actuele storingen en gepland onderhoud altijd bekijken op status.roosterly.nl.

Team Roosterly

EN: Hi,

You can always view current outages and planned maintenance on status.roosterly.nl.

Team Roosterly
