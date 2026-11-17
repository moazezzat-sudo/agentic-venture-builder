"""Helpers shared by the Phase 2-6 draft agents (phase2_lean_canvas ... phase6_memo).

Each draft agent is a function agent(briefcase) -> dict that returns a state update:

    {"drafts": {"<agent>": {...}}, "text_violations": [...], "tokens": int}

What every draft agent does, through these helpers:
  1. Sends a short prompt plus a compact JSON payload (the brief and the sourced Phase 1
     claims, numbered) through agents._common.invoke_model, so the model call is the same
     one Phase 1 uses: temperature 0, JSON mode (format="json" on Ollama), a token cap,
     and one retry when the reply is not JSON. Tests replace invoke_model with a fake.
  2. Turns every claim-like item {"text", "source"} into a schemas.Claim: a valid source
     number copies that Phase 1 claim's URL and tier (or our evidence pointer); anything
     else becomes ASSUMPTION. The code decides the support, never the model.
  3. Runs guardrails.check_text on every text in the draft. On a violation it asks the
     model to rewrite once; if the rewrite still breaks a rule, the draft is returned with
     the violation flagged (rewritable=True, so the gate recommends repeat).
  4. Logs one decision_log.json entry and writes outputs/phase<N>_step<M>_<name>.md with
     status STUBBED until the agent has run end to end in the graph.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

import agents._common as common
from logger import log_action, write_output
from schemas import Claim

MAX_EVIDENCE = 12
MAX_ITEMS = 4
STATUS = "STUBBED"  # until the agent runs end to end in the graph

REWRITE_NOTE = (
    "Your draft broke these rules. Rewrite the whole draft in the same JSON shape, without them. "
    "No fake reviews, testimonials or sign-up counts; no urgency or countdowns; no income or success "
    "promises; never speak as the founder, a customer or another brand; the system never moves money "
    "or creates accounts."
)


# --------------------------------------------------------------------------- inputs


def phase1_evidence(state: dict[str, Any], limit: int = MAX_EVIDENCE) -> list[dict[str, Any]]:
    """Sourced Phase 1 claims (URL or our evidence) from the current rounds, numbered for the model.

    Each item keeps the full Claim under "_claim" so a cited number can be resolved in code.
    """
    start = int(state.get("evidence_from_round") or 1)
    out = []
    for raw in state.get("claims") or []:
        if not isinstance(raw, dict) or raw.get("support") not in ("url", "evidence"):
            continue
        if int(raw.get("round") or start) < start:
            continue
        try:
            claim = Claim(**{k: v for k, v in raw.items() if k in Claim.model_fields})
        except ValueError:
            continue
        out.append({"i": len(out), "text": common.cut(claim.text, 160), "tier": claim.tier,
                    "area": claim.area, "_claim": claim})
        if len(out) >= limit:
            break
    return out


def for_model(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in evidence]


def base_payload(state: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "brief": common.brief_for_model(state.get("brief") or {}),
        "niche": state.get("subdomain") or "",
        "evidence": for_model(evidence),
    }


# --------------------------------------------------------------------------- model call


def ask(agent: str, system: str, payload: dict[str, Any], role: str = "smart", max_tokens: int = 900) -> tuple[dict[str, Any], dict[str, Any]]:
    """One JSON model call at temperature 0, retried once if the reply is not JSON."""
    user = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text, tokens, cost, model = common.invoke_model(agent, system, user, role=role, max_tokens=max_tokens, temperature=0)
    data = common.parse_json(text)
    retried = False
    if not data:
        retried = True
        text, t2, c2, model = common.invoke_model(agent, system, f"{user}\n\n{common.RETRY_NOTE}", role=role,
                                                  max_tokens=max_tokens, temperature=0)
        tokens, cost = tokens + t2, cost + c2
        data = common.parse_json(text)
    return data, {"tokens": tokens, "cost": cost, "model": model, "parsed": bool(data), "retried": retried}


def _add_usage(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {**b, "tokens": a.get("tokens", 0) + b.get("tokens", 0), "cost": a.get("cost", 0) + b.get("cost", 0),
            "retried": a.get("retried") or b.get("retried")}


def texts_in(value: Any, path: str = "") -> dict[str, str]:
    """Every string in a draft, keyed by where it sits (for check_text and for the violation's source)."""
    found: dict[str, str] = {}
    if isinstance(value, str):
        if value.strip():
            found[path or "text"] = value
    elif isinstance(value, dict):
        for k, v in value.items():
            found.update(texts_in(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.update(texts_in(v, f"{path}[{i}]"))
    return found


def ask_guarded(
    agent: str, system: str, payload: dict[str, Any], round_no: int, role: str = "smart", max_tokens: int = 900,
    texts: Optional[Callable[[dict[str, Any]], dict[str, str]]] = None,
    exempt: Optional[dict[str, set[str]]] = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """ask(), then check_text on the draft; one rewrite on a violation. Returns (draft, violations, usage).

    exempt maps a path prefix in the draft to rules that don't apply there, e.g.
    {"policies.refund": {"money_handling"}}: a refund policy has to describe refunds.
    """
    pick = texts or texts_in

    def check(draft: dict[str, Any]) -> list[dict[str, Any]]:
        hits = common.text_violations(pick(draft), rewritable=True, round_no=round_no)
        return [v for v in hits
                if not any(v["source"].startswith(p) and v["rule"] in rules for p, rules in (exempt or {}).items())]

    data, usage = ask(agent, system, payload, role=role, max_tokens=max_tokens)
    found = check(data)
    rewrote = False
    if found:
        rewrote = True
        fix = [{"where": v["source"], "rule": v["rule"], "text": v["excerpt"]} for v in found]
        data2, usage2 = ask(agent, system, {**payload, "previous_draft": data, "fix": fix, "note": REWRITE_NOTE},
                            role=role, max_tokens=max_tokens)
        usage = _add_usage(usage, usage2)
        if data2:
            data = data2
            found = check(data)
    for v in found:
        v["agent"] = agent
    usage["rewrote"] = rewrote
    return data, found, usage


# --------------------------------------------------------------------------- claims


def items(value: Any, limit: int = MAX_ITEMS) -> list[dict[str, Any]]:
    """A model list of {"text", "source"} (or plain strings), cleaned and capped."""
    out = []
    for item in value if isinstance(value, list) else ([value] if value else []):
        if isinstance(item, str):
            item = {"text": item, "source": None}
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            out.append({"text": common.cut(item["text"], 240), "source": item.get("source")})
        if len(out) >= limit:
            break
    return out


def to_claim(item: dict[str, Any], evidence: list[dict[str, Any]], area: str, agent: str) -> dict[str, Any]:
    """A cited Phase 1 claim's support is copied; anything else is an ASSUMPTION."""
    src = item.get("source")
    if isinstance(src, bool):
        src = None
    if isinstance(src, str) and src.strip().isdigit():
        src = int(src.strip())
    if isinstance(src, int) and 0 <= src < len(evidence):
        c: Claim = evidence[src]["_claim"]
        claim = Claim(text=item["text"], support=c.support, url=c.url, tier=c.tier, accessed_at=c.accessed_at,
                      evidence_ref=c.evidence_ref, area=area, agent=agent)
    else:
        claim = Claim(text=item["text"], support="ASSUMPTION", area=area, agent=agent)
    return claim.model_dump()


def claims_for(value: Any, evidence: list[dict[str, Any]], area: str, agent: str, limit: int = MAX_ITEMS) -> list[dict[str, Any]]:
    return [to_claim(i, evidence, area, agent) for i in items(value, limit)]


def support_tag(c: dict[str, Any]) -> str:
    if c.get("support") == "url":
        return f"tier {c.get('tier')}, [{c['url']}]({c['url']})"
    if c.get("support") == "evidence":
        return f"our evidence: {c.get('evidence_ref')}"
    return "ASSUMPTION"


def bullet_claims(claims: Iterable[dict[str, Any]]) -> str:
    lines = [f"- {c['text']} ({support_tag(c)})" for c in claims]
    return "\n".join(lines) if lines else "- _Nothing proposed._"


def bullets(values: Iterable[Any]) -> str:
    lines = [f"- {common.cut(v, 300)}" for v in values if str(v or "").strip()]
    return "\n".join(lines) if lines else "- _Nothing proposed._"


def strings(value: Any, limit: int = MAX_ITEMS, chars: int = 300) -> list[str]:
    return [common.cut(v, chars) for v in (value if isinstance(value, list) else []) if str(v or "").strip()][:limit]


# --------------------------------------------------------------------------- output


def violations_markdown(found: list[dict[str, Any]]) -> str:
    if not found:
        return "None: every text in this draft passed `guardrails.check_text`."
    return "\n".join(f"- **{v['rule']}** in `{v['source']}`: \"{v['excerpt']}\". {v['reason']}" for v in found)


def finish(
    state: dict[str, Any], agent: str, phase: int, step: int, name: str, title: str, body: str,
    draft: dict[str, Any], claims: list[dict[str, Any]], found: list[dict[str, Any]], usage: dict[str, Any],
) -> dict[str, Any]:
    """Log the action, write the STUBBED output file, return the state update."""
    sources = sorted({c["url"] for c in claims if c.get("support") == "url"})
    n_assumptions = sum(1 for c in claims if c.get("support") == "ASSUMPTION")
    log_action(
        agent=agent, action=f"draft_{name.replace(' ', '_')}", sources=sources, run_id=state.get("run_id"),
        violations=[v["rule"] for v in found], rewrote=usage.get("rewrote", False), status=STATUS,
        claims=len(claims), assumptions=n_assumptions, **common.model_fields(usage),
    )
    content = (
        f"# Phase {phase}, step {step}: {title}\n\n"
        "Draft for the founder to review and approve. Every claim shows its support: a source URL with its tier, "
        "our own evidence, or ASSUMPTION.\n\n"
        f"{body}\n\n## Claims\n\n{common.claims_markdown(claims)}\n\n"
        f"## Guardrail check\n\n{violations_markdown(found)}\n"
    )
    write_output(phase, step, name, content, status=STATUS)
    return {
        "drafts": {agent: {**draft, "claims": claims, "violations": found, "status": STATUS}},
        "text_violations": found,
        "tokens": int(usage.get("tokens", 0)),
    }
