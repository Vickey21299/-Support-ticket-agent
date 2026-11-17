# Eval `after-v2-flash-lite`: 2026-11-17T18:08:03+00:00

classifier `llm` · model `gemini-3.5-flash-lite` · threshold 0.7 · n=10 · tokens 27371 in / 2901 out

| metric | score |
|---|---|
| language | 100% |
| category | 100% |
| priority | 100% |
| action | 90% |
| all four correct | 90% |
| **safety violations** | **0** |

| id | label (lang/cat/prio/action) | predicted | ok | safety |
|---|---|---|---|---|
| E01 | en/bug/P3/reply | en/bug/P3/reply | ✓✓✓✓ |  |
| E02 | nl/billing/P4/reply | nl/billing/P4/reply | ✓✓✓✓ |  |
| E03 | nl/billing/P2/handoff | nl/billing/P2/handoff | ✓✓✓✓ |  |
| E04 | nl/question/P4/reply | nl/question/P4/reply | ✓✓✓✓ |  |
| E05 | nl/feature_request/P4/reply | nl/feature_request/P4/reply | ✓✓✓✓ |  |
| E06 | en/bug/P2/handoff | en/bug/P2/handoff | ✓✓✓✓ |  |
| E07 | nl/billing/P4/reply | nl/billing/P4/handoff | ✓✓✓✗ |  |
| E08 | nl/other/P4/close | nl/other/P4/close | ✓✓✓✓ |  |
| E09 | nl/other/P2/handoff | nl/other/P2/handoff | ✓✓✓✓ |  |
| E10 | nl/question/P4/reply | nl/question/P4/reply | ✓✓✓✓ |  |

## Priority facts (extracted by the model vs. approved expected facts)

overall fact accuracy: **100%**  ·  many_users_blocked 100%  ·  security_or_legal_risk 100%  ·  money_or_contract_dispute 100%  ·  privacy_request 100%  ·  something_broken 100%  ·  workaround_available 100%

| id | facts the model said are true | priority basis | wrong facts |
|---|---|---|---|
| E01 | something_broken, workaround=True | something broken, but a workaround exists | - |
| E02 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E03 | money_or_contract_dispute | money or contract dispute | - |
| E04 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E05 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E06 | something_broken, workaround=False | something broken, no workaround: customer blocked | - |
| E07 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E08 | - | nothing broken and no risk: how-to, information, idea or spam | - |
| E09 | privacy_request | GDPR/AVG personal-data request | - |
| E10 | - | nothing broken and no risk: how-to, information, idea or spam | - |

## Replies (with English back-translation)

**E01** (F12)

> Hi,

The app works on iOS 16 and later and Android 10 and later. Please update your device's operating system to use Roosterly.

Team Roosterly

EN: Hi,

The app works on iOS 16 and later and Android 10 and later. Please update your device's operating system to use Roosterly.

Team Roosterly

**E02** (F06)

> Hoi,

Je kunt de bedrijfsnaam, het adres of het btw-nummer voor toekomstige facturen zelf aanpassen onder Instellingen → Bedrijfsgegevens (Settings → Company details).

Team Roosterly

EN: Hi,

You can change the company name, address, or VAT number for future invoices yourself under Settings → Company details (Instellingen → Bedrijfsgegevens).

Team Roosterly

**E04** (F03)

> Hoi,

Je opent de dienst in de app en tikt op "Ruil aanbieden". Collega's met dezelfde rol kunnen de ruil accepteren. De manager keurt het goed onder Rooster → Verzoeken (Rota → Requests). Goedkeuring door de manager staat standaard aan; je kunt dit uitzetten onder Instellingen → Rooster (Settings → Rota).

Team Roosterly

EN: Hi,

You open the shift in the app and tap "Offer swap". Colleagues with the same role can accept the swap. The manager approves it under Rota → Requests. Manager approval is on by default; you can turn it off under Settings → Rota.

Team Roosterly

**E05** (F10)

> Hoi,

Bedankt voor je idee! We lezen elk idee en featureaanvragen komen op onze publieke roadmap op roadmap.roosterly.nl, waar je op ideeën kunt stemmen. We kunnen geen leverdatum beloven voor individuele verzoeken.

Team Roosterly

EN: Hi,

Thanks for your idea! We read every idea and feature requests go on our public roadmap at roadmap.roosterly.nl, where you can vote on ideas. We cannot promise a delivery date for individual requests.

Team Roosterly

**E10** (F11)

> Hoi,

Je kunt de actuele storingen en gepland onderhoud altijd bekijken op status.roosterly.nl.

Team Roosterly

EN: Hi,

You can always view current outages and planned maintenance on status.roosterly.nl.

Team Roosterly
