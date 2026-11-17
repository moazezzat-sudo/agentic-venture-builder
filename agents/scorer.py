"""Scorer: the model proposes a 0-4 score per rubric criterion from the claims only.

Python then checks every score and caps it by the evidence actually present,
so the model cannot score past the research (for example market above 1
with no tier A or B figure). The weighted total and the outcome are not
computed here: that is gates.py.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from agents._common import ask_json, brief_for_model, claims_markdown, cut, model_fields
from gates import criteria_names, load_rubric, source_key
from logger import log_action, write_output
from schemas import EVIDENCE_CRITERION

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
        elif name == "problem_evidence":
            independent = {source_key(c["url"]) for c in sourced}
            if len(independent) < 3:
                caps[name] = (2.0, f"capped at 2: {len(independent)} independent source(s) show the pain, 3 needed for more")
            elif not [c for c in sourced if c.get("tier") in ("A", "B", "C")]:
                caps[name] = (2.0, "capped at 2: only community signals (tier D) show the pain")
        elif not sourced:
            caps[name] = (WEAK, "capped at 1: no sourced claim for this criterion")
    return caps


# Which evidence types can support a score above 1 on each criterion (schemas.EVIDENCE_TYPES).
CITABLE = {"problem_evidence": ("pain",), "competition": ("competitors",),
           "willingness_to_pay": ("pricing", "competitors"), "market": ("market",)}
MODEL_CRITERIA = ("problem_evidence", "market", "competition", "founder_fit", "feasibility", "willingness_to_pay")


def claim_kind(claim: dict[str, Any]) -> Optional[str]:
    """The evidence type of a claim (older claims carry only the rubric criterion)."""
    if claim.get("kind"):
        return claim["kind"]
    reverse = {v: k for k, v in EVIDENCE_CRITERION.items()}
    return reverse.get(claim.get("area"))


def citable(criterion: str, claim: dict[str, Any]) -> bool:
    kind = claim_kind(claim)
    if claim.get("support") != "url" or kind not in CITABLE.get(criterion, ()):
        return False
    # A competitor claim supports willingness to pay only when it states a price.
    return not (criterion == "willingness_to_pay" and kind == "competitors" and not PRICE.search(claim.get("text", "")))


def rules_risk(state: dict[str, Any], claims: list[dict[str, Any]]) -> tuple[float, str, list[str]]:
    """rules_risk in Python: guardrails, not the model. Banned categories never reach scoring (category check)."""
    from agents.search_plan import regulation_relevant

    founder_hits = [v for v in state.get("text_violations") or [] if not v.get("rewritable")]
    if founder_hits:
        return 0.0, "A guardrail rule is broken in the founder's own answers: " + ", ".join(v["rule"] for v in founder_hits), []
    regulation = [c["id"] for c in claims if claim_kind(c) == "regulation" and c.get("id")]
    if regulation_relevant(state.get("brief") or {}):
        return 3.0, "Allowed digital product in a regulated area: confirm the official rules before launch.", regulation
    return 4.0, "Allowed digital product; no guardrail hits and no regulated activity found.", regulation


def clean_scores(raw: Any, claims: list[dict[str, Any]], state: Optional[dict[str, Any]] = None
                 ) -> tuple[dict[str, float], dict[str, str], dict[str, list[str]], list[str]]:
    """Check the model's {criterion: {score, claim_ids, reasoning}} against the claims.

    Returns (scores, notes, claim ids per criterion, incomplete). A criterion the model did not return
    with a valid 0-4 score is listed in `incomplete` (the gate then recommends repeat) and gets no score:
    a missing score is never turned into a 0.
    """
    rubric = load_rubric()
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    raw = raw if isinstance(raw, dict) else {}
    by_id = {c.get("id"): c for c in claims if c.get("id")}
    scores: dict[str, float] = {}
    notes: dict[str, str] = {}
    cited: dict[str, list[str]] = {}
    incomplete: list[str] = []
    for name in MODEL_CRITERIA:
        entry = raw.get(name) if isinstance(raw.get(name), dict) else {}
        value = entry.get("score")
        try:
            ok = not isinstance(value, bool) and value is not None and lo <= float(value) <= hi
        except (TypeError, ValueError):
            ok = False
        if not ok:
            incomplete.append(name)
            continue
        ids = [str(i) for i in (entry.get("claim_ids") or []) if str(i) in by_id]
        score, note = float(value), cut(entry.get("reasoning") or "no reasoning given", 220)
        if name in CITABLE:
            right = [i for i in ids if citable(name, by_id[i])]
            if score > 1 and not right:
                score, note = 1.0, f"no evidence: no {' or '.join(CITABLE[name])} claim cited (capped at 1). {note}"
            ids = right
        scores[name], notes[name], cited[name] = score, note, ids
    for name, (cap, why) in evidence_caps(claims).items():
        if name in scores and scores[name] > cap:
            scores[name] = cap
            notes[name] = f"{notes[name]} ({why})"
    # Competition 0 stops the idea ("a free tool already solves it"), so it must rest on a sourced
    # claim that a competitor is free. Paid competitors, or none found, are not a 0.
    if scores.get("competition") == 0 and not free_competitor_claims(claims):
        scores["competition"] = WEAK
        notes["competition"] = f"{notes['competition']} (raised to 1: a 0 needs a sourced claim that a free tool solves it)"
    if scores.get("competition") == 0:
        cited["competition"] = [c["id"] for c in free_competitor_claims(claims) if c.get("id")]
    rr, rr_note, rr_ids = rules_risk(state or {}, claims)
    scores["rules_risk"], notes["rules_risk"], cited["rules_risk"] = rr, rr_note, rr_ids
    return scores, notes, cited, incomplete


_SCORE_TEXT = re.compile(r"-?\d+(?:\.\d+)?")


def _key(name: Any) -> str:
    return re.sub(r"[^a-z]+", "_", str(name).lower()).strip("_")


def _score_value(value: Any) -> Any:
    """2, 2.5, "2", "2/4", "score: 3" -> a number; anything else unchanged."""
    if isinstance(value, str):
        m = _SCORE_TEXT.search(value)
        return float(m.group()) if m else value
    return value


def normalize_scores(data: Any) -> dict[str, Any]:
    """Accept the shapes small local models actually return and turn them into
    {criterion: {score, claim_ids, reasoning}}. Unknown keys are ignored; nothing is invented."""
    if not isinstance(data, dict):
        return {}
    wanted = {_key(n): n for n in MODEL_CRITERIA}
    reasons = data.get("reasons") if isinstance(data.get("reasons"), dict) else {}
    reasons = {_key(k): v for k, v in reasons.items()}
    source: Any = data.get("criteria") or data.get("scores") or data.get("rubric") or data
    if isinstance(source, list):
        source = {str(e.get("criterion") or e.get("name") or ""): e for e in source if isinstance(e, dict)}
    out: dict[str, Any] = {}
    if not isinstance(source, dict):
        return out
    for raw_key, entry in source.items():
        name = wanted.get(_key(raw_key))
        if not name:
            continue
        if isinstance(entry, dict):
            score = entry.get("score", entry.get("value"))
            ids = entry.get("claim_ids") or entry.get("claims") or []
            reasoning = entry.get("reasoning") or entry.get("reason") or entry.get("explanation")
        else:
            score, ids, reasoning = entry, [], None
        if isinstance(ids, str):
            ids = re.findall(r"C\d+", ids)
        out[name] = {"score": _score_value(score), "claim_ids": ids,
                     "reasoning": reasoning or reasons.get(_key(raw_key))}
    return out


def free_competitor_claims(claims: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sourced competitor claims that say the tool is free (a plain word check, not a judgement)."""
    return [
        c for c in claims
        if c.get("area") == "competition" and c.get("support") == "url"
        and re.search(r"\bfree\b", c.get("text", ""), re.I)
        and not re.search(r"\bfree (trial|plan for \d|for \d+ days)\b", c.get("text", ""), re.I)
    ]


def grouped_claims(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Claims for the model, grouped by evidence type, each with its id."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        groups.setdefault(claim_kind(c) or "other", []).append(
            {"id": c.get("id"), "text": c["text"], "tier": c.get("tier"), "support": c.get("support")})
    return groups


def make_node(step: int, name: str):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        claims = current_claims(state)
        payload = {
            "brief": brief_for_model(state["brief"]),
            "niche": state.get("subdomain") or None,
            "claims_by_type": grouped_claims(claims),
            "skeptic_checks": state.get("claim_checks") or [],
        }
        data, usage = ask_json("scorer", payload, role="smart", max_tokens=900, temperature=0)
        scores, notes, cited, incomplete = clean_scores(normalize_scores(data), claims, state)

        log_action(
            agent="scorer", action=f"score_rubric_{name}", sources=sorted({c["url"] for c in claims if c.get("url")}),
            run_id=state.get("run_id"), round=state.get("round", 1), **model_fields(usage), scores=scores,
            claim_ids=cited, scoring_incomplete=incomplete,
        )
        weights = {k: v["weight"] for k, v in load_rubric()["criteria"].items()}
        rows = "\n".join(
            f"| {k} | {weights[k]:.0%} | {scores[k]:g} | {', '.join(cited.get(k) or []) or '-'} | {notes[k]} |"
            if k in scores else f"| {k} | {weights[k]:.0%} | **missing** | - | the model returned no valid score |"
            for k in weights
        )
        missing = (f"\n\n**Scoring incomplete** ({', '.join(incomplete)}): the gate recommends repeat; "
                   "no missing score is turned into a 0.") if incomplete else ""
        write_output(1, step, name, (
            f"# Phase 1, step {step}: rubric scores (round {state.get('round', 1)})\n\n"
            "| Criterion | Weight | Score (0-4) | Claims | Reasoning |\n|---|---|---|---|---|\n" + rows + missing + "\n\n"
            "A score above 1 on problem evidence, competition, willingness to pay or market must cite a claim of the "
            "matching evidence type. Rules and risk comes from the guardrails, not the model. Weights and cut-offs are "
            "our design choices (rubric.yaml).\n\n"
            "## Claims\n\n" + claims_markdown(claims) + "\n"
        ))
        return {"scores": scores, "score_notes": notes, "score_claims": cited, "scoring_incomplete": incomplete,
                "tokens": usage["tokens"]}

    node.__name__ = f"scorer_{name}"
    return node


node = make_node(6, "scores")
