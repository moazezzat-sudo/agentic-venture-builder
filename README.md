# Agentic Venture Builder

An open-source team of AI agents that takes a founder's brief toward a sellable **digital** product. It checks the founder's claims against rated sources, scores the idea on a fixed rubric, recommends go / repeat / pivot / stop at every gate, and waits for the founder's approval before anything moves on.

## Quickstart

```bash
docker compose up
```

Optional: copy `.env.example` to `.env` and add a free Groq key for faster runs. Without a key, the first start downloads the local open-weight model (`qwen3:8b`, several GB) into a Docker volume. Then open `http://localhost:8000`. The founder web app is under construction (see the table below); until it lands, this command runs the smoke tests and serves the repository on that port.

## What works and what is mocked

The repository is being built during the hackathon. A row says **Working** only once it runs end to end and has a test.

| Phase | Step | Status | Notes |
|---|---|---|---|
| All | Shared foundation: settings, model client, state schemas, decision log, output writer (`config.py`, `llm.py`, `schemas.py`, `logger.py`) | **Working** | `tests/test_smoke.py` |
| All | LangGraph orchestration (`orchestrator.py`) | **STUBBED** | Not built yet |
| All | Founder approve/reject at every gate (`approval.py`, `gates.py`) | **STUBBED** | Not built yet |
| All | Guardrails (`guardrails.py`) | **STUBBED** | Not built yet |
| Discover | Intake and follow-up questions | **STUBBED** | Not built yet |
| Discover | Business-area weighting, research with rated sources | **STUBBED** | Not built yet |
| Discover | Claim check, rubric score, Gate 1 with STOP | **STUBBED** | Not built yet |
| Validate | Lean Canvas, landing-page copy | **STUBBED** | Not built yet |
| Build | Product, UI/UX and MVP-plan proposals | **STUBBED** | Not built yet |
| Commercial setup | Pricing and draft policies | **STUBBED** | Not built yet |
| Sell/deliver/get paid | Checkout, delivery, refunds, reconciliation | **STUBBED** | Will be MOCKED only: no payment provider, no sandbox |
| Operate and learn | Metrics and persevere-or-pivot memo | **STUBBED** | Not built yet |

## Architecture

The system runs six phases in order: Discover, Validate, Build, Commercial setup, Sell/deliver/get paid, and Operate and learn. Each phase is a set of agents in a LangGraph graph that share one state object, the Briefcase. Every phase ends at a gate that recommends go, repeat, pivot or stop against a target set in advance, then pauses until the founder approves or rejects. Every agent action is appended to `decision_log.json`, and every result is written to `outputs/`. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Models and free resources

- **Default with a key: Groq free tier.** Open-weight `openai/gpt-oss-120b` for judgement-heavy steps and `openai/gpt-oss-20b` for light steps, served by [Groq](https://console.groq.com/docs/models). Create a free key at [console.groq.com/keys](https://console.groq.com/keys) and put it in a local `.env` as `GROQ_API_KEY` (see `.env.example`). No payment details are needed for the free tier.
- **Default without a key: fully local.** With no `GROQ_API_KEY`, the system uses `qwen3:8b` through [Ollama](https://ollama.com/library/qwen3), which `docker compose up` downloads. No account, key or payment.
- The model choice is backed by our own measurements in `evals/model_choice.md` (in progress).
- **Free data sources, no keys:** web search tries DuckDuckGo, then other free engines through the `ddgs` package, then the Wikipedia and Hacker News search APIs, and records which engine answered (`tools/search.py`). Country statistics come from the [World Bank Open Data API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) (`tools/worldbank.py`).
- **Every source is rated A–D by fixed domain rules** (`tools/credibility.py`): official and international bodies A, social media, forums and review sites D, listed news outlets and research firms C, and rule: unknown -> B (a domain in no list is treated as the company's or author's own site). No model is used to rate sources.
- **No paid services:** payments are mocked in code.

## Cost per run

About $0.00 per run: the Groq free tier and the local Ollama model charge nothing per token (`LLM_COST_PER_1K_TOKENS=0`). The token count per run will be measured from the logged demo run.

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
