# Phase 1, step 6: rubric scores (round 1)

| Criterion | Weight | Score (0-4) | Claims | Reasoning |
|---|---|---|---|---|
| problem_evidence | 20% | 2 | C1, C2, C3 | Three independent B‑tier sources cite the same PDF‑to‑Word pain. |
| market | 15% | 1 | C6, C7 | Only total population and internet penetration are given; no specific university‑student figures. |
| competition | 15% | 0 | C4 | A free converter app already solves the exact problem. |
| founder_fit | 15% | 3 | - | Python skill matches the technical needs of a simple web converter. |
| feasibility | 15% | 3 | - | Budget and time are sufficient for an MVP using existing libraries. |
| willingness_to_pay | 10% | 0 | - | No evidence of payment intent; skeptic check shows users prefer free tools. |
| rules_risk | 10% | 3 | - | Allowed digital product in a regulated area: confirm the official rules before launch. |

A score above 1 on problem evidence, competition, willingness to pay or market must cite a claim of the matching evidence type. Rules and risk comes from the guardrails, not the model. Weights and cut-offs are our design choices (rubric.yaml).

## Claims

0. [C1 · pain] حوّل ملفات PDF إلى DOC و DOCX للتعديل عليها بسهولة. (problem_evidence; tier B, [https://www.ilovepdf.com/ar/pdf_to_word](https://www.ilovepdf.com/ar/pdf_to_word), read 2026-11-17T21:55:39Z)
1. [C2 · pain] تحويل PDF إلى Word - مجاناً باستخدامConvert Academic PDF to Word for University Students ...تحويل ملف PDF إلى Word مجان… (problem_evidence; tier B, [https://smallpdf.com/ar/pdf-to-word](https://smallpdf.com/ar/pdf-to-word), read 2026-11-17T21:55:39Z)
2. [C3 · pain] تحويل ملف PDF إلى Word مجانًا - محوّل ملف PDF إلى DOCX (problem_evidence; tier B, [https://www.adobe.com/eg_ar/acrobat/online/pdf-to-word.html](https://www.adobe.com/eg_ar/acrobat/online/pdf-to-word.html), read 2026-11-17T21:55:39Z)
3. [C4 · competitors] Converter App: Free File Converter (1GB+) supports PDF to Word conversion and is free. (competition; tier B, [https://converter.app/](https://converter.app/), read 2026-11-17T21:55:24Z)
4. [C5 · competitors] File Converter app from Online-Convert.com offers PDF to Word conversion in the cloud. (competition; tier B, [https://play.google.com/store/apps/details?id=com.onlineconvert.ocapp&hl=en-US](https://play.google.com/store/apps/details?id=com.onlineconvert.ocapp&hl=en-US), read 2026-11-17T21:55:24Z)
5. [C6 · market] Population, total in EG, 2025: 118,365,995.0 (World Bank). (market; tier A, [https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1](https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1), read 2026-11-17T21:55:23Z)
6. [C7 · market] Individuals using the Internet (% of population) in EG, 2024: 74.6 (World Bank). (market; tier A, [https://api.worldbank.org/v2/country/EG/indicator/IT.NET.USER.ZS?format=json&mrnev=1](https://api.worldbank.org/v2/country/EG/indicator/IT.NET.USER.ZS?format=json&mrnev=1), read 2026-11-17T21:55:23Z)
