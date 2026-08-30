r"""REACH end-to-end reproducible test suite.

Exercises every backend capability against a real Gemini 3.5 Flash (Vertex AI)
and an isolated in-memory store. No running server needed (FastAPI TestClient).

Run:
    cd backend
    ..\.venv\Scripts\Activate.ps1
    $env:GOOGLE_CLOUD_PROJECT = "reach-agent-507107"
    $env:REACH_SESSION_BACKEND = "memory"        # isolate from prod Firestore
    python test_e2e.py

Expect ~4-8 minutes (many live model calls). Each check prints PASS / FAIL and
the script exits non-zero if any FAIL.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

os.environ.setdefault("REACH_SESSION_BACKEND", "memory")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

C = TestClient(main.app)
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        _fails.append(name)


def dom(buttons, text="", title="Demo", url="file:///demo/index.html"):
    return json.dumps({
        "title": title, "url": url, "visibleText": text,
        "buttons": [{"text": b.get("t", ""), "accessibleName": b.get("a", b.get("t", "")),
                     "id": b["id"], "selector": "#" + b["id"]} for b in buttons],
    })


CLEAR = dom(
    [{"id": "view-bill", "t": "View Bill"}, {"id": "pay-button", "t": "Pay Bill"}],
    "Electricity Account  Bill 1,240  View Bill  Pay Bill",
)
BILL_OPEN = dom(
    [{"id": "download-bill", "t": "Download PDF"}],
    "Electricity Bill  Account 4471-2290  Amount due 1,240.00  Due date 15 Sep 2026  Status Unpaid",
    title="Electricity Bill",
)
ICONS = dom(
    [{"id": "icon-home", "t": "\U0001F3E0", "a": "button"},
     {"id": "icon-pay", "t": "\U0001F4B3", "a": "button"},
     {"id": "icon-user", "t": "\U0001F464", "a": "button"}],
    "Account",
)
PAY_OK = dom([], "Payment successful. Razorpay Payment ID pay_TEST123 Order ID order_TEST Receipt RCPT-1 Status Paid",
             title="Payment successful")
PAY_PROCESSING = dom([], "Processing payment...", title="Payment")


def main_suite() -> None:
    print("\n== 1. service health ==")
    r = C.get("/health").json()
    check("/health ok", r.get("status") == "ok")
    root = C.get("/").json()
    check("/ reports framework", root.get("framework") == "google-adk", str(root.get("framework")))
    print(f"       payments_mode={root.get('payments_mode')}  session_backend={root.get('session_backend')}")

    print("\n== 2. /agent — structure path (clear DOM, Vision skipped) ==")
    a = C.post("/agent", json={"goal": "open my electricity bill", "url": "file:///d",
                               "dom": CLEAR, "screenshot": None}).json()
    check("clicks #view-bill", a.get("action") == "click" and a.get("target") == "#view-bill", str(a))
    check("vision NOT used", a.get("vision_used") is False)

    print("\n== 3. /agent — invented-selector refusal ==")
    a = C.post("/agent", json={"goal": "click #ghost-button", "url": "file:///d",
                               "dom": CLEAR, "screenshot": None}).json()
    check("refuses (action=none)", a.get("action") == "none", str(a))

    print("\n== 4. /agent — impossible goal ==")
    a = C.post("/agent", json={"goal": "book a flight to Paris", "url": "file:///d",
                               "dom": CLEAR, "screenshot": None}).json()
    check("blocked (action=none)", a.get("action") == "none", str(a))

    print("\n== 5. /verify — VERIFIED vs AMBIGUOUS ==")
    v = C.post("/verify", json={"goal": "open my electricity bill", "action": {"action": "click", "target": "#view-bill"},
                                "before_dom": CLEAR, "after_dom": BILL_OPEN, "after_url": "file:///d/bill"}).json()
    check("bill open -> VERIFIED", v.get("status") == "VERIFIED" and v.get("success") is True, str(v.get("status")))
    v = C.post("/verify", json={"goal": "pay my electricity bill", "action": {"action": "click", "target": "#pay"},
                                "before_dom": CLEAR, "after_dom": PAY_PROCESSING, "after_url": "file:///d/pay"}).json()
    check("processing -> AMBIGUOUS", v.get("status") == "AMBIGUOUS", str(v.get("status")))
    check("AMBIGUOUS -> no success", v.get("success") is False)
    check("AMBIGUOUS -> retry blocked", v.get("retry_allowed") is False)

    print("\n== 6. /agent/loop — one reasoning step ==")
    s = C.post("/agent/loop", json={"goal": "open my electricity bill", "url": "file:///d", "dom": CLEAR,
                                    "history": [], "prev_dom": None, "last_action": None, "max_steps": 8}).json()
    check("loop step runs", s.get("status") == "running" and s.get("target") == "#view-bill", str(s.get("status")))

    print("\n== 7. /chat — stateful dialogue + pronoun ==")
    sid = None
    r1 = C.post("/chat", json={"session_id": sid, "user_id": "e2e", "message": "open my electricity bill",
                               "url": "file:///d", "dom": CLEAR, "screenshot": None}).json()
    sid = r1["session_id"]
    check("T1 -> click #view-bill", r1.get("action", {}).get("target") == "#view-bill", str(r1.get("action")))
    r2 = C.post("/chat", json={"session_id": sid, "user_id": "e2e", "message": "actually download it instead",
                               "url": "file:///d", "dom": BILL_OPEN, "screenshot": None}).json()
    check("T2 correction understood", (r2.get("action") or {}).get("target") == "#download-bill"
          or "download" in (r2.get("message", "").lower()), str(r2.get("action")))

    print("\n== 8. /chat — consequential action asks for confirmation ==")
    r = C.post("/chat", json={"session_id": None, "user_id": "e2e", "message": "pay my electricity bill",
                              "url": "file:///d", "dom": CLEAR, "screenshot": None}).json()
    check("needs confirmation", r.get("status") == "waiting_confirmation" and r.get("requires_confirmation"), str(r.get("status")))

    print("\n== 9. memory — learn on VERIFIED, current page wins ==")
    import memory as M
    dom_url = f"file:///reach-e2e-{uuid.uuid4().hex[:6]}/bill.html"
    M.writer().apply_verification_outcome(session_id="e2e", goal="open bill", url=dom_url,
                                          action={"action": "click", "target": "#view-bill"},
                                          verification={"status": "VERIFIED", "success": True}, element_label="bill")
    mem = M.retriever().retrieve(dom_url, "open bill")
    check("page memory learned", any(p["selector"] == "#view-bill" for p in mem["page_memory"]), str(mem["page_memory"]))
    M.writer().apply_verification_outcome(session_id="e2e", goal="open bill", url=dom_url,
                                          action={"action": "click", "target": "#gone"},
                                          verification={"status": "VERIFIED", "success": True})
    import asyncio

    from agents.root_agent import run_agent
    resp = asyncio.run(
        run_agent("open bill", dom_url, dom([{"id": "view-bill", "t": "View Bill"}], "View Bill"), screenshot=None))
    check("stale memory ignored (page wins)", resp.target == "#view-bill", str(resp.target))

    print("\n== 10. correction learning — persists across sessions ==")
    curl = f"file:///reach-e2e-{uuid.uuid4().hex[:6]}/dash.html"
    M.writer().record_correction(url=curl, selector="#icon-2", correct_label="payment",
                                 agent_prediction="account settings", user_said="no, that's payment", strength="strong")
    got = M.retriever().retrieve(curl, "pay", user_id="demo-user")
    check("correction retrievable", any(c["selector"] == "#icon-2" and "pay" in c["correct_label"].lower()
                                        for c in got["corrections"]), str(got["corrections"]))
    check("user-scoped", not M.retriever().retrieve(curl, "pay", user_id="someone-else")["corrections"])

    print("\n== 11. preferences — validate + persist ==")
    p = C.patch("/preferences", json={"user_id": "e2e-A", "verbosity": "detailed", "verbosity_bad": "x"}).json()
    check("valid applied", p["applied"].get("verbosity") == "detailed", str(p["applied"]))
    g = C.get("/preferences", params={"user_id": "e2e-A"}).json()
    check("preference persisted", g.get("verbosity") == "detailed")

    print("\n== 12. payments — real order (or mock) + capture ==")
    o = C.post("/payments/create-order", json={"amount": 1240, "consumer": "REACH-2026-001"}).json()
    check("order created", bool(o.get("order_id")), str(o.get("order_id")))
    print(f"       mode={'MOCK' if o.get('mock') else 'REAL (Razorpay order '+o['order_id']+')'}")
    cap = C.post("/payments/test-capture", json={"order_id": o["order_id"]}).json()
    check("capture -> SUCCESS", cap.get("status") == "SUCCESS" and cap.get("verified"), str(cap.get("status")))

    print("\n" + ("=" * 48))
    if _fails:
        print(f"RESULT: {len(_fails)} FAILED -> " + ", ".join(_fails))
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main_suite()
