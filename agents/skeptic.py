"""Skeptic: checks the founder's own statements against the research.

The model picks up to 3 statements and gives a verdict; Python then demotes
any "supported" or "contradicted" verdict that does not point at a real,
sourced research claim to "unverified".
"""

from __future__ import annotations

import re
from typing import Any

from agents._common import ask_json, brief_for_model, cut, model_fields
from agents.scorer import current_claims
from logger import log_action, write_output

VERDICTS = ("supported", "contradicted", "unverified")
MAX_CHECKS = 3


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split())


def restates_brief(statement: str, brief: dict[str, Any]) -> bool:
    """True when the statement is just the idea or the target market repeated, not a claim to check."""
    s = _norm(re.sub(r"^\s*(idea|target market|target)\s*:\s*", "", statement, flags=re.I))
    for field in ("idea", "target_market"):
        f = _norm(brief.get(field))
        if s and f and (s == f or (len(s) >= 0.6 * len(f) and (s in f or f in s))):
            return True
    return False


def clean_checks(raw: Any, claims: list[dict[str, Any]], brief: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    checks = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_CHECKS]:
        if not isinstance(item, dict) or not str(item.get("statement", "")).strip():
            continue
        if brief and restates_brief(item["statement"], brief):
            continue
        verdict = item.get("verdict") if item.get("verdict") in VERDICTS else "unverified"
        evidence = [
            i for i in (item.get("evidence") or [])
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(claims) and claims[i].get("support") == "url"
        ]
        why = cut(item.get("why") or "", 200)
        if verdict != "unverified" and not evidence:
            verdict, why = "unverified", "no sourced research claim backs this verdict"
        checks.append({
            "statement": cut(item["statement"], 200), "verdict": verdict, "why": why,
            "evidence": [claims[i]["url"] for i in evidence],
        })
    return checks


def node(state: dict[str, Any]) -> dict[str, Any]:
    claims = current_claims(state)
    payload = {
        "brief": brief_for_model(state["brief"]),
        "claims": [{"i": i, "text": c["text"], "tier": c.get("tier"), "support": c.get("support")} for i, c in enumerate(claims)],
    }
    data, usage = ask_json("skeptic", payload, role="smart", temperature=0, expect=("checks",))
    checks = clean_checks(data.get("checks"), claims, state["brief"])

    log_action(
        agent="skeptic", action="check_founder_claims", sources=sorted({u for c in checks for u in c["evidence"]}),
        run_id=state.get("run_id"), round=state.get("round", 1), **model_fields(usage), verdicts=[c["verdict"] for c in checks],
    )
    rows = "\n".join(
        f"| {c['statement']} | {c['verdict']} | {c['why']} | {' '.join(c['evidence']) or 'none'} |" for c in checks
    ) or "| _No checkable statements found._ | | | |"
    write_output(1, 5, "skeptic", (
        f"# Phase 1, step 5: founder claims checked (round {state.get('round', 1)})\n\n"
        "| Founder statement | Verdict | Why | Sources |\n|---|---|---|---|\n" + rows + "\n"
    ))
    return {"claim_checks": checks, "tokens": usage["tokens"]}
