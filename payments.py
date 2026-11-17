"""MOCKED checkout and payment events (PLAN.md section 6, "Sale to cash").

MOCKED: everything here runs on fake in-memory events. There is no payment provider, no
API key, no sandbox, and no money. The system never holds, moves or refunds money: in real
life the founder sells through their own provider account, and these functions only
simulate the provider's events so delivery, refunds and reconciliation can be tested.

    from payments import MockStore, publish_listing, create_order, mock_payment_event, handle_event
    store = MockStore()
    publish_listing(store, "kit", "Interview kit", 25000, "EGP", copy, founder_approved=True)
    order = create_order(store, "kit", "cust_001")
    result = handle_event(store, mock_payment_event(store, order["order_id"]))   # -> delivery token
    handle_event(store, same_event)    # duplicate: returns the original result, nothing new

Flow: a store listing goes live only with the founder's approval and a clean guardrail
check. A payment.succeeded event delivers access (delivery.py). Each event carries an
idempotency key, so a replay creates no second token or ledger entry. A refund needs the
founder's approval and revokes access (refunds.py). reconcile.py matches orders, payments,
fees, refunds and the payout.

Amounts are integers in minor units (piasters for EGP, cents for USD).

Run the full mocked test and write outputs/payment_test_log.md:

    python payments.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from logger import log_action

MOCKED = True

# MOCKED fee rule, an ASSUMPTION for the test only: 3% of the amount. Not any real provider's pricing.
MOCK_FEE_RATE = 0.03

_CUSTOMER_REF = re.compile(r"^cust_[A-Za-z0-9]{1,32}$")


class ApprovalRequired(PermissionError):
    """Raised when an action needs the founder's explicit approval and doesn't have it."""


class GuardrailViolation(ValueError):
    """Raised when text breaks a guardrail (fake reviews, urgency, income promises ...)."""


@dataclass
class MockStore:
    """All mocked sale-to-cash state, in memory. Nothing here leaves the process."""

    listings: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    payments: dict[str, dict[str, Any]] = field(default_factory=dict)  # by order_id
    refunds: dict[str, dict[str, Any]] = field(default_factory=dict)  # by order_id
    tokens: dict[str, dict[str, Any]] = field(default_factory=dict)  # access token -> {order_id, active}
    ledger: list[dict[str, Any]] = field(default_factory=list)
    processed: dict[str, dict[str, Any]] = field(default_factory=dict)  # idempotency key -> first result
    log_path: Optional[Path] = None  # decision_log.json by default
    quiet: bool = False  # True for generated MOCKED datasets: nothing is logged, no approval is claimed

    def log(self, agent: str, action: str, approved_by: Optional[str] = None, **extra: Any) -> None:
        if self.quiet:
            return
        log_action(agent=agent, action=action, sources=[], model=None, cost=0, approved_by=approved_by,
                   log_path=self.log_path, mocked=True, **extra)


def publish_listing(
    store: MockStore,
    product_id: str,
    title: str,
    price: int,
    currency: str,
    copy: str,
    founder_approved: bool,
) -> dict[str, Any]:
    """Put a product on the MOCKED store. Needs founder_approved=True and copy that passes the guardrails.

    MOCKED: nothing is posted anywhere; the listing only exists in the MockStore.
    """
    if founder_approved is not True:
        raise ApprovalRequired("the founder must approve the store listing before it goes live")
    if not isinstance(price, int) or price <= 0:
        raise ValueError("price must be a positive integer in minor units")
    from guardrails import check_text

    violations = check_text(f"{title}\n{copy}")
    if violations:
        rules = ", ".join(sorted({v["rule"] for v in violations}))
        raise GuardrailViolation(f"listing refused by the guardrails ({rules}): {violations[0]['reason']}")
    listing = {"product_id": product_id, "title": title, "price": price, "currency": currency.upper(),
               "copy": copy, "status": "live (MOCKED: not posted anywhere)"}
    store.listings[product_id] = listing
    store.log("payments", "publish_listing", approved_by="founder", product_id=product_id, price=price, currency=listing["currency"])
    return listing


def create_order(store: MockStore, product_id: str, customer_ref: str) -> dict[str, Any]:
    """Open a pending order. customer_ref is a pseudonym (cust_...); no names, emails or card data."""
    if product_id not in store.listings:
        raise KeyError(f"no live listing for {product_id!r}")
    if not isinstance(customer_ref, str) or not _CUSTOMER_REF.match(customer_ref):
        raise ValueError("customer_ref must be a pseudonym like 'cust_001'; personal or card data is never stored")
    listing = store.listings[product_id]
    order_id = f"ord_{len(store.orders) + 1:04d}"
    order = {"order_id": order_id, "product_id": product_id, "customer_ref": customer_ref,
             "amount": listing["price"], "currency": listing["currency"], "status": "pending", "token": None}
    store.orders[order_id] = order
    store.log("payments", "create_order", order_id=order_id, amount=order["amount"], currency=order["currency"])
    return order


def mock_fee(amount: int) -> int:
    """MOCKED fee (ASSUMPTION: 3%), rounded to the nearest minor unit."""
    return int(round(amount * MOCK_FEE_RATE))


def mock_payment_event(store: MockStore, order_id: str, amount: Optional[int] = None) -> dict[str, Any]:
    """A fake payment.succeeded event, as a provider's webhook would send it. MOCKED.

    The idempotency key is tied to the order's payment, so a replayed event has the same key.
    amount defaults to the order amount; pass another value to test a mismatch.
    """
    order = store.orders[order_id]
    amount = order["amount"] if amount is None else amount
    return {"type": "payment.succeeded", "id": f"evt_pay_{order_id}", "idempotency_key": f"pay_{order_id}",
            "order_id": order_id, "amount": amount, "currency": order["currency"], "fee": mock_fee(amount),
            "mocked": True}


def handle_event(store: MockStore, event: dict[str, Any]) -> dict[str, Any]:
    """Apply a mocked provider event once. A replayed idempotency key returns the first result, unchanged."""
    key = event.get("idempotency_key")
    if not key:
        raise ValueError("event has no idempotency_key")
    if key in store.processed:
        store.log("payments", "duplicate_event_ignored", event_type=event.get("type"), idempotency_key=key)
        return {**store.processed[key], "duplicate": True}

    if event.get("type") == "payment.succeeded":
        result = _apply_payment(store, event)
    elif event.get("type") == "refund.succeeded":
        from refunds import apply_refund

        result = apply_refund(store, event)
    else:
        raise ValueError(f"unknown mocked event type: {event.get('type')!r}")
    store.processed[key] = result
    return {**result, "duplicate": False}


def _apply_payment(store: MockStore, event: dict[str, Any]) -> dict[str, Any]:
    from delivery import deliver

    order = store.orders.get(event["order_id"])
    if order is None:
        raise KeyError(f"payment for unknown order {event['order_id']!r}")
    if event["amount"] != order["amount"] or event["currency"] != order["currency"]:
        raise ValueError(
            f"payment {event['amount']} {event['currency']} does not match order "
            f"{order['amount']} {order['currency']}; nothing delivered"
        )
    if order["status"] != "pending":
        raise ValueError(f"order {order['order_id']} is {order['status']}, not pending")
    store.payments[order["order_id"]] = {"order_id": order["order_id"], "amount": event["amount"], "fee": event["fee"],
                                         "currency": event["currency"], "event_id": event["id"]}
    store.ledger.append({"order_id": order["order_id"], "kind": "sale", "amount": event["amount"]})
    store.ledger.append({"order_id": order["order_id"], "kind": "fee", "amount": -event["fee"]})
    order["status"] = "paid"
    store.log("payments", "payment_succeeded", order_id=order["order_id"], amount=event["amount"], fee=event["fee"])
    token = deliver(store, order["order_id"])
    return {"event": event["type"], "order_id": order["order_id"], "status": order["status"], "token": token}


def mock_sales_data(price: int = 25000, currency: str = "EGP") -> MockStore:
    """A fixed MOCKED dataset for Phase 6: 6 orders, 4 paid, 1 of them refunded, 2 left unpaid.

    MOCKED: no real customers or sales. The store is quiet: nothing goes to decision_log.json
    and no founder approval is claimed, because nothing is published. The listing is inserted
    directly and marked as a MOCKED dataset.
    """
    from refunds import apply_refund

    store = MockStore(quiet=True)
    store.listings["mock"] = {"product_id": "mock", "title": "MOCKED dataset", "price": price, "currency": currency,
                              "copy": "", "status": "MOCKED dataset: not published, no founder approval asked"}
    orders = [create_order(store, "mock", f"cust_{i:03d}") for i in range(1, 7)]
    for order in orders[:4]:
        handle_event(store, mock_payment_event(store, order["order_id"]))
    payment = store.payments[orders[1]["order_id"]]
    store.processed[f"ref_{orders[1]['order_id']}"] = apply_refund(store, {
        "type": "refund.succeeded", "id": f"evt_ref_{orders[1]['order_id']}", "order_id": orders[1]["order_id"],
        "amount": payment["amount"], "currency": currency, "reason": "MOCKED refund", "mocked": True})
    return store


def run_payment_test(out_path: Optional[Path] = None, log_path: Optional[Path] = None) -> Path:
    """Run the whole mocked sale-to-cash flow and write outputs/payment_test_log.md from what happened."""
    from config import settings
    from delivery import has_access
    from reconcile import mock_payout_statement, reconcile, reconciliation_markdown
    from refunds import request_refund
    from schemas import utc_now

    store = MockStore(log_path=log_path)
    steps: list[tuple[str, str, str]] = []  # (step, what happened, result)

    def step(name: str, outcome: str, ok: bool) -> None:
        steps.append((name, outcome, "PASS" if ok else "FAIL"))

    copy = ("A printable interview kit for SME hiring managers: question bank, score sheet and "
            "a structured interview guide. One-time purchase.")

    try:
        publish_listing(store, "kit", "Interview kit", 25000, "EGP", copy, founder_approved=False)
        step("Listing without founder approval", "published", False)
    except ApprovalRequired as exc:
        step("Listing without founder approval", f"refused: {exc}", True)

    try:
        publish_listing(store, "kit", "Interview kit", 25000, "EGP", copy + " Only 3 left, offer ends tonight!", founder_approved=True)
        step("Listing with fake urgency", "published", False)
    except GuardrailViolation as exc:
        step("Listing with fake urgency", f"refused: {exc}", True)

    publish_listing(store, "kit", "Interview kit", 25000, "EGP", copy, founder_approved=True)
    step("Listing approved by the founder", "live on the MOCKED store (approved_by: founder)", "kit" in store.listings)

    o1 = create_order(store, "kit", "cust_001")
    o2 = create_order(store, "kit", "cust_002")
    o3 = create_order(store, "kit", "cust_003")

    first = handle_event(store, mock_payment_event(store, o1["order_id"]))
    step("Payment event for order 1", f"delivered token {first['token'][:8]}...", has_access(store, first["token"]))

    ledger_before = len(store.ledger)
    replay = handle_event(store, mock_payment_event(store, o1["order_id"]))
    step("Same payment event replayed", f"duplicate={replay['duplicate']}, same token: {replay['token'] == first['token']}, "
         f"new ledger entries: {len(store.ledger) - ledger_before}, tokens issued: {len(store.tokens)}",
         replay["duplicate"] and replay["token"] == first["token"] and len(store.ledger) == ledger_before and len(store.tokens) == 1)

    try:
        handle_event(store, {**mock_payment_event(store, o3["order_id"], amount=100), "idempotency_key": "pay_bad"})
        step("Payment with the wrong amount", "delivered", False)
    except ValueError as exc:
        step("Payment with the wrong amount", f"rejected, nothing delivered: {exc}", o3["token"] is None)

    second = handle_event(store, mock_payment_event(store, o2["order_id"]))
    step("Payment event for order 2", f"delivered token {second['token'][:8]}...", has_access(store, second["token"]))

    try:
        request_refund(store, o2["order_id"], "customer asked within 14 days", founder_approved=False)
        step("Refund without founder approval", "refunded", False)
    except ApprovalRequired as exc:
        step("Refund without founder approval", f"refused: {exc}", True)

    refund_event = request_refund(store, o2["order_id"], "customer asked within 14 days", founder_approved=True)
    refunded = handle_event(store, refund_event)
    step("Refund approved by the founder (simulated)", f"order {refunded['order_id']} {refunded['status']}; "
         f"access now {has_access(store, second['token'])}", not has_access(store, second["token"]))

    again = handle_event(store, refund_event)
    step("Same refund event replayed", f"duplicate={again['duplicate']}, refunds recorded: {len(store.refunds)}",
         again["duplicate"] and len(store.refunds) == 1)

    report = reconcile(store, mock_payout_statement(store))
    step("Reconciliation", f"gross - fees - refunds = net payout: {report['ok']}", report["ok"])

    broken = mock_payout_statement(store)
    broken["net"] -= 100
    bad = reconcile(store, broken)
    step("Reconciliation against a payout statement that is off by 100", f"mismatch flagged: {not bad['ok']}", not bad["ok"])

    passed = sum(1 for s in steps if s[2] == "PASS")
    rows = "\n".join(f"| {i} | {n} | {o.replace('|', '/')} | {r} |" for i, (n, o, r) in enumerate(steps, 1))
    text = (
        "> **MOCKED**: this is a test of the mocked sale-to-cash flow. There is no payment provider, no keys, "
        "no sandbox and no money. Customers are pseudonyms; the fee is an ASSUMPTION (3%), not any provider's pricing.\n\n"
        f"# Payment and delivery test log\n\nGenerated by `payments.run_payment_test()` (`python payments.py`) on {utc_now()}.\n\n"
        f"**{passed}/{len(steps)} steps passed.** Amounts are in piasters (100 piasters = 1 EGP).\n\n"
        f"| # | Step | What happened | Result |\n|---|---|---|---|\n{rows}\n\n"
        f"## Reconciliation\n\n{reconciliation_markdown(report)}\n"
    )
    path = Path(out_path or Path(settings.outputs_dir) / "payment_test_log.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    out = run_payment_test()
    print(f"Wrote {out}")
    sys.exit(0 if "FAIL |" not in out.read_text(encoding="utf-8") else 1)
