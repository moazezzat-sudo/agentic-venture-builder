"""MOCKED delivery: a paid order gets one access token; a refund revokes it.

MOCKED: the token is a random string kept in the in-memory MockStore. Nothing is emailed or
sent; in a real store the founder's own platform would show the buyer their download.

    from delivery import deliver, has_access, revoke
    token = deliver(store, order_id)     # idempotent: the same order always gets the same token
    has_access(store, token)             # True until the order is refunded
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from payments import MockStore

MOCKED = True


def deliver(store: "MockStore", order_id: str) -> str:
    """Issue the access token for a paid order. Calling it again returns the same token."""
    order = store.orders[order_id]
    if order["status"] not in ("paid", "delivered"):
        raise ValueError(f"order {order_id} is {order['status']}; only paid orders are delivered")
    if order.get("token"):
        return order["token"]
    token = "tok_" + secrets.token_hex(12)
    store.tokens[token] = {"order_id": order_id, "active": True}
    order["token"] = token
    order["status"] = "delivered"
    store.log("delivery", "deliver_access", order_id=order_id)
    return token


def has_access(store: "MockStore", token: str) -> bool:
    record = store.tokens.get(token)
    return bool(record and record["active"])


def revoke(store: "MockStore", order_id: str) -> None:
    """Deactivate every token of the order."""
    for record in store.tokens.values():
        if record["order_id"] == order_id and record["active"]:
            record["active"] = False
            store.log("delivery", "revoke_access", order_id=order_id)
