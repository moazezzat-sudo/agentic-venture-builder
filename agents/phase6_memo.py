"""Phase 6 (Operate and learn), step 1: metrics against targets, persevere-or-pivot memo, support-reply drafts.

    from agents.phase6_memo import agent
    update = agent(briefcase)   # {"drafts": {"phase6_memo": {...}}, "text_violations": [...], "tokens": n}

Data: briefcase["sales_store"] (a payments.MockStore) when the run has one, otherwise the fixed
MOCKED dataset from payments.mock_sales_data(). There are no real customers yet, so the data is
MOCKED and labelled so everywhere.

The recommendation is plain Python, never the model (like gates.py):
  - MOCKED data            -> repeat: fake sales can't support persevere or pivot
  - no targets from Gate 2 -> repeat: set targets first
  - every target missed    -> stop
  - some targets missed    -> pivot
  - every target met       -> go (persevere)
Targets are the founder's, set at Gate 2, in briefcase["targets"]:
{"paid_orders": 10, "max_refund_rate": 0.2, ...}; a "max_" target is an upper limit.

The model writes the memo text, two support-reply drafts (for the founder to send; the system
never refunds or moves money) and next experiments. Every text passes guardrails.check_text.
Writes outputs/phase6_step1_memo.md (STUBBED until wired in).
"""

from __future__ import annotations

from typing import Any, Optional

from agents import phase2_6_shared as shared
from schemas import Claim

AGENT = "phase6_memo"
DATA_REF = "payments.mock_sales_data() (MOCKED)"

SYSTEM = """You write a short operating memo for a founder from sales metrics. The metrics may be MOCKED (fake test data): if so, say plainly that they can't support a real decision.
Input: the metrics, the founder's targets (may be empty) and the system's recommendation, which you must not change.
Reply with JSON only:
{"summary":"","observations":[""],"next_experiments":[""],"support_replies":[{"situation":"","reply":""}]}
At most 3 observations and 3 experiments. Two support replies: a customer asking for a refund, and a customer who can't access the product.
Support replies are drafts the founder sends under their own name. The founder decides and handles every refund; the reply never says money was refunded or moved. No promises, no invented numbers."""


def metrics_from(store: Any) -> dict[str, Any]:
    """Plain counts and sums from the store (amounts in minor units)."""
    from reconcile import mock_payout_statement, reconcile

    payout = mock_payout_statement(store)
    report = reconcile(store, payout)
    orders = len(store.orders)
    paid = len(store.payments)
    refunded = len(store.refunds)
    return {
        "orders": orders,
        "paid_orders": paid,
        "refunded_orders": refunded,
        "conversion_rate": round(paid / orders, 3) if orders else 0.0,
        "refund_rate": round(refunded / paid, 3) if paid else 0.0,
        "gross": payout["gross"],
        "fees": payout["fees"],
        "refunds": payout["refunds"],
        "net": payout["net"],
        "reconciled": report["ok"],
        "currency": next(iter(store.orders.values()))["currency"] if store.orders else "",
    }


def compare(metrics: dict[str, Any], targets: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, target in (targets or {}).items():
        key = name[4:] if name.startswith("max_") else name
        if key not in metrics or not isinstance(target, (int, float)):
            continue
        actual = metrics[key]
        met = actual <= target if name.startswith("max_") else actual >= target
        rows.append({"metric": key, "target": target, "limit": "at most" if name.startswith("max_") else "at least",
                     "actual": actual, "met": met})
    return rows


def recommend(mocked: bool, rows: list[dict[str, Any]]) -> tuple[str, str]:
    if mocked:
        return "repeat", "The data is MOCKED: fake sales can't support persevere or pivot. Collect real sales first."
    if not rows:
        return "repeat", "No targets were set at Gate 2, so there is nothing to judge against. Set targets first."
    missed = [r["metric"] for r in rows if not r["met"]]
    if len(missed) == len(rows):
        return "stop", f"Every target was missed ({', '.join(missed)})."
    if missed:
        return "pivot", f"Some targets were missed ({', '.join(missed)})."
    return "go", "Every target was met: persevere."


def agent(state: dict[str, Any]) -> dict[str, Any]:
    from payments import mock_sales_data

    store = state.get("sales_store")
    mocked = True  # every store today is MOCKED; real sales data is roadmap
    if store is None:
        store = mock_sales_data()
    metrics = metrics_from(store)
    targets = state.get("targets") if isinstance(state.get("targets"), dict) else None
    rows = compare(metrics, targets)
    outcome, why = recommend(mocked, rows)

    payload = {"metrics": metrics, "mocked": mocked, "targets": targets or {}, "recommendation": outcome, "why": why}
    data, found, usage = shared.ask_guarded(AGENT, SYSTEM, payload, round_no=int(state.get("round") or 1), max_tokens=900)

    observations = [Claim(text=f"{t} (on MOCKED data)" if mocked else t, support="ASSUMPTION", area="observation",
                          agent=AGENT).model_dump() for t in shared.strings(data.get("observations"), limit=3, chars=240)]
    metric_claims = [Claim(text=f"{k}: {metrics[k]}" + (" (MOCKED)" if mocked else ""), support="evidence",
                           evidence_ref=DATA_REF, area="metrics", agent=AGENT).model_dump()
                     for k in ("orders", "paid_orders", "refund_rate", "net")]
    replies = []
    for r in (data.get("support_replies") if isinstance(data.get("support_replies"), list) else [])[:2]:
        if isinstance(r, dict) and str(r.get("reply", "")).strip():
            replies.append({"situation": shared.common.cut(r.get("situation", ""), 80), "reply": shared.common.cut(r["reply"], 600),
                            "sent": False})
    experiments = shared.strings(data.get("next_experiments"), limit=3, chars=200)
    claims = metric_claims + observations

    cur = metrics["currency"]
    metric_rows = "\n".join(f"| {k} | {v} |" for k, v in metrics.items())
    target_rows = "\n".join(f"| {r['metric']} | {r['limit']} {r['target']} | {r['actual']} | {'met' if r['met'] else '**missed**'} |"
                            for r in rows) or "| _no targets set at Gate 2_ | | | |"
    replies_md = "\n\n".join(f"### {r['situation'] or 'Support reply'}\n\n{r['reply']}" for r in replies) or "_None drafted._"
    body = (
        ("> **MOCKED data**: there are no real customers or sales. These numbers come from "
         f"`{DATA_REF}` and can't support a real decision.\n\n" if mocked else "")
        + f"## Metrics\n\nAmounts in minor units of {cur or 'the currency'}.\n\n| Metric | Value |\n|---|---|\n{metric_rows}\n\n"
        f"## Against the targets set at Gate 2\n\n| Metric | Target | Actual | Result |\n|---|---|---|---|\n{target_rows}\n\n"
        f"## Recommendation (fixed rules, not the model)\n\n**{outcome.upper()}**: {why}\n\n"
        "The founder approves or rejects this at the Gate 6 decision.\n\n"
        f"## Memo\n\n{shared.common.cut(data.get('summary', ''), 800) or '_No summary._'}\n\n"
        f"### Observations\n\n{shared.bullet_claims(observations)}\n\n"
        f"### Next experiments\n\n{shared.bullets(experiments)}\n\n"
        "## Support-reply drafts (not sent)\n\nThe founder edits and sends these under their own name, and decides every "
        f"refund in their own payment provider.\n\n{replies_md}\n"
    )
    draft = {"metrics": metrics, "mocked": mocked, "targets": targets, "comparison": rows, "recommendation": outcome,
             "why": why, "summary": shared.common.cut(data.get("summary", ""), 800), "observations": observations,
             "next_experiments": experiments, "support_replies": replies}
    return shared.finish(state, AGENT, 6, 1, "memo", "metrics, persevere-or-pivot memo and support replies", body, draft,
                         claims, found, usage)
