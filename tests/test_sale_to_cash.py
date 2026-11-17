"""Mocked sale to cash (PLAN.md section 6): payment -> delivery, idempotency, refund revokes, reconciliation.

All in memory: no provider, no keys, no network. The decision log goes to a temp file.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import delivery  # noqa: E402
import payments  # noqa: E402
import reconcile  # noqa: E402
import refunds  # noqa: E402
from payments import ApprovalRequired, GuardrailViolation, MockStore  # noqa: E402

COPY = "A printable interview kit for SME hiring managers. One-time purchase."


@pytest.fixture
def store(tmp_path):
    s = MockStore(log_path=tmp_path / "log.json")
    payments.publish_listing(s, "kit", "Interview kit", 25000, "EGP", COPY, founder_approved=True)
    return s


def paid(store, customer="cust_001"):
    order = payments.create_order(store, "kit", customer)
    result = payments.handle_event(store, payments.mock_payment_event(store, order["order_id"]))
    return order, result


def log(store):
    return json.loads(store.log_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- founder approval


@pytest.mark.parametrize("approved", [False, None, "yes", 1])
def test_listing_needs_explicit_founder_approval(tmp_path, approved):
    with pytest.raises(ApprovalRequired):
        payments.publish_listing(MockStore(log_path=tmp_path / "l.json"), "kit", "Kit", 100, "EGP", COPY, founder_approved=approved)


@pytest.mark.parametrize("bad", ["Only 3 left, hurry!", "Join 5,000+ happy customers", "Guaranteed income in 30 days"])
def test_listing_copy_must_pass_the_guardrails(tmp_path, bad):
    with pytest.raises(GuardrailViolation):
        payments.publish_listing(MockStore(log_path=tmp_path / "l.json"), "kit", "Kit", 100, "EGP", f"{COPY} {bad}", founder_approved=True)


def test_listing_approval_is_logged_as_founder(store):
    entry = [e for e in log(store) if e["action"] == "publish_listing"][0]
    assert entry["approved_by"] == "founder" and entry["mocked"] is True
    for key in ("action", "sources", "model", "cost", "approved_by"):
        assert key in entry


@pytest.mark.parametrize("approved", [False, None, "yes"])
def test_refund_needs_explicit_founder_approval(store, approved):
    order, _ = paid(store)
    with pytest.raises(ApprovalRequired):
        refunds.request_refund(store, order["order_id"], "asked", founder_approved=approved)
    assert store.orders[order["order_id"]]["status"] == "delivered" and not store.refunds


def test_no_personal_or_card_data_as_customer(store):
    for ref in ("sara@example.com", "4242 4242 4242 4242", "Sara Ahmed"):
        with pytest.raises(ValueError):
            payments.create_order(store, "kit", ref)


# --------------------------------------------------------------------------- payment -> delivery


def test_payment_triggers_delivery(store):
    order, result = paid(store)
    assert result["status"] == "delivered" and result["duplicate"] is False
    assert delivery.has_access(store, result["token"])
    assert store.orders[order["order_id"]]["token"] == result["token"]


def test_no_delivery_before_payment(store):
    order = payments.create_order(store, "kit", "cust_009")
    with pytest.raises(ValueError):
        delivery.deliver(store, order["order_id"])
    assert not store.tokens


def test_wrong_amount_delivers_nothing(store):
    order = payments.create_order(store, "kit", "cust_002")
    with pytest.raises(ValueError):
        payments.handle_event(store, payments.mock_payment_event(store, order["order_id"], amount=1))
    assert not store.tokens and order["order_id"] not in store.payments and not store.ledger


# --------------------------------------------------------------------------- idempotency


def test_replayed_payment_event_changes_nothing(store):
    order, first = paid(store)
    before = (len(store.ledger), len(store.tokens), len(store.payments))
    replay = payments.handle_event(store, payments.mock_payment_event(store, order["order_id"]))
    assert replay["duplicate"] is True and replay["token"] == first["token"]
    assert (len(store.ledger), len(store.tokens), len(store.payments)) == before
    assert delivery.deliver(store, order["order_id"]) == first["token"]  # delivery itself is idempotent too


def test_event_without_idempotency_key_is_refused(store):
    order = payments.create_order(store, "kit", "cust_003")
    event = payments.mock_payment_event(store, order["order_id"])
    del event["idempotency_key"]
    with pytest.raises(ValueError):
        payments.handle_event(store, event)


# --------------------------------------------------------------------------- refunds


def test_refund_revokes_access_and_reverses_the_ledger(store):
    order, result = paid(store)
    event = refunds.request_refund(store, order["order_id"], "asked within 14 days", founder_approved=True)
    out = payments.handle_event(store, event)
    assert out["status"] == "refunded" and not delivery.has_access(store, result["token"])
    assert {"order_id": order["order_id"], "kind": "refund", "amount": -25000} in store.ledger
    assert [e for e in log(store) if e["action"] == "refund_approved"][0]["approved_by"] == "founder"

    again = payments.handle_event(store, event)
    assert again["duplicate"] is True and len(store.refunds) == 1
    assert sum(1 for e in store.ledger if e["kind"] == "refund") == 1


def test_cannot_refund_an_unpaid_order(store):
    order = payments.create_order(store, "kit", "cust_004")
    with pytest.raises(ValueError):
        refunds.request_refund(store, order["order_id"], "x", founder_approved=True)


# --------------------------------------------------------------------------- reconciliation


def test_reconciliation_matches(store):
    o1, _ = paid(store, "cust_001")
    o2, _ = paid(store, "cust_002")
    payments.handle_event(store, refunds.request_refund(store, o2["order_id"], "x", founder_approved=True))
    payout = reconcile.mock_payout_statement(store)
    report = reconcile.reconcile(store, payout)
    assert report["ok"], report["mismatches"]
    fee = payments.mock_fee(25000)
    assert payout == {"gross": 50000, "fees": 2 * fee, "refunds": 25000, "net": 50000 - 2 * fee - 25000}


def test_reconciliation_flags_mismatches(store):
    o1, result = paid(store)
    payout = reconcile.mock_payout_statement(store)
    payout["net"] -= 100
    assert not reconcile.reconcile(store, payout)["ok"]

    store.tokens[result["token"]]["active"] = False  # paid but no access
    store.ledger.append({"order_id": o1["order_id"], "kind": "sale", "amount": 25000})  # double sale
    report = reconcile.reconcile(store, reconcile.mock_payout_statement(store))
    text = " ".join(report["mismatches"])
    assert "2 sale entries" in text and "0 active access tokens" in text and "gross" in text


# --------------------------------------------------------------------------- the test log


def test_payment_test_log_is_written_from_a_real_run(tmp_path):
    out = payments.run_payment_test(out_path=tmp_path / "payment_test_log.md", log_path=tmp_path / "log.json")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("> **MOCKED**")
    assert "| FAIL |" not in text and "steps passed" in text and "**Matches: True.**" in text


def test_no_payment_provider_or_keys_in_the_code():
    for name in ("payments.py", "delivery.py", "refunds.py", "reconcile.py"):
        src = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "import stripe" not in src and "import requests" not in src and "api_key" not in src
        assert "mocked = true" in src
