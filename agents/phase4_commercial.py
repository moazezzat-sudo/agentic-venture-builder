"""Phase 4 (Commercial setup), step 1: pricing with a basis, policy drafts, rules checklist, marketing plan.

    from agents.phase4_commercial import agent
    update = agent(briefcase)   # {"drafts": {"phase4_commercial": {...}}, "text_violations": [...], "tokens": n}

- Pricing: a price in the launch market's currency, with its basis as claims (competitor
  prices, local purchasing power from Phase 1 evidence, or ASSUMPTION). No payments of any kind.
- Terms, privacy and refund policies: short drafts, each marked "Draft, not legal advice".
  They describe the seller's process; the system never refunds or moves money.
- Rules checklist: items need a tier-A (official) source; anything else is shown as
  "confirm on the official site". Dedicated rules research is STUBBED.
- Marketing plan: channels where Phase 1 found the target users, with their sources.
- Questions for agencies (email drafts): STUBBED.

Everything passes guardrails.check_text (one rewrite, then flagged). Writes
outputs/phase4_step1_commercial.md (STUBBED until wired into the graph).
"""

from __future__ import annotations

from typing import Any

from agents import phase2_6_shared as shared

AGENT = "phase4_commercial"

LEGAL_NOTE = "Draft, not legal advice: confirm with a lawyer or the relevant agency before use."

SYSTEM = shared.common.load_prompt("phase4_commercial").strip()


def _default_currency(brief: dict[str, Any]) -> str:
    loc = str(brief.get("location") or "").lower()
    return "EGP" if "egypt" in loc or "cairo" in loc or "alexandria" in loc else "USD"


def _prefill_pricing(pricing: dict[str, Any], evidence: list[dict[str, Any]], brief: dict[str, Any]) -> None:
    """When the model parsed a draft but left price or basis blank, prefill from evidence or an explicit ASSUMPTION."""
    if not pricing["currency"]:
        pricing["currency"] = _default_currency(brief)
    if not pricing["price"]:
        understood_pay = str((brief.get("confirmed_understanding") or {}).get("payment") or "").strip()
        if understood_pay and not understood_pay.lower().startswith("unclear"):
            pricing["price"] = shared.common.cut(understood_pay, 60)
        else:
            pricing["price"] = "250 per month" if pricing["currency"] == "EGP" else "10 per month"
    if not pricing["model"]:
        pricing["model"] = "subscription"
    if not pricing["basis"]:
        wtp = [e for e in evidence if e.get("area") in ("willingness_to_pay", "pricing")]
        if wtp:
            pricing["basis"] = [shared.to_claim({"text": wtp[0]["text"], "source": wtp[0]["i"]}, evidence, "pricing", AGENT)]
        else:
            pricing["basis"] = [shared.to_claim(
                {"text": "Initial starting price hypothesis for the founder to test (no competitor price in the evidence).",
                 "source": None},
                evidence, "pricing", AGENT,
            )]


def agent(state: dict[str, Any]) -> dict[str, Any]:
    evidence = shared.phase1_evidence(state)
    payload = shared.base_payload(state, evidence)
    data, found, usage = shared.ask_guarded(
        AGENT, SYSTEM, payload, round_no=int(state.get("round") or 1), max_tokens=1100,
        exempt={"policies.refund": {"money_handling"}},
    )

    p = data.get("pricing") if isinstance(data.get("pricing"), dict) else {}
    pricing = {
        "currency": shared.common.cut(p.get("currency", ""), 10),
        "price": shared.common.cut(p.get("price", ""), 60),
        "model": shared.common.cut(p.get("model", ""), 40),
        "basis": shared.claims_for(p.get("basis"), evidence, "pricing", AGENT, limit=3),
    }
    if data:
        _prefill_pricing(pricing, evidence, state.get("brief") or {})
    sourced_basis = any(c["support"] != "ASSUMPTION" for c in pricing["basis"])

    pol = data.get("policies") if isinstance(data.get("policies"), dict) else {}
    policies = {k: shared.strings(pol.get(k), limit=4, chars=240) for k in ("terms", "privacy", "refund")}

    rules = shared.claims_for(data.get("rules_checklist"), evidence, "rules", AGENT, limit=5)

    marketing = []
    for m in (data.get("marketing") if isinstance(data.get("marketing"), list) else [])[:3]:
        if not isinstance(m, dict) or not str(m.get("channel", "")).strip():
            continue
        claim = shared.to_claim({"text": f"{shared.common.cut(m['channel'], 80)}: {shared.common.cut(m.get('why', ''), 160)}",
                                 "source": m.get("source")}, evidence, "marketing", AGENT)
        marketing.append(claim)

    claims = pricing["basis"] + rules + marketing

    def rule_line(c: dict[str, Any]) -> str:
        ok = c.get("support") == "url" and c.get("tier") == "A"
        return f"- {c['text']} ({shared.support_tag(c)})" + ("" if ok else " **Not from an official source: confirm on the official site.**")

    policy_md = "\n\n".join(f"### {label} (draft)\n\n> {LEGAL_NOTE}\n\n{shared.bullets(policies[key])}"
                            for key, label in (("terms", "Terms of service"), ("privacy", "Privacy policy"), ("refund", "Refund policy")))
    body = (
        "## Pricing\n\n"
        f"Proposed price: **{pricing['price'] or '_none_'} {pricing['currency']}** ({pricing['model'] or 'model not stated'}).\n\n"
        f"Basis:\n\n{shared.bullet_claims(pricing['basis'])}\n\n"
        + ("" if sourced_basis else "**The price has no sourced basis yet: it is an ASSUMPTION for the founder to test.**\n\n")
        + "No payments are set up. Checkout is MOCKED (payments.py); the founder sells through their own provider.\n\n"
        f"## Policies\n\n{policy_md}\n\n"
        "## Rules and registrations to check\n\n"
        + ("\n".join(rule_line(c) for c in rules) if rules else "- _None proposed._")
        + "\n\nRules research from official sites is **STUBBED**: this list comes from Phase 1 evidence only.\n\n"
        f"## Marketing plan\n\n{shared.bullet_claims(marketing)}\n\n"
        "## Questions for agencies\n\n**STUBBED**: email drafts to agencies are not built yet. When they are, the founder sends them.\n"
    )
    draft = {"pricing": pricing, "price_has_sourced_basis": sourced_basis, "policies": policies,
             "legal_note": LEGAL_NOTE, "rules_checklist": rules, "marketing": marketing}
    return shared.finish(state, AGENT, 4, 1, "commercial", "pricing, policies and marketing plan", body, draft, claims, found, usage)
