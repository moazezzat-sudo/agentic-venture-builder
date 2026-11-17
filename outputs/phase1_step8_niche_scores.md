# Phase 1, step 8: rubric scores (round 1)

| Criterion | Weight | Score (0-4) | Claims | Reasoning |
|---|---|---|---|---|
| problem_evidence | 20% | 1 | C1 | Only one low‑tier source shows manual scheduling; no strong data on frequency or cost. |
| market | 15% | 1 | C5 | Population and internet use are given, but no data on number of target SME HR teams. |
| competition | 15% | 1 | - | A free booking system claim suggests a free tool already addresses the need. (raised to 1: a 0 needs a sourced claim that a free tool solves it) |
| founder_fit | 15% | 3 | - | Founder has Python/web dev skills and HR operations experience matching product needs. |
| feasibility | 15% | 3 | - | MVP can be built with stated budget and weekly hours using the founder's skills. |
| willingness_to_pay | 10% | 1 | - | No evidence that SMEs would pay for this SaaS; only free tool claim present. |
| rules_risk | 10% | 3 | - | Allowed digital product in a regulated area: confirm the official rules before launch. |

A score above 1 on problem evidence, competition, willingness to pay or market must cite a claim of the matching evidence type. Rules and risk comes from the guardrails, not the model. Weights and cut-offs are our design choices (rubric.yaml).

## Claims

0. [C1 · pain] Community signal: User schedules interviews by emailing candidates with available slots and collecting their responses. (problem_evidence; tier D, [https://www.reddit.com/r/recruiting/comments/ylvksb/looking_for_a_specific_kind_of_scheduling_tool/](https://www.reddit.com/r/recruiting/comments/ylvksb/looking_for_a_specific_kind_of_scheduling_tool/), read 2026-11-17T21:54:12Z)
1. [C2 · pain] Arabic article describes an interview scheduling automation platform simplifying logistics for hiring managers, interviewers, and candidates. (problem_evidence; tier B, [https://www.mokahr.io/articles/ar/the-best-interview-scheduling-automation-tool](https://www.mokahr.io/articles/ar/the-best-interview-scheduling-automation-tool), read 2026-11-17T21:54:12Z)
2. [C3 · pain] Community signal: Arabic list of top 5 interview scheduling automation tools for 2026. (problem_evidence; tier D, [https://www.linkedin.com/pulse/5-best-tools-automating-interview-scheduling-2026-harry-portch-0wgpe?tl=ar](https://www.linkedin.com/pulse/5-best-tools-automating-interview-scheduling-2026-harry-portch-0wgpe?tl=ar), read 2026-11-17T21:54:12Z)
3. [C4 · pricing] Free booking system & appointment scheduling software, start free, no per-seat fees. (willingness_to_pay; tier B, [https://www.supersaas.com/](https://www.supersaas.com/), read 2026-11-17T21:54:05Z)
4. [C5 · market] Population, total in EG, 2025: 118,365,995.0 (World Bank). (market; tier A, [https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1](https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1), read 2026-11-17T21:54:04Z)
5. [C6 · market] Individuals using the Internet (% of population) in EG, 2024: 74.6 (World Bank). (market; tier A, [https://api.worldbank.org/v2/country/EG/indicator/IT.NET.USER.ZS?format=json&mrnev=1](https://api.worldbank.org/v2/country/EG/indicator/IT.NET.USER.ZS?format=json&mrnev=1), read 2026-11-17T21:54:04Z)
