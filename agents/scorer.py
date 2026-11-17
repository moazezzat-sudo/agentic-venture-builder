"""Scorer: the model proposes a 0-4 score per rubric criterion from the claims only.

Python then checks every score and caps it by the evidence actually present,
so the model cannot score past the research (for example market above 1
with no tier A or B figure). The weighted total and the outcome are not
computed here: that is gates.py.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from agents._common import ask_json, brief_for_model, claims_markdown, cut, model_fields
from gates import criteria_names, load_rubric
from logger import log_action, write_output

# Criteria that need research evidence; with none, the score is capped at WEAK
# (problem_evidence at 0, since "no evidence" is 0 on the rubric scale).
EVIDENCE_CRITERIA = ("problem_evidence", "market", "competition", "willingness_to_pay")
WEAK = 1.0
PRICE = re.compile(
    r"(\$\s?\d|\d\s?(usd|eur|egp|gbp|dollars?)\b|\b(usd|eur|egp|gbp)\s?\d|\bper (month|year|user|seat)\b|/\s?(mo|month|yr|year)\b|\bpaid plans?\b|\bpricing\b)",
    re.I,
)


def current_claims(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Claims that count for the idea as it stands.

    A repeat keeps all earlier evidence. A pivot keeps the pain and changes the idea (prompts/coach.md),
    so sourced problem-evidence claims from earlier rounds carry over; everything else starts fresh.
    """
    since = state.get("evidence_from_round", 1)
    return [
        c for c in state.get("claims", [])
        if c.get("round", 1) >= since or (c.get("area") == "problem_evidence" and c.get("support") == "url")
    ]


def evidence_caps(claims: Iterable[dict[str, Any]]) -> dict[str, tuple[float, str]]:
    """Upper limits from the evidence: {criterion: (cap, reason)}."""
    claims = list(claims)
    caps: dict[str, tuple[float, str]] = {}
    for name in EVIDENCE_CRITERIA:
        sourced = [c for c in claims if c.get("area") == name and c.get("support") == "url"]
        if name == "willingness_to_pay":
            # A competitor's stated price is evidence that people pay for this kind of solution.
            sourced += [c for c in claims if c.get("area") == "competition" and c.get("support") == "url"
                        and PRICE.search(c.get("text", ""))]
        if name == "market":
            sourced = [c for c in sourced if c.get("tier") in ("A", "B")]
            if not sourced:
                caps[name] = (WEAK, "capped at 1: no tier A or B source for the market")
        elif name == "problem_evidence" and not sourced:
            # The rubric scale says 0 = no evidence, and a 0 here stops the idea. Market figures
            # (population, internet use) say nothing about whether the pain is real.
            caps[name] = (0.0, "set to 0: no sourced claim shows the pain")
        elif not sourced:
            caps[name] = (WEAK, "capped at 1: no sourced claim for this criterion")
    return caps


def clean_scores(raw_scores: Any, raw_reasons: Any, claims: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, str]]:
    """Every criterion gets a number in 0-4. Missing or invalid -> 0 with the reason said; then evidence caps."""
    rubric = load_rubric()
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    raw_scores = raw_scores if isinstance(raw_scores, dict) else {}
    raw_reasons = raw_reasons if isinstance(raw_reasons, dict) else {}
    scores: dict[str, float] = {}
    notes: dict[str, str] = {}
    for name in criteria_names(rubric):
        value = raw_scores.get(name)
        try:
            ok = not isinstance(value, bool) and lo <= float(value) <= hi
        except (TypeError, ValueError):
            ok = False
        if ok:
            scores[name] = float(value)
            notes[name] = cut(raw_reasons.get(name) or "no reason given", 200)
        else:
            scores[name] = 0.0
            notes[name] = "scored 0: the model gave no valid score"
    for name, (cap, why) in evidence_caps(claims).items():
        if scores[name] > cap:
            scores[name] = cap
            notes[name] = f"{notes[name]} ({why})"
    # Competition 0 stops the idea ("a free tool already solves it"), so it must rest on a sourced
    # claim that a competitor is free. Paid competitors, or none found, are not a 0.
    if scores["competition"] == 0 and not free_competitor_claims(claims):
        scores["competition"] = WEAK
        notes["competition"] = f"{notes['competition']} (raised to 1: a 0 needs a sourced claim that a free tool solves it)"
    return scores, notes


def free_competitor_claims(claims: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sourced competitor claims that say the tool is free (a plain word check, not a judgement)."""
    return [
        c for c in claims
        if c.get("area") == "competition" and c.get("support") == "url"
        and re.search(r"\bfree\b", c.get("text", ""), re.I)
        and not re.search(r"\bfree (trial|plan for \d|for \d+ days)\b", c.get("text", ""), re.I)
    ]


def make_node(step: int, name: str):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        claims = current_claims(state)
        payload = {
            "brief": brief_for_model(state["brief"]),
            "niche": state.get("subdomain") or None,
            "claims": [
                {"i": i, "text": c["text"], "support": c.get("support"), "tier": c.get("tier"), "criterion": c.get("area")}
                for i, c in enumerate(claims)
            ],
            "skeptic_checks": state.get("claim_checks") or [],
        }
        data, usage = ask_json("scorer", payload, role="smart", max_tokens=700, temperature=0)
        scores, notes = clean_scores(data.get("scores"), data.get("reasons"), claims)

        log_action(
            agent="scorer", action=f"score_rubric_{name}", sources=sorted({c["url"] for c in claims if c.get("url")}),
            run_id=state.get("run_id"), round=state.get("round", 1), **model_fields(usage), scores=scores,
        )
        weights = {k: v["weight"] for k, v in load_rubric()["criteria"].items()}
        rows = "\n".join(f"| {k} | {weights[k]:.0%} | {v:g} | {notes[k]} |" for k, v in scores.items())
        write_output(1, step, name, (
            f"# Phase 1, step {step}: rubric scores (round {state.get('round', 1)})\n\n"
            "| Criterion | Weight | Score (0-4) | Reason |\n|---|---|---|---|\n" + rows + "\n\n"
            "Weights and cut-offs are our design choices (rubric.yaml).\n\n"
            "## Claims the scorer saw\n\nThe numbers in the reasons, like [2], refer to this list.\n\n"
            + claims_markdown(claims) + "\n"
        ))
        return {"scores": scores, "score_notes": notes, "tokens": usage["tokens"]}

    node.__name__ = f"scorer_{name}"
    return node


node = make_node(6, "scores")
