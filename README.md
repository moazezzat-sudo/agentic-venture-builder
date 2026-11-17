# Agentic Venture Builder

An open-source team of AI agents that takes a founder's brief toward a sellable **digital** product. It checks the founder's claims against rated sources, scores the idea on a fixed rubric, recommends go / repeat / pivot / stop at every gate, and waits for the founder's approval before anything moves on.

## Quickstart

```bash
docker compose up
```

Then open `http://localhost:8000`, fill in your brief, and answer the follow-up questions and gates in the founder web app. No account or key is needed. The app opens at once; on the first start the local open-weight model (`qwen3:4b`, about 2.5 GB) downloads in the background, and the app says so until it is ready (progress: `docker compose logs -f model-pull`). With more memory, set `OLLAMA_MODEL=qwen3:8b` in `.env` for a stronger model about twice the size. With a free `GROQ_API_KEY` in `.env` the app works immediately, without waiting for the download.

Already running Ollama on your machine (for example Ollama for Windows with a GPU)? Copy `.env.example` to `.env`, set `OLLAMA_BASE_URL=http://host.docker.internal:11434`, and start only the app with `docker compose up --no-deps app`.

## What works and what is mocked

The repository is being built during the hackathon. A row says **Working** only once it runs end to end and has a test.

| Phase | Step | Status | Notes |
|---|---|---|---|
| All | Shared foundation: settings, model client, state schemas, decision log, output writer (`config.py`, `llm.py`, `schemas.py`, `logger.py`) | **Working** | `tests/test_smoke.py` |
| All | LangGraph orchestration, SQLite checkpoints, `start_run` / `resume_run` / `get_state` (`orchestrator.py`) | **Working** | `tests/test_orchestrator.py`; real Groq runs from the web app to Gate 1 |
| All | Founder approve/reject at every gate (`approval.py`, `gates.py`) | **Working** | `tests/test_record_decision.py`, `tests/test_approval.py`, `tests/test_gates.py` |
| All | Guardrails (`guardrails.py`) | **Working** | `tests/test_guardrails.py`, `tests/test_guardrail_eval.py`; results in `evals/guardrail_results.md` |
| All | Data tools: web search with a fallback chain of free engines, World Bank indicators, A–D source ratings (`tools/search.py`, `tools/worldbank.py`, `tools/credibility.py`) | **Working** | `tests/test_search.py`, `tests/test_worldbank.py`, `tests/test_credibility.py` |
| Discover | Discovery conversation: summary, five assumptions, typed questions, founder confirms or corrects (`agents/discovery.py`) | **Working** | `tests/test_orchestrator.py`; live discovery uses `prompts/discovery.md`; `agents/questions.py` is bypassed; committed demo run in `outputs/` |
| Discover | Category check, search plan by evidence type, research with rated sources and claim ids (`guardrails.py`, `agents/search_plan.py`, `agents/researcher.py`) | **Working** | `tests/test_orchestrator.py`; committed demo run in `outputs/` |
| Discover | Claim check, rubric score, Gate 1 with STOP (`agents/skeptic.py`, `agents/scorer.py`, `gates.py`) | **Working** | `tests/test_orchestrator.py`; real Groq runs from the web app to Gate 1 |
| Discover | Coach loop, niche step and niche gate (`agents/coach.py`, `agents/subdomain.py`) | **STUBBED** | Tested offline only (`tests/test_orchestrator.py`) |
| Validate | Lean Canvas, landing-page copy, waitlist targets set by the founder (`agents/phase2_lean_canvas.py`) | **STUBBED** | Draft agent; runs in the graph after the niche gate, with its own founder gate (`tests/test_phase_agents.py`, `tests/test_orchestrator.py`); its outputs are labelled STUBBED; the real sign-up count is entered by the founder, never estimated |
| Build | Architect, UI/UX and MVP-plan proposals (`agents/phase3_build_plan.py`) | **STUBBED** | Draft agent; runs in the graph after the niche gate, with its own founder gate (`tests/test_phase_agents.py`, `tests/test_orchestrator.py`); its outputs are labelled STUBBED |
| Build | Landing page, product and user docs, checked before Gate 3 (`agents/phase3_build.py`) | **STUBBED** | Draft agent; runs in the graph after the niche gate, with its own founder gate (`tests/test_phase_agents.py`, `tests/test_orchestrator.py`); its outputs are labelled STUBBED |
| Commercial setup | Pricing and draft policies (`agents/phase4_commercial.py`) | **STUBBED** | Draft agent; runs in the graph after the niche gate, with its own founder gate (`tests/test_phase_agents.py`, `tests/test_orchestrator.py`); its outputs are labelled STUBBED |
| Sell/deliver/get paid | Launch plan, store page and launch posts (`agents/phase5_launch.py`) | **STUBBED** | Draft agent; runs in the graph after the niche gate, with its own founder gate (`tests/test_phase_agents.py`, `tests/test_orchestrator.py`); its outputs are labelled STUBBED; nothing is posted |
| Sell/deliver/get paid | Checkout, delivery, refunds, reconciliation (`payments.py`, `delivery.py`, `refunds.py`, `reconcile.py`) | **MOCKED** | Fake in-memory events: no payment provider, no sandbox, no real money. `tests/test_sale_to_cash.py`; `outputs/payment_test_log.md` |
| Operate and learn | Metrics and persevere-or-pivot memo (`agents/phase6_memo.py`) | **STUBBED** | Draft agent; runs in the graph after the niche gate, with its own founder gate (`tests/test_phase_agents.py`, `tests/test_orchestrator.py`); its outputs are labelled STUBBED; metrics come from MOCKED sales |

## Architecture

The system runs six phases in order: Discover, Validate, Build, Commercial setup, Sell/deliver/get paid, and Operate and learn. Each phase is a set of agents in a LangGraph graph that share one state object, the Briefcase. Every phase ends at a gate that recommends go, repeat, pivot or stop against a target set in advance, then pauses until the founder approves or rejects. Every agent action is appended to `decision_log.json`, and every result is written to `outputs/`. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Models and free resources

- **Default: fully local.** The open-weight `qwen3:4b` runs on your machine through [Ollama](https://ollama.com/library/qwen3); `docker compose up` downloads it, or point the app at an Ollama you already run (see Quickstart). No account, key or payment. Settings are in `.env.example`: `OLLAMA_MODEL`, an optional smaller `OLLAMA_FAST_MODEL` for light steps, an 8,192-token context, and qwen3's thinking mode turned off for speed.
- **With no model reachable** (no Groq key and no Ollama running), briefs with an ambiguous keyword such as "crypto", "supplements", "handmade" or "lending" are blocked to be safe, because the guardrail can't ask the model whether the product is allowed; the bundled Ollama from `docker compose up` avoids this.
- **Optional: Groq free tier.** Set `LLM_PROVIDER=groq` (or `auto` with a key) and a free `GROQ_API_KEY` from [console.groq.com/keys](https://console.groq.com/keys) to use the open-weight `openai/gpt-oss-120b` and `openai/gpt-oss-20b` served by [Groq](https://console.groq.com/docs/models). Never required; no payment details are needed for the free tier.
- Historical Groq measurements are in `evals/briefs/RESULTS.md`. They predate the discovery and search-plan rewrite; the full brief suite and football check still need a fresh qwen3:4b run.
- **Free data sources, no keys:** web search tries DuckDuckGo, then other free engines through the `ddgs` package, then the Wikipedia and Hacker News search APIs, and records which engine answered (`tools/search.py`). Country statistics come from the [World Bank Open Data API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) (`tools/worldbank.py`).
- **Every source is rated A–D by fixed domain rules** (`tools/credibility.py`): official and international bodies A, social media, forums and review sites D, listed news outlets and research firms C, and rule: unknown -> B (a domain in no list is treated as the company's or author's own site). No model is used to rate sources.
- **No paid services:** payments are mocked in code.

## Cost per run

$0.00 in API charges per run with local Ollama or Groq's free tier. The figure excludes hardware, electricity and internet. The committed Groq demo used 7,171 tokens over 11 model calls and recommended STOP at Gate 1 with zero independent pain sources. The historical six-phase Groq test used 20,915 tokens with scripted founder overrides and STUBBED drafts. See the [committed gate decision](outputs/phase1_gate_decision.md) and [evaluation results](evals/briefs/RESULTS.md).

## Demo video

Not recorded yet.

## What our system will NOT do

- Promise income or success.
- Create fake reviews, testimonials, sign-ups, urgency or countdown timers.
- Pose as the founder, a customer or another brand.
- Hold, move or refund money by itself, create accounts, or store passwords or card numbers.
- Publish, send, spend or sign anything without the founder's explicit approval.
- Work on physical goods; financial, investment or crypto products; or health or legal advice products.
- Hide core features behind a paywall.

## How the project stays alive after the hackathon

- **Maintainers:** the founding team, under the MIT License.
- **Roadmap:** finish all six phases; add more free official data sources (IMF, OECD, national statistics offices); add an evaluation benchmark under `evals/`.
- **Community:** issues and pull requests on GitHub.
- **Funding:** none required. The project runs on free, open-weight models and has no paid dependencies.
