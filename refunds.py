"""MOCKED refunds: the founder approves, a simulated provider event follows, access is revoked.

MOCKED: the system never refunds money. In real life the founder issues the refund in their
own payment provider. request_refund() needs founder_approved=True and returns the fake
refund.succeeded event the provider would send; payments.handle_event() applies it once.

    from refunds import request_refund
    event = request_refund(store, order_id, "reason", founder_approved=True)
    payments.handle_event(store, event)   # order refunded, ledger reversed, token revoked
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from payments import MockStore

MOCKED = True


def request_refund(store: "MockStore", order_id: str, reason: str, founder_approved: bool) -> dict[str, Any]:
    """Return the mocked refund.succeeded event for a paid order. Needs the founder's explicit approval."""
    from payments import ApprovalRequired

    if founder_approved is not True:
        raise ApprovalRequired("a refund moves money: the founder must approve it")
    order = store.orders.get(order_id)
    if order is None:
        raise KeyError(f"no order {order_id!r}")
    if order_id not in store.payments:
        raise ValueError(f"order {order_id} was never paid; there is nothing to refund")
    payment = store.payments[order_id]
    store.log("refunds", "refund_approved", approved_by="founder", order_id=order_id, amount=payment["amount"], reason=reason)
    return {"type": "refund.succeeded", "id": f"evt_ref_{order_id}", "idempotency_key": f"ref_{order_id}",
            "order_id": order_id, "amount": payment["amount"], "currency": payment["currency"], "reason": reason,
            "mocked": True}


def apply_refund(store: "MockStore", event: dict[str, Any]) -> dict[str, Any]:
    """Mark the order refunded, add a reversing ledger entry and revoke access.

    The payment fee is not returned on a refund (ASSUMPTION for the mock; providers differ).
    """
    from delivery import revoke

    order_id = event["order_id"]
    order = store.orders[order_id]
    if order["status"] == "refunded":
        raise ValueError(f"order {order_id} is already refunded")
    if event["amount"] > store.payments[order_id]["amount"]:
        raise ValueError("refund is larger than the payment")
    store.refunds[order_id] = {"order_id": order_id, "amount": event["amount"], "currency": event["currency"],
                               "reason": event.get("reason", ""), "event_id": event["id"]}
    store.ledger.append({"order_id": order_id, "kind": "refund", "amount": -event["amount"]})
    order["status"] = "refunded"
    revoke(store, order_id)
    store.log("refunds", "refund_applied", order_id=order_id, amount=event["amount"])
    return {"event": event["type"], "order_id": order_id, "status": order["status"], "token": order.get("token")}
