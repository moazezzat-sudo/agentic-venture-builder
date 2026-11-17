# Phase 1 brief evaluation: Gate 1 recommendations

Run at 2026-11-17 14:57 UTC with `groq` (`openai/gpt-oss-120b` / `openai/gpt-oss-20b`), real web search. Produced by `python evals/briefs/run_briefs.py`; briefs in `evals/briefs/briefs.json`. Each run stops at Gate 1 with no founder decision made.

**5 of 7 as expected.**

| Brief | Set | Expected | Got | Score | As expected | Seconds | Tokens |
|---|---|---|---|---|---|---|---|
| S1: Interview-scheduling SaaS for SMEs in Egypt | strong | not stop | pivot | 2.30 | yes | 13.8 | 5445 |
| S2: An online table-booking widget for restaurants and cafés | strong | not stop | stop | 1.90 | **no** | 10.2 | 4638 |
| S3: A CV and portfolio builder for fresh graduates | strong | not stop | stop | 1.45 | **no** | 9.9 | 5677 |
| W1: A website that converts PDF files to Word documents | weak (free tool already solves it) | stop | stop | 2.10 | yes | 6.5 | 5494 |
| W2: An app that reminds people to water their artificial plants | weak (no evidence of the pain) | stop | stop | 1.90 | yes | 10.3 | 5997 |
| W3: A route-optimisation SaaS for shipping and logistics companies | weak (poor founder fit) | stop | stop | 1.30 | yes | 21.9 | 5900 |
| B1: A mobile app that lets people buy fractions of Bitcoin with their phone credit | banned | stop | stop | n/a | yes | 0.1 | 0 |

## Gate 1 reasons

**S1** (pivot):
- Weighted score 2.30 is between 2.0 and 2.8; the pain looks real (problem evidence 3) but the idea as framed scores low.
- Weakest criteria: market 1, competition 1.

**S2** (stop):
- Weighted score 1.90 is below 2.0.
- Weakest criteria: problem_evidence 1, market 1.
- Target missed: only 1 independent source(s) show the pain (target 3).

**S3** (stop):
- problem_evidence scored 0, which stops the idea whatever the total.

**W1** (stop):
- competition scored 0, which stops the idea whatever the total.

**W2** (stop):
- Weighted score 1.90 is below 2.0.
- Weakest criteria: problem_evidence 1, market 1.
- Target missed: only 1 independent source(s) show the pain (target 3).

**W3** (stop):
- Weighted score 1.30 is below 2.0.
- Weakest criteria: founder_fit 0, feasibility 0.
- Target missed: founder fit 0 is below 2.

**B1** (stop):
- Financial, investment and crypto products are banned: the system can't build products that handle, invest or advise on money or digital assets. (Rule matched: "buy fractions of Bitcoin".)
