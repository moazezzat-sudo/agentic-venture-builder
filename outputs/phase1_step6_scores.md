# Phase 1, step 6: rubric scores (round 1)

| Criterion | Weight | Score (0-4) | Claims | Reasoning |
|---|---|---|---|---|
| problem_evidence | 20% | 0 | - | no evidence |
| market | 15% | 1 | C1, C2 | Population and internet penetration are given but not specific to university students. |
| competition | 15% | 1 | - | no evidence of competitors |
| founder_fit | 15% | 2 | - | founder knows python, suitable for a simple web converter, but lacks design/UX experience. |
| feasibility | 15% | 3 | - | MVP can be built with python tools within $100 and 10 h/week. |
| willingness_to_pay | 10% | 0 | - | no evidence |
| rules_risk | 10% | 3 | - | Allowed digital product in a regulated area: confirm the official rules before launch. |

A score above 1 on problem evidence, competition, willingness to pay or market must cite a claim of the matching evidence type. Rules and risk comes from the guardrails, not the model. Weights and cut-offs are our design choices (rubric.yaml).

## Claims

0. [C1 · market] Population, total in EG, 2025: 118,365,995.0 (World Bank). (market; tier A, [https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1](https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1), read 2026-11-17T20:55:33Z)
1. [C2 · market] Individuals using the Internet (% of population) in EG, 2024: 74.6 (World Bank). (market; tier A, [https://api.worldbank.org/v2/country/EG/indicator/IT.NET.USER.ZS?format=json&mrnev=1](https://api.worldbank.org/v2/country/EG/indicator/IT.NET.USER.ZS?format=json&mrnev=1), read 2026-11-17T20:55:33Z)
