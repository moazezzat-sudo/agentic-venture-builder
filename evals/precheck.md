# Pre-push check (trial run)

A trial run of CLAUDE.md's "Before every push" checklist against `main` at commit `eb6bc58`, on 2026-11-17. Each gap has an owner. The check was stopped part-way when the local model finished downloading; the checks not run yet are listed at the end.

## Gaps

| # | Gap | Owner | Due |
|---|---|---|---|
| 1 | `decision_log.json` is missing at the root. It must hold the committed demo run, with all 5 keys in every entry. | Eyad (demo run) | 21:00–22:30 demo runs |
| 2 | `outputs/` has no gate decision and no phase files: only `payment_test_log.md`. The demo runs need a strong idea and a weak idea that ends in **stop** (`outputs/phase1_gate_decision.md`). | Eyad (demo run) | 21:00–22:30 |
| 3 | The MOCKED sale-to-cash run isn't in `decision_log.json`. Run `python payments.py` as part of the final demo run. | Hashish | Final demo run |
| 4 | Demo video: the README says "Not recorded yet". It needs a YouTube, Vimeo, Loom or Drive link, 3 minutes at most. | Moaz | 22:30 |
| 5 | The README "What works and what is mocked" table is out of date: the orchestrator and all three Phase 1 rows say "STUBBED, Not built yet" although they are built and tested (`tests/test_orchestrator.py`); Validate, Build, Commercial setup and Operate rows say "Not built yet" although STUBBED draft agents exist (`tests/test_phase_agents.py`). The Phase 3 build step has no row. | Moaz | Before the 21:00 freeze |
| 6 | After gap 5, copy the README table into ARCHITECTURE.md "Built vs. stubbed" so the two stay identical, and add `tests/test_status_tables.py` to enforce it. | Hashish | After gap 5 |
| 7 | A grep for `gsk_` or `sk_` finds fake keys in the current tree: test fixtures in `tests/test_guardrails.py` (`gsk_abc…`, `sk_live_abc…`) and a regex in `guardrails.py`. None are real keys, but a plain grep can't tell. Fix: build the fake keys at runtime and write the regex without the literal prefix. | Hashish | Next push |
| 8 | Git history: commit `9c8404d` has `STRIPE_TEST_SECRET_KEY=sk_test_placeholder_only_do_not_use_live_keys` and `FREE_TIER_LLM_API_KEY=your_free_tier_api_key_placeholder_here` in `.env.example`. These are placeholders, not keys, and the current `.env.example` has neither. Removing them would mean rewriting shared history with a force push, so the recommendation is to leave them. | Moaz (decide) | — |
| 9 | Cost per run says `$0.00 per run` (the `$` figure is there), but the token count per run is still "will be measured". Fill it in from the demo run's logged tokens. | Moaz, with Eyad's token total | After the demo run |
| 10 | The Phase 2–6 agent prompts are in the agent files (`SYSTEM`), not in `prompts/` (CLAUDE.md: SHOULD, one file per agent prompt). | Eyad (owns `prompts/`) | Optional |

## Passed

- README: all 8 `##` headings, word for word and in order. Quickstart has a `bash` block containing exactly `docker compose up`, then how to open the app. Cost per run has a `$` figure.
- ARCHITECTURE.md: all 7 `##` headings in order, with Mermaid diagrams.
- `LICENSE`: the full MIT text (permission grant and "AS IS" warranty).
- `docker-compose.yml` is at the root.
- `.env.example`: placeholders only. `.env` is gitignored and was never committed (checked across all 82 commits on all branches).
- No real secret in git history: no real Groq, OpenAI-style or payment key, and no real `api_key` value. All matches are placeholders or test fixtures (gap 7).
- `tests/`: 15 test files with standard names.
- No text addressed to reviewers: the only matches are neutral uses of "hackathon" (e.g. "How the project stays alive after the hackathon") and "judge" in code comments.
- `CLAUDE.md` is not in `docs/`. `docs/` holds only our own `docker_check.md`. `AGENTS.md` and `GEMINI.md` are identical copies of `CLAUDE.md` at the root.
- `outputs/payment_test_log.md` starts with its MOCKED label.

## Not checked yet

Stopped when the local model finished downloading. Owner: Hashish.

- Trick prompts outside `tests/` and `evals/` (a phrase search of every other tracked file).
- Every mock labelled in the app's screens (`app.py`).
- No income promises: `guardrails.check_text` over every tracked text file outside `tests/` and `evals/`.
- Claims in `outputs/` sourced or `ASSUMPTION`: covered by `tests/test_claims.py`, which can only check the demo-run outputs once they exist (gap 2).
