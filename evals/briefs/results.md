# Phase 1 brief evaluation: Gate 1 recommendations

Run at 2026-11-17 15:33 UTC with `groq` (`openai/gpt-oss-120b` / `openai/gpt-oss-20b`), real web search. Produced by `python evals/briefs/run_briefs.py`; briefs in `evals/briefs/briefs.json`. Each run stops at Gate 1 with no founder decision made.

**5 of 7 as expected.**

| Brief | Set | Expected | Got | Score | As expected | Seconds | Tokens |
|---|---|---|---|---|---|---|---|
| S1: Interview-scheduling SaaS for SMEs in Egypt | strong | not stop | stop | 1.95 | **no** | 10.5 | 7604 |
| S2: An online table-booking widget for restaurants and cafés | strong | not stop | stop | 2.05 | **no** | 8.0 | 7743 |
| S3: A CV and portfolio builder for fresh graduates | strong | not stop | repeat | 2.05 | yes | 5.7 | 6688 |
| W1: A website that converts PDF files to Word documents | weak (free tool already solves it) | stop | stop | 1.75 | yes | 19.2 | 6625 |
| W2: An app that reminds people to water their artificial plants | weak (no evidence of the pain) | stop | stop | 1.80 | yes | 27.6 | 7106 |
| W3: A route-optimisation SaaS for shipping and logistics companies | weak (poor founder fit) | stop | stop | 0.95 | yes | 15.7 | 6528 |
| B1: A mobile app that lets people buy fractions of Bitcoin with their phone credit | banned | stop | stop | n/a | yes | 0.1 | 0 |

## Gate 1 reasons

**S1** (stop):
- Weighted score 1.95 is below 2.0.
- Weakest criteria: market 1, competition 1.
- Target missed: only 2 independent source(s) show the pain (target 3).

**S2** (stop):
- competition scored 0, which stops the idea whatever the total.

**S3** (repeat):
- Weighted score 2.05 is between 2.0 and 2.8; problem evidence (2) is too thin, so more evidence is needed.
- Weakest criteria: market 0, competition 1.

**W1** (stop):
- problem_evidence scored 0, which stops the idea whatever the total.
- competition scored 0, which stops the idea whatever the total.

**W2** (stop):
- competition scored 0, which stops the idea whatever the total.

**W3** (stop):
- Weighted score 0.95 is below 2.0.
- Weakest criteria: market 0, founder_fit 0.
- Target missed: founder fit 0 is below 2.

**B1** (stop):
- Financial, investment and crypto products are banned: the system can't build products that handle, invest or advise on money or digital assets. (Rule matched: "buy fractions of Bitcoin".)
