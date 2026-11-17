"""Subdomain: after a go at Gate 1, place the idea in one precise niche, research that niche's
competitors, and write a Mom Test interview kit. The scorer then re-scores before the niche gate."""

from __future__ import annotations

from typing import Any

from agents import researcher
from agents._common import ask_json, brief_for_model, claims_markdown, cut, model_fields, write_interview_kit
from agents.scorer import current_claims
from logger import log_action, write_output


def node(state: dict[str, Any]) -> dict[str, Any]:
    brief, round_no = state["brief"], state.get("round", 1)
    strongest = [c for c in current_claims(state) if c.get("support") == "url"][:8]
    payload = {
        "brief": brief_for_model(brief),
        "areas": [a["name"] for a in state.get("areas", [])],
        "claims": [{"text": c["text"], "tier": c.get("tier")} for c in strongest],
    }
    data, usage = ask_json("subdomain", payload, role="smart", temperature=0)
    niche = cut(data.get("niche") or brief.get("target_market") or brief.get("idea"), 200)
    query = cut(data.get("competitor_query") or f"{niche} tools", 120)
    kit = write_interview_kit(data.get("interview_questions"), niche, "go")

    claims, r_usage, sources = researcher.research({"name": "competitors in niche", "query": query, "focus": "competitors"},
                                                   brief, round_no)
    if not sources:
        # A niche query can be too narrow for the search engine; fall back to the round's competitor query.
        fallback = next((a["query"] for a in state.get("areas", []) if a.get("focus") == "competitors"), None)
        if fallback and fallback != query:
            query = fallback
            claims, r_usage, sources = researcher.research(
                {"name": "competitors in niche", "query": query, "focus": "competitors"}, brief, round_no)
    tokens = usage["tokens"] + r_usage["tokens"]
    stubbed = researcher._stubbed_tools()

    log_action(
        agent="subdomain", action="place_niche_and_research_competitors", sources=[s["url"] for s in sources],
        run_id=state.get("run_id"), round=round_no, niche=niche, stubbed_tools=stubbed,
        **{**model_fields(usage), "cost": usage["cost"] + r_usage["cost"], "tokens": tokens,
           "parsed": usage["parsed"] and r_usage["parsed"] is not False},
    )
    write_output(1, 8, "niche", (
        f"# Phase 1, step 8: niche and its competitors (round {round_no})\n\n"
        f"Niche: **{niche}**\n\nCompetitor search: `{query}`\n\n## Claims\n\n{claims_markdown(claims)}\n"
    ), status="STUBBED" if stubbed else "Working")
    return {"subdomain": niche, "interview_kit": kit, "claims": claims, "tokens": tokens}
