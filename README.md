# Agentic Venture Builder

An open-source team of AI agents that takes a founder's idea toward a validated, sellable digital product across six structured phases with explicit evidence gates and founder approval controls.

## Quickstart

```bash
docker compose up
```

Once the containers are running, open the app in your browser at `http://localhost:8000` (or run the interactive CLI inside the `app` container). Copy `.env.example` to `.env` if you wish to customize model or sandbox settings before starting.

## What works and what is mocked

| Phase | Step | Component | Status | Notes |
|---|---|---|---|---|
| Phase 1: Discover | 1.1 Opportunity Scan | `agents/researcher.py` | **STUBBED** | Scans public problem threads and cites source URLs or labels `ASSUMPTION` |
| Phase 1: Discover | Gate 1: Opportunity Gate | `gates.py` / `approval.py` | **Working** | Enforces evidence threshold and explicit founder approve/reject |
| Phase 2: Validate | 2.1 Market & Willingness-to-Pay | `agents/validator.py` | **STUBBED** | Evaluates demand signals and competitive alternatives |
| Phase 2: Validate | Gate 2: Validation Gate | `gates.py` / `approval.py` | **Working** | Recommends `stop` on weak evidence; requires founder approval |
| Phase 3: Build | 3.1 Digital Product Spec & Asset Build | `agents/builder.py` | **STUBBED** | Generates digital product artifacts and documentation |
| Phase 3: Build | Gate 3: Build Quality Gate | `gates.py` / `approval.py` | **Working** | Checks product completeness and prohibited-category guardrails |
| Phase 4: Commercial setup | 4.1 Pricing, Copy & Terms | `agents/commercial.py` | **STUBBED** | Prepares honest landing copy and sandbox checkout configuration |
| Phase 4: Commercial setup | Gate 4: Launch Gate | `gates.py` / `approval.py` | **Working** | Blocks publishing until founder explicitly approves |
| Phase 5: Sell/deliver/get paid | 5.1 Sandbox Checkout & Webhook | `payments.py` | **MOCKED** | Simulated / sandbox payment intent and webhook verification |
| Phase 5: Sell/deliver/get paid | 5.2 Idempotent Digital Delivery | `delivery.py` | **Working** | Grants access once per paid order; prevents duplicate delivery |
| Phase 5: Sell/deliver/get paid | 5.3 Refunds & Reconciliation | `refunds.py` / `reconcile.py` | **MOCKED** | Simulated refund revokes access; reconciles orders, fees, and payouts |
| Phase 6: Operate and learn | 6.1 Telemetry & Iteration Brief | `agents/operator.py` | **STUBBED** | Summarizes conversion, refund reasons, and next backlog actions |

## Architecture

The system orchestrates specialized role-based agents across six sequential phases: **Discover**, **Validate**, **Build**, **Commercial setup**, **Sell/deliver/get paid**, and **Operate and learn**. Between every phase, deterministic evidence gates evaluate source quality and guardrail compliance, recommending **STOP** whenever market evidence is weak or unverifiable. No external publication, spend, or commercial action can occur without an explicit founder approval step enforced in code. Every agent action and gate decision is appended to an auditable `decision_log.json`, and all phase deliverables are written to `outputs/`. See [ARCHITECTURE.md](ARCHITECTURE.md) for full phase specifications and system diagrams.

## Models and free resources

- **Primary open-weight model:** `qwen3:8b` running locally via [Ollama](https://ollama.com/) (`http://localhost:11434`).
- **How to run without paying:**
  1. Use the bundled `ollama` service in `docker-compose.yml` or install Ollama locally and run `ollama pull qwen3:8b`.
  2. Leave paid API keys blank in `.env`; the orchestrator defaults to local `qwen3:8b` inference and free public web sources.
  3. All payment, fulfillment, and reconciliation flows run in local mock/sandbox mode with zero transaction costs.

## Cost per run

About $0.00 per run (local model `qwen3:8b` via Ollama, ~40k tokens).

## What our system will NOT do

- **Never promise income or success:** We do not make revenue guarantees or financial projections presented as certainty.
- **Never fabricate social proof or urgency:** We never create fake reviews, testimonials, sign-ups, or countdown timers.
- **Never impersonate:** The system never poses as the founder, a customer, or another brand.
- **Never autonomously touch real money or credentials:** The system never holds, moves, or refunds real money by itself, never creates external accounts autonomously, and never stores passwords or payment card numbers.
- **Never build prohibited products:** The guardrail engine blocks physical goods, financial/investment/crypto products, and health or legal advice products.
- **Never bypass founder approval or hide core features behind a paywall:** Nothing is published, sent, spent, or signed without an explicit founder approve/reject step enforced in code, and 100% of core features remain open-source.

## How the project stays alive after the hackathon

- **Maintainers & Governance:** Maintained by the founding hackathon team under the MIT License with open pull requests, issue templates, and release tags on the `main` branch.
- **Roadmap:**
  - *Short-term (Month 1):* Replace remaining stubbed research/build adapters with live local tool-calling connectors and Stripe Test Mode webhooks.
  - *Medium-term (Months 2–3):* Add pluggable digital delivery adapters (GitHub release tokens, static bundle hosting, license key servers) and an evaluation benchmark suite under `evals/`.
- **Community & Funding:** Community contributions are welcomed via GitHub Discussions and Issues. The core project remains free and open-source with zero required paid services, sustained through maintainer sponsorship and optional community grants.
