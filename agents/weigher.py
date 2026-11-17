"""Weigher: split the idea into 2-3 areas with weights and a search query each.

Every run researches at least one "problem" area (is the pain real?) and one
"competitors" area (who already solves it?); Python adds a plain query for
either one the model leaves out.
"""

from __future__ import annotations

from typing import Any

from agents._common import ask_json, brief_for_model, cut
from logger import log_action, write_output

INNOVATION_TYPES = ("new_product", "better_product", "cheaper_product", "new_market")
FOCUSES = ("problem", "competitors", "pricing")
REQUIRED_FOCUSES = ("problem", "competitors")
MAX_AREAS = 3


def _fallback_area(focus: str, brief: dict[str, Any]) -> dict[str, Any]:
    """A plain query for a focus the model left out. Built from the customer, not the founder's skills."""
    who = cut(brief.get("target_market") or brief.get("idea") or "", 70)
    where = cut(brief.get("location") or "", 30)
    suffix = {"problem": "problems complaints forum", "competitors": "tools apps"}[focus]
    return {"name": f"{focus} ({who})", "focus": focus, "weight": 0.0,
            "query": cut(" ".join(p for p in (who, where, suffix) if p), 120)}


def clean_areas(raw: Any, brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep at most MAX_AREAS valid areas, make sure one looks for the problem and one for
    competitors, and normalise weights to sum to 1. Added areas get the average weight."""
    areas = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or not str(a.get("name", "")).strip() or not str(a.get("query", "")).strip():
            continue
        try:
            weight = max(float(a.get("weight", 0)), 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        focus = a.get("focus") if a.get("focus") in FOCUSES else "problem"
        areas.append({"name": cut(a["name"], 60), "focus": focus, "weight": weight, "query": cut(a["query"], 120)})
        if len(areas) == MAX_AREAS:
            break
    for focus in REQUIRED_FOCUSES:
        if any(a["focus"] == focus for a in areas):
            continue
        extra = _fallback_area(focus, brief)
        extra["weight"] = (sum(a["weight"] for a in areas) / len(areas)) if areas else 1.0
        if len(areas) == MAX_AREAS:
            # Replace the last area whose focus is not required elsewhere.
            spare = next(i for i in range(len(areas) - 1, -1, -1)
                         if areas[i]["focus"] not in REQUIRED_FOCUSES
                         or sum(x["focus"] == areas[i]["focus"] for x in areas) > 1)
            areas[spare] = extra
        else:
            areas.append(extra)
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
    data, usage = ask_json("weigher", payload, role="fast", max_tokens=400)

    areas = clean_areas(data.get("areas"), brief)
    # On a repeat, the coach's queries replace the weigher's, area by area.
    for area, query in zip(areas, coach.get("queries") or []):
        area["query"] = cut(query, 120)
    innovation = data.get("innovation_type") if data.get("innovation_type") in INNOVATION_TYPES else "unknown"

    log_action(
        agent="weigher", action="split_areas", model=usage["model"], cost=usage["cost"],
        tokens=usage["tokens"], round=state.get("round", 1), parsed=usage["parsed"],
    )
    rows = "\n".join(f"| {a['name']} | {a['focus']} | {a['weight']:.2f} | {a['query']} |" for a in areas)
    write_output(1, 3, "areas", (
        f"# Phase 1, step 3: business areas (round {state.get('round', 1)})\n\n"
        f"Innovation type: **{innovation}**\n\n| Area | Looks for | Weight | Search query |\n|---|---|---|---|\n{rows}\n\n"
        "Weights are the model's split of the idea, normalised to sum to 1 (design choice, not a market claim).\n"
    ))
    return {"areas": areas, "innovation_type": innovation, "tokens": usage["tokens"]}
