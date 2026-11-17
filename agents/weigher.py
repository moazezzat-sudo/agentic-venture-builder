"""Weigher: split the idea into 2-3 business areas with weights and a search query each."""

from __future__ import annotations

from typing import Any

from agents._common import ask_json, brief_for_model, cut
from logger import log_action, write_output

INNOVATION_TYPES = ("new_product", "better_product", "cheaper_product", "new_market")
MAX_AREAS = 3


def clean_areas(raw: Any, idea: str) -> list[dict[str, Any]]:
    """Keep at most MAX_AREAS valid areas and normalise weights to sum to 1. Falls back to one area."""
    areas = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or not str(a.get("name", "")).strip() or not str(a.get("query", "")).strip():
            continue
        try:
            weight = max(float(a.get("weight", 0)), 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        areas.append({"name": cut(a["name"], 60), "weight": weight, "query": cut(a["query"], 120)})
        if len(areas) == MAX_AREAS:
            break
    if not areas:
        areas = [{"name": "core problem", "weight": 1.0, "query": cut(f"{idea} problem", 120)}]
    total = sum(a["weight"] for a in areas)
    for a in areas:
        a["weight"] = round(a["weight"] / total, 2) if total else round(1 / len(areas), 2)
    return areas


def node(state: dict[str, Any]) -> dict[str, Any]:
    brief = state["brief"]
    payload: dict[str, Any] = {"brief": brief_for_model(brief)}
    coach = state.get("coach_notes") or {}
    if coach:
        payload["coach"] = {k: coach.get(k) for k in ("revised_idea", "missing_evidence", "queries")}
    data, usage = ask_json("weigher", payload, role="fast", max_tokens=350)

    areas = clean_areas(data.get("areas"), brief.get("idea", ""))
    # On a repeat, the coach's queries replace the weigher's, area by area.
    for area, query in zip(areas, coach.get("queries") or []):
        area["query"] = cut(query, 120)
    innovation = data.get("innovation_type") if data.get("innovation_type") in INNOVATION_TYPES else "unknown"

    log_action(
        agent="weigher", action="split_areas", model=usage["model"], cost=usage["cost"],
        tokens=usage["tokens"], round=state.get("round", 1), parsed=usage["parsed"],
    )
    rows = "\n".join(f"| {a['name']} | {a['weight']:.2f} | {a['query']} |" for a in areas)
    write_output(1, 3, "areas", (
        f"# Phase 1, step 3: business areas (round {state.get('round', 1)})\n\n"
        f"Innovation type: **{innovation}**\n\n| Area | Weight | Search query |\n|---|---|---|\n{rows}\n\n"
        "Weights are the model's split of the idea, normalised to sum to 1 (design choice, not a market claim).\n"
    ))
    return {"areas": areas, "innovation_type": innovation, "tokens": usage["tokens"]}
