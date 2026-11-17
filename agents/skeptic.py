"""Skeptic: checks the founder's own statements against the research.

The model picks up to 3 statements and gives a verdict; Python then demotes
any "supported" or "contradicted" verdict that does not point at a real,
sourced research claim to "unverified".
"""

from __future__ import annotations

from typing import Any

from agents._common import ask_json, brief_for_model, cut
from agents.scorer import current_claims
from logger import log_action, write_output

VERDICTS = ("supported", "contradicted", "unverified")
MAX_CHECKS = 3


def clean_checks(raw: Any, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_CHECKS]:
        if not isinstance(item, dict) or not str(item.get("statement", "")).strip():
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
    data, usage = ask_json("skeptic", payload, role="smart", max_tokens=450)
    checks = clean_checks(data.get("checks"), claims)

    log_action(
        agent="skeptic", action="check_founder_claims", sources=sorted({u for c in checks for u in c["evidence"]}),
        model=usage["model"], cost=usage["cost"], tokens=usage["tokens"], round=state.get("round", 1),
        parsed=usage["parsed"], verdicts=[c["verdict"] for c in checks],
    )
    rows = "\n".join(
        f"| {c['statement']} | {c['verdict']} | {c['why']} | {' '.join(c['evidence']) or 'none'} |" for c in checks
    ) or "| _No checkable statements found._ | | | |"
    write_output(1, 5, "skeptic", (
        f"# Phase 1, step 5: founder claims checked (round {state.get('round', 1)})\n\n"
        "| Founder statement | Verdict | Why | Sources |\n|---|---|---|---|\n" + rows + "\n"
    ))
    return {"claim_checks": checks, "tokens": usage["tokens"]}
