"""Phase 3 (Build), step 1: architect, UI/UX and MVP-plan proposals for the founder to approve.

    from agents.phase3_build_plan import agent
    update = agent(briefcase)   # {"drafts": {"phase3_build_plan": {...}}, "text_violations": [...], "tokens": n}

- Architect: stack and database, each with its reason. The database is local (SQLite) by
  default; a cloud free tier only if the founder chooses one, and the founder creates any
  account. The system never creates accounts or handles keys.
- UI/UX: the main user flows and the screens they need.
- MVP plan: the smallest feature set that tests the riskiest assumption. The weakest Phase 1
  rubric criteria are passed in, so the MVP targets what the evidence left most uncertain.
- Feasibility against the founder's time, budget and skills: an ASSUMPTION, never a promise.
- Coder and tester agents, docs writer and team builder: STUBBED.

Stack and design choices are proposals ("design choice"), not market claims. Every text
passes guardrails.check_text. Writes outputs/phase3_step1_build_plan.md (STUBBED until wired in).
"""

from __future__ import annotations

from typing import Any

from agents import phase2_6_shared as shared

AGENT = "phase3_build_plan"
DEFAULT_DATABASE = "SQLite (local file)"

SYSTEM = shared.common.load_prompt("phase3_build_plan").strip()


def _weakest(state: dict[str, Any], n: int = 2) -> list[dict[str, Any]]:
    scores = state.get("scores") or {}
    notes = state.get("score_notes") or {}
    ranked = sorted(((k, v) for k, v in scores.items() if isinstance(v, (int, float))), key=lambda kv: kv[1])[:n]
    return [{"criterion": k, "score": v, "note": shared.common.cut(notes.get(k, ""), 160)} for k, v in ranked]


def _rows(value: Any, keys: tuple[str, ...], limit: int) -> list[dict[str, str]]:
    out = []
    for row in (value if isinstance(value, list) else [])[:limit]:
        if isinstance(row, dict) and any(str(row.get(k, "")).strip() for k in keys):
            out.append({k: shared.common.cut(row.get(k, ""), 200) for k in keys})
    return out


def agent(state: dict[str, Any]) -> dict[str, Any]:
    evidence = shared.phase1_evidence(state)
    weakest = _weakest(state)
    payload = {**shared.base_payload(state, evidence), "weakest_criteria": weakest}
    data, found, usage = shared.ask_guarded(AGENT, SYSTEM, payload, round_no=int(state.get("round") or 1), max_tokens=1200)

    stack = _rows(data.get("stack"), ("component", "choice", "why"), 5)
    db = data.get("database") if isinstance(data.get("database"), dict) else {}
    database = {"choice": shared.common.cut(db.get("choice", ""), 80) or DEFAULT_DATABASE,
                "why": shared.common.cut(db.get("why", ""), 200)}
    database["local"] = "sqlite" in database["choice"].lower()
    flows = shared.strings(data.get("flows"), limit=4, chars=200)
    screens = _rows(data.get("screens"), ("name", "purpose"), 6)
    riskiest = shared.claims_for(data.get("riskiest_assumption"), evidence, "riskiest_assumption", AGENT, limit=1)
    features = shared.strings(data.get("mvp_features"), limit=5, chars=160)
    out_of_scope = shared.strings(data.get("out_of_scope"), limit=5, chars=160)
    feasibility = shared.claims_for(data.get("feasibility"), evidence, "feasibility", AGENT, limit=3)
    claims = riskiest + feasibility

    stack_md = "\n".join(f"| {r['component']} | {r['choice']} | {r['why']} |" for r in stack) or "| _none_ | | |"
    screens_md = "\n".join(f"- **{s['name']}**: {s['purpose']}" for s in screens) or "- _None proposed._"
    weak_md = "\n".join(f"- {w['criterion']}: {w['score']:g} of 4. {w['note']}" for w in weakest) or "- _No Phase 1 scores in the briefcase._"
    db_note = ("" if database["local"] else
               "\n\n**Not local:** a cloud database needs the founder's choice. The founder creates any account and keeps "
               "keys in their own `.env`; the system never creates accounts or handles keys.")
    body = (
        "Every item below is a proposal for the founder to approve, change or reject. Stack and design choices are "
        "design choices, not market claims.\n\n"
        "## Architect\n\n| Component | Choice | Why |\n|---|---|---|\n" + stack_md + "\n\n"
        f"Database: **{database['choice']}**. {database['why']}{db_note}\n\n"
        "Any hosted service above (hosting, email, analytics) needs an account the founder creates; its prices and "
        "limits must be checked on the provider's own site. The system never creates accounts or handles keys.\n\n"
        f"## UI/UX\n\n### User flows\n\n{shared.bullets(flows)}\n\n### Screens\n\n{screens_md}\n\n"
        f"## MVP plan\n\nWeakest Phase 1 criteria (what the evidence left most uncertain):\n\n{weak_md}\n\n"
        f"Riskiest assumption:\n\n{shared.bullet_claims(riskiest)}\n\n"
        f"Features:\n\n{shared.bullets(features)}\n\nOut of scope for the MVP:\n\n{shared.bullets(out_of_scope)}\n\n"
        f"How the MVP tests the assumption: {shared.common.cut(data.get('how_mvp_tests_it', ''), 300) or '_not stated_'}\n\n"
        f"## Feasibility for this founder\n\n{shared.bullet_claims(feasibility)}\n\n"
        "These are estimates, not promises.\n\n"
        "## Not built yet\n\n- Coder and tester agents (generate the MVP and run its tests): **STUBBED**\n"
        "- Docs writer (user documentation): **STUBBED**\n"
        "- Team builder (roles, form, blind scoring, interview guide): **STUBBED**\n"
    )
    draft = {"stack": stack, "database": database, "flows": flows, "screens": screens, "weakest_criteria": weakest,
             "riskiest_assumption": riskiest, "mvp_features": features, "out_of_scope": out_of_scope,
             "how_mvp_tests_it": shared.common.cut(data.get("how_mvp_tests_it", ""), 300), "feasibility": feasibility}
    return shared.finish(state, AGENT, 3, 1, "build plan", "architect, UI/UX and MVP plan", body, draft, claims, found, usage)
