"""Razorpay Test-Mode payments for the Phase 13 demo portal.

Secrets live ONLY in env vars - never in the frontend or the extension:
    RAZORPAY_KEY_ID        (rzp_test_...)   - the only value the browser gets
    RAZORPAY_KEY_SECRET
    RAZORPAY_WEBHOOK_SECRET

If RAZORPAY_KEY_ID / _SECRET are unset the module runs in MOCK mode: orders and
receipts are synthesised locally so the demo still works offline. Real mode is
used automatically once the env vars are present.

The payment result is written to Firestore (`payment_transactions`) and, more
importantly, the demo's success page renders the transaction id + receipt so the
existing Phase 8 Verification Agent can read it as evidence - no agent changes.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid

from memory.store import get_store

log = logging.getLogger("reach.payments")

KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

REAL = bool(KEY_ID and KEY_SECRET)

_client = None
if REAL:
    try:
        import razorpay  # optional dependency

        _client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))
        log.info("[payments] Razorpay REAL mode (key_id=%s...)", KEY_ID[:12])
    except Exception as exc:  # noqa: BLE001
        log.warning("[payments] razorpay SDK unavailable (%s) - MOCK mode", exc)
        _client = None
        REAL = False
if not REAL:
    log.info("[payments] MOCK mode - set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET for live test checkout")

PUBLIC_KEY_ID = KEY_ID or "rzp_test_MOCK"


def _store():
    return get_store()


def create_order(amount_rupees: float, consumer: str = "", note: str = "") -> dict:
    """amount_rupees -> Razorpay order (paise). Returns what the browser needs."""
    paise = int(round(float(amount_rupees) * 100))
    if REAL and _client:
        order = _client.order.create(
            {"amount": paise, "currency": "INR", "payment_capture": 1,
             "notes": {"consumer": consumer, "note": note}}
        )
        order_id = order["id"]
        mock = False
    else:
        order_id = "order_mock_" + uuid.uuid4().hex[:16]
        mock = True

    doc = {
        "order_id": order_id, "amount": paise, "currency": "INR",
        "consumer": consumer, "note": note, "status": "CREATED",
        "payment_id": None, "verified": False, "mock": mock,
        "created_at": time.time(),
    }
    _store().add("payment_transactions", doc, order_id)
    log.info("[payments] created order %s  amount=%d paise  mock=%s", order_id, paise, mock)
    return {
        "order_id": order_id,
        "amount": paise,
        "currency": "INR",
        "key_id": PUBLIC_KEY_ID,
        "mock": mock,
    }


def _valid_signature(order_id: str, payment_id: str, signature: str) -> bool:
    body = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(KEY_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_payment(order_id: str, payment_id: str, signature: str = "") -> dict:
    """Verify the Razorpay signature (real) or accept a synthetic id (mock).
    Never trust a frontend-only 'success'."""
    row = _store().query("payment_transactions", {"order_id": order_id})
    record = row[0] if row else {"order_id": order_id, "amount": 0, "created_at": time.time()}

    if REAL:
        ok = _valid_signature(order_id, payment_id, signature)
    else:
        ok = bool(payment_id) and payment_id.startswith("pay_")

    record.update(
        payment_id=payment_id,
        signature_valid=ok,
        verified=ok,
        status="SUCCESS" if ok else "FAILED",
        verified_at=time.time(),
    )
    _store().set("payment_transactions", order_id, {k: v for k, v in record.items() if k != "_id"})
    log.info("[payments] verify order=%s payment=%s -> %s", order_id, payment_id, record["status"])

    receipt = "RCPT-" + order_id.split("_")[-1][:10].upper()
    return {
        "verified": ok,
        "status": record["status"],
        "order_id": order_id,
        "payment_id": payment_id,
        "receipt": receipt if ok else None,
        "amount": record.get("amount", 0),
    }


def test_capture(order_id: str) -> dict:
    """Demo helper: complete a TEST order without the checkout UI, so REACH can
    pay fully hands-free. Only ever used with an rzp_test_ / mock key
    (enforced in main.py). Produces a real receipt shape for the Verification Agent."""
    row = _store().query("payment_transactions", {"order_id": order_id})
    record = row[0] if row else {"order_id": order_id, "amount": 0}
    payment_id = "pay_test_" + uuid.uuid4().hex[:16]
    record.update(
        payment_id=payment_id, verified=True, signature_valid=True,
        status="SUCCESS", captured="auto", verified_at=time.time(),
    )
    _store().set("payment_transactions", order_id, {k: v for k, v in record.items() if k != "_id"})
    receipt = "RCPT-" + order_id.split("_")[-1][:10].upper()
    log.info("[payments] test-capture order=%s -> %s", order_id, payment_id)
    return {
        "verified": True, "status": "SUCCESS", "order_id": order_id,
        "payment_id": payment_id, "receipt": receipt, "amount": record.get("amount", 0),
    }


def handle_webhook(raw_body: bytes, signature: str) -> dict:
    """Razorpay -> /payments/webhook. Verify signature, update the order."""
    if WEBHOOK_SECRET:
        expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            log.warning("[payments] webhook signature mismatch - ignored")
            return {"ok": False, "reason": "bad signature"}

    import json

    try:
        event = json.loads(raw_body.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"ok": False, "reason": "bad body"}

    entity = (
        event.get("payload", {}).get("payment", {}).get("entity", {})
        or event.get("payload", {}).get("order", {}).get("entity", {})
    )
    order_id = entity.get("order_id") or entity.get("id")
    if not order_id:
        return {"ok": True, "note": "no order id in event"}

    row = _store().query("payment_transactions", {"order_id": order_id})
    if row:
        rec = {k: v for k, v in row[0].items() if k != "_id"}
        rec["webhook_event"] = event.get("event")
        rec["webhook_at"] = time.time()
        if event.get("event", "").startswith("payment.captured"):
            rec["status"] = "SUCCESS"
            rec["verified"] = True
        elif event.get("event", "").startswith("payment.failed"):
            rec["status"] = "FAILED"
        _store().set("payment_transactions", order_id, rec)
    log.info("[payments] webhook %s for order %s", event.get("event"), order_id)
    return {"ok": True, "event": event.get("event")}


def get_transaction(order_id: str) -> dict | None:
    row = _store().query("payment_transactions", {"order_id": order_id})
    return {k: v for k, v in row[0].items() if k != "_id"} if row else None
