"""MOCKED reconciliation: orders, payments, fees, refunds and the payout must agree.

    from reconcile import mock_payout_statement, reconcile
    report = reconcile(store, mock_payout_statement(store))
    report["ok"]           # True when everything matches
    report["mismatches"]   # what doesn't, in plain words

Checks:
  - gross - fees - refunds = net, from the ledger, equals the payout statement's net
  - every payment matches its order's amount and currency
  - each order has at most one sale entry (no double delivery or double charge)
  - every paid order has an active access token; every refunded or unpaid order has none

MOCKED: the payout statement is computed from the mocked provider records (payments and
refunds), independently of our ledger, to stand in for the provider's real statement.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from payments import MockStore

MOCKED = True


def mock_payout_statement(store: "MockStore") -> dict[str, int]:
    """The MOCKED provider's payout statement, from its own payment and refund records."""
    gross = sum(p["amount"] for p in store.payments.values())
    fees = sum(p["fee"] for p in store.payments.values())
    refunds = sum(r["amount"] for r in store.refunds.values())
    return {"gross": gross, "fees": fees, "refunds": refunds, "net": gross - fees - refunds}


def reconcile(store: "MockStore", payout: dict[str, int]) -> dict[str, Any]:
    mismatches: list[str] = []

    totals = {
        "gross": sum(e["amount"] for e in store.ledger if e["kind"] == "sale"),
        "fees": -sum(e["amount"] for e in store.ledger if e["kind"] == "fee"),
        "refunds": -sum(e["amount"] for e in store.ledger if e["kind"] == "refund"),
    }
    totals["net"] = totals["gross"] - totals["fees"] - totals["refunds"]
    for key in ("gross", "fees", "refunds", "net"):
        if totals[key] != payout.get(key):
            mismatches.append(f"{key}: ledger {totals[key]} vs payout statement {payout.get(key)}")

    sales = Counter(e["order_id"] for e in store.ledger if e["kind"] == "sale")
    for order_id, count in sales.items():
        if count > 1:
            mismatches.append(f"{order_id}: {count} sale entries (double charge or double delivery)")

    active = Counter(t["order_id"] for t in store.tokens.values() if t["active"])
    rows = []
    for order_id, order in store.orders.items():
        payment = store.payments.get(order_id)
        refund = store.refunds.get(order_id)
        if payment and (payment["amount"] != order["amount"] or payment["currency"] != order["currency"]):
            mismatches.append(f"{order_id}: payment {payment['amount']} {payment['currency']} vs order {order['amount']} {order['currency']}")
        if payment and not refund and active[order_id] != 1:
            mismatches.append(f"{order_id}: paid but has {active[order_id]} active access tokens (expected 1)")
        if (refund or not payment) and active[order_id]:
            mismatches.append(f"{order_id}: {'refunded' if refund else 'unpaid'} but still has access")
        if payment and order_id not in sales:
            mismatches.append(f"{order_id}: paid but no sale in the ledger")
        rows.append({
            "order_id": order_id, "status": order["status"],
            "gross": payment["amount"] if payment else 0, "fee": payment["fee"] if payment else 0,
            "refund": refund["amount"] if refund else 0, "access": active[order_id] > 0,
        })
    for order_id in store.payments:
        if order_id not in store.orders:
            mismatches.append(f"{order_id}: payment without an order")

    return {"ok": not mismatches, "totals": totals, "payout": dict(payout), "orders": rows, "mismatches": mismatches}


def reconciliation_markdown(report: dict[str, Any]) -> str:
    lines = ["| Order | Status | Gross | Fee | Refund | Net | Access |", "|---|---|---|---|---|---|---|"]
    for r in report["orders"]:
        net = r["gross"] - r["fee"] - r["refund"]
        lines.append(f"| {r['order_id']} | {r['status']} | {r['gross']} | {r['fee']} | {r['refund']} | {net} | {'yes' if r['access'] else 'no'} |")
    t, p = report["totals"], report["payout"]
    lines += [
        "",
        f"Ledger: gross {t['gross']} - fees {t['fees']} - refunds {t['refunds']} = net {t['net']}.",
        f"Payout statement (MOCKED): gross {p['gross']} - fees {p['fees']} - refunds {p['refunds']} = net {p['net']}.",
        "",
        f"**Matches: {report['ok']}.** " + ("No mismatches." if report["ok"] else "Mismatches: " + "; ".join(report["mismatches"])),
    ]
    return "\n".join(lines)
