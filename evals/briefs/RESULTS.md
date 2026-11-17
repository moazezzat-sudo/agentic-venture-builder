# Evaluation results

Every number below comes from a real run of the pipeline (saved in `brief_runs.json` and `full_path.json` next to this file). Nothing is written by hand.

## Gate 1 on the evaluation briefs

Run at 2026-11-17 16:27 UTC with `groq` (`openai/gpt-oss-120b` / `openai/gpt-oss-20b`), real web search, up to 2 run(s) per brief. Produced by `python evals/briefs/run_briefs.py`; briefs in `evals/briefs/briefs.json`. Each run stops at Gate 1 with no founder decision made.

**6 of 7 briefs as expected on every run.**

| Brief | Set | Expected | Got (each run) | Same each run | As expected | Score | Seconds | Tokens | Research ran |
|---|---|---|---|---|---|---|---|---|---|
| S1: Interview-scheduling SaaS for SMEs in Egypt | strong | not stop | repeat | yes | yes | 2.10 | 9.5 | 7743 | yes |
| S2: An online table-booking widget for restaurants and cafés | strong | not stop | stop | yes | **no** | 2.15 | 6.7 | 8228 | yes |
| S3: A CV and portfolio builder for fresh graduates | strong | not stop | repeat | yes | yes | 2.05 | 9.4 | 6509 | yes |
| W1: A website that converts PDF files to Word documents | weak (free tool already solves it) | stop | stop, stop | yes | yes | 1.45, 1.45 | 15.7, 23.6 | 6706, 6686 | yes, yes |
| W2: An app that reminds people to water their artificial plants | weak (no evidence of the pain) | stop | stop, stop | yes | yes | 1.70, 1.70 | 21.7, 21.6 | 7213, 7234 | yes, yes |
| W3: A route-optimisation SaaS for shipping and logistics companies | weak (poor founder fit) | stop | stop, stop | yes | yes | 0.95, 1.30 | 22.7, 29.0 | 6890, 7501 | yes, yes |
| B1: A mobile app that lets people buy fractions of Bitcoin with their phone credit | banned | stop | stop, stop | yes | yes | n/a, n/a | 0.3, 0.2 | 0, 0 | no, no |

### Gate 1 reasons (last run of each brief)

**S1** (repeat):
- Weighted score 2.10 is between 2.0 and 2.8; problem evidence (2) is too thin, so more evidence is needed.
- Weakest criteria: market 1, competition 1.

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
- Weighted score 1.30 is below 2.0.
- Weakest criteria: founder_fit 0, feasibility 0.
- Target missed: founder fit 0 is below 2.

**B1** (stop):
- Financial, investment and crypto products are banned: the system can't build products that handle, invest or advise on money or digital assets. (Rule matched: "buy fractions of Bitcoin".)

## One brief through every phase

Run at 2026-11-17 16:28 UTC with `groq` (`openai/gpt-oss-120b` / `openai/gpt-oss-20b`): brief S1, Gate 1 -> niche gate -> Phases 2-6 -> finish. Produced by `python evals/briefs/run_full_path.py`. This is a pipeline test, so the script plays the founder: it approves where the gate recommends go and otherwise overrides to go (logged as a founder override), so every phase is reached. At Gate 2 it sets a waitlist target and enters no real count (none is invented), so Gate 2 recommends repeat.

Ended in Phase 6, stopped: False. **Total: 54.5 s of machine time, 20,915 tokens.**

| Phase | Seconds | Tokens |
|---|---|---|
| 1 | 19.8 | 11,166 |
| 2 | 2.3 | 1,577 |
| 3 | 6.4 | 4,156 |
| 4 | 7.5 | 1,615 |
| 5 | 11.8 | 1,610 |
| 6 | 6.6 | 791 |

| Gate | Recommended | Chosen | Override |
|---|---|---|---|
| gate_1 | repeat | go | yes |
| gate_1_niche | stop | go | yes |
| gate_2 | repeat | go | yes |
| gate_3_plan | go | go | no |
| gate_3 | go | go | no |
| gate_4 | repeat | go | yes |
| gate_5 | go | go | no |
| gate_6 | repeat | go | yes |
