# Eval `after-v3-flash-lite`: 2026-11-17T18:29:21+00:00

classifier `llm` · model `gemini-3.5-flash-lite` · threshold 0.7 · n=10 · tokens 28145 in / 2930 out

| metric | score |
|---|---|
| language | 100% |
| category | 100% |
| priority | 90% |
| action | 100% |
| all four correct | 90% |
| **safety violations** | **0** |

| id | label (lang/cat/prio/action) | predicted | ok | safety |
|---|---|---|---|---|
| E01 | en/bug/P3/reply | en/bug/P2/reply | ✓✓✗✓ |  |
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

overall fact accuracy: **98%**  ·  many_users_blocked 100%  ·  security_or_legal_risk 100%  ·  money_or_contract_dispute 100%  ·  privacy_request 100%  ·  something_broken 100%  ·  cosmetic_only 100%  ·  workaround_available 50%

| id | facts the model said are true | priority basis | wrong facts |
|---|---|---|---|
| E01 | something_broken, workaround=False | something broken, no workaround: customer blocked | workaround_available |
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

Thanks for reaching out. Roosterly requires iOS 16 or later to run on Apple devices.

Team Roosterly

EN: Hi,

Thanks for reaching out. Roosterly requires iOS 16 or later to run on Apple devices.

Team Roosterly

**E02** (F06)

> Hoi,

Je kunt je bedrijfsnaam, adres of btw-nummer zelf aanpassen voor toekomstige facturen onder Instellingen → Bedrijfsgegevens (Settings → Company details).

Team Roosterly

EN: Hi,

You can update your company name, address, or VAT number yourself for future invoices under Settings → Company details (Settings → Company details).

Team Roosterly

**E04** (F03)

> Hoi,

Om een dienst te ruilen, open je de dienst in de app en tik je op "Ruil aanbieden". Collega's met dezelfde rol kunnen de ruil accepteren. De manager keurt dit goed onder Rooster → Verzoeken.

Team Roosterly

EN: Hi,

To swap a shift, you open the shift in the app and tap "Offer swap". Colleagues with the same role can accept the swap. The manager approves this under Rota → Requests.

Team Roosterly

**E05** (F10)

> Hoi,

Bedankt voor je idee! We lezen elk idee en featureaanvragen gaan op onze openbare roadmap op roadmap.roosterly.nl, waar je op ideeën kunt stemmen. We kunnen echter geen leverdatum beloven voor individuele verzoeken.

Team Roosterly

EN: Hi,

Thanks for your idea! We read every idea and feature requests go on our public roadmap at roadmap.roosterly.nl, where you can vote on ideas. However, we cannot promise a delivery date for individual requests.

Team Roosterly

**E07** (F05)

> Hoi,

Plus kost €6 per actieve medewerker per maand (exclusief btw). Je kunt op elk moment upgraden onder Instellingen → Abonnement (Settings → Subscription); de nieuwe prijs geldt vanaf de volgende factuur.

Team Roosterly

EN: Hi,

Plus costs €6 per active employee per month (excluding VAT). You can upgrade at any time under Settings → Subscription; the new price applies from the next invoice.

Team Roosterly

**E10** (F11)

> Hoi,

Je kunt de actuele storingen en geplande onderhoudswerkzaamheden bekijken op status.roosterly.nl.

Team Roosterly

EN: Hi,

You can view current outages and planned maintenance activities on status.roosterly.nl.

Team Roosterly
