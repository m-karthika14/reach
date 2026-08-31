r"""REACH Gemma fast-filter test suite (Phase 14).

Gemma is REACH's SECOND Google model: a fast relevance filter that pre-screens
on-page candidates so the Gemini reasoning agents work over a short ranked
shortlist. These checks prove Gemma is actually invoked over Vertex AI (ADC, no
API key), that its output can never inject an invented selector, and that every
failure path falls back to "keep every candidate" so the pipeline is never worse
off than before Gemma existed.

Run:
    cd backend
    ..\.venv\Scripts\Activate.ps1
    $env:GOOGLE_CLOUD_PROJECT = "reach-agent-507107"
    $env:REACH_SESSION_BACKEND = "memory"
    python test_gemma.py

Live model calls make this ~1-3 min. Exits non-zero on any FAIL.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

os.environ.setdefault("REACH_SESSION_BACKEND", "memory")
os.environ.setdefault("GEMMA_ENABLED", "1")

from agents.gemma_classifier import GemmaClassifier, filter_candidates  # noqa: E402

_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        _fails.append(name)


def run(coro):
    return asyncio.run(coro)


NAV = [
    {"selector": "#view-bill", "name": "View Bill", "role": "button", "text": "View Bill"},
    {"selector": "#pay-button", "name": "Pay Bill", "role": "button", "text": "Pay Bill"},
    {"selector": "#nav-home", "name": "Home", "role": "button", "text": "Home"},
    {"selector": "#nav-help", "name": "Help", "role": "button", "text": "Help"},
    {"selector": "#nav-logout", "name": "Log out", "role": "button", "text": "Log out"},
    {"selector": "#nav-profile", "name": "Profile", "role": "button", "text": "Profile"},
    {"selector": "#nav-settings", "name": "Settings", "role": "button", "text": "Settings"},
    {"selector": "#lang-en", "name": "English", "role": "button", "text": "English"},
]


def suite() -> None:
    print("\n== 1. classifier returns a well-formed result (live) ==")
    res = run(filter_candidates("pay my electricity bill", NAV, page_context="file:///d"))
    check("result has model + kept", bool(res.model) and isinstance(res.kept, list), str(res.summary()))
    check("candidates_in counted", res.candidates_in == len(NAV), str(res.candidates_in))
    print(f"       used={res.used} kept={res.kept} latency={res.latency_ms}ms fallback={res.fallback_reason}")

    print("\n== 2. Gemma actually ran and kept the pay element (live) ==")
    check("used == True (real Gemma call)", res.used is True, res.fallback_reason or "")
    check("pay element kept", "#pay-button" in res.kept, str(res.kept))
    check("every kept selector is real", set(res.kept).issubset({c["selector"] for c in NAV}), str(res.kept))

    print("\n== 3. large list is narrowed (live) ==")
    check("candidates_out < candidates_in", res.candidates_out < res.candidates_in,
          f"{res.candidates_out} < {res.candidates_in}")
    check("noise dropped (logout / language)",
          "#nav-logout" not in res.kept and "#lang-en" not in res.kept, str(res.kept))

    print("\n== 4. invented selector can never pass through ==")
    c = GemmaClassifier()
    c._call = lambda *a, **k: '[{"selector": "#ghost-button", "score": 1.0, "reason": "x"}]'
    r = run(c.classify_candidates("do a thing", NAV))
    check("no invented selector in kept", "#ghost-button" not in r.kept, str(r.kept))
    check("falls back to all candidates", r.used is False and len(r.kept) == len(NAV), str(r.summary()))

    print("\n== 5. echoed candidate line is salvaged to the real selector ==")
    c = GemmaClassifier()
    c._call = lambda *a, **k: json.dumps([
        {"selector": "#view-bill | role=button | label='View Bill'", "score": 0.9, "reason": "x"},
        {"selector": "#pay-button", "score": 0.8, "reason": "y"},
        {"selector": "#nav-profile", "score": 0.5, "reason": "z"},
    ])
    r = run(c.classify_candidates("open my bill", NAV))
    check("salvaged #view-bill", "#view-bill" in r.kept and r.used is True, str(r.kept))

    print("\n== 6. malformed JSON -> graceful fallback ==")
    c = GemmaClassifier()
    c._call = lambda *a, **k: "sorry, I cannot help with that"
    r = run(c.classify_candidates("open my bill", NAV))
    check("used == False", r.used is False)
    check("kept == all candidates", len(r.kept) == len(NAV))
    check("fallback_reason recorded", bool(r.fallback_reason), str(r.fallback_reason))

    print("\n== 7. slow model -> timeout fallback (no hang) ==")
    c = GemmaClassifier()
    c.timeout_s = 0.3

    def _slow(*a, **k):
        time.sleep(1.0)  # the classify call must abandon this well before it returns
        return "[]"

    c._call = _slow
    t0 = time.time()
    r = run(c.classify_candidates("open my bill", NAV))
    elapsed = time.time() - t0
    check("timeout fallback (no invented data, all kept)",
          r.used is False and "timeout" in (r.fallback_reason or "") and len(r.kept) == len(NAV),
          str(r.fallback_reason))
    check("did not hang", elapsed < 2.5, f"{elapsed:.2f}s")

    print("\n== 8. GEMMA_ENABLED=0 -> total bypass, no model call ==")
    os.environ["GEMMA_ENABLED"] = "0"
    c = GemmaClassifier()
    c._call = lambda *a, **k: (_ for _ in ()).throw(AssertionError("model must not be called when disabled"))
    r = run(c.classify_candidates("open my bill", NAV))
    check("used == False, all kept", r.used is False and len(r.kept) == len(NAV))
    check("reason mentions disabled", "disabled" in (r.fallback_reason or ""), str(r.fallback_reason))
    os.environ["GEMMA_ENABLED"] = "1"

    print("\n== 9. tiny candidate list is skipped (nothing to gain) ==")
    c = GemmaClassifier()
    c._call = lambda *a, **k: (_ for _ in ()).throw(AssertionError("model must not be called for a tiny list"))
    r = run(c.classify_candidates("open my bill", NAV[:3]))
    check("used == False for 3 candidates", r.used is False and len(r.kept) == 3, str(r.summary()))

    print("\n== 10. Structure-relevant selectors are a floor Gemma cannot veto ==")
    c = GemmaClassifier()
    c._call = lambda *a, **k: json.dumps([
        {"selector": "#nav-profile", "score": 0.9, "reason": "x"},
        {"selector": "#nav-settings", "score": 0.8, "reason": "y"},
    ])
    r = run(c.classify_candidates("open my bill", NAV, floor={"#view-bill"}))
    check("floored #view-bill survives", "#view-bill" in r.kept, str(r.kept))

    print("\n== 11. /debug/gemma endpoint is read-only ==")
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    dom = json.dumps({"title": "Demo", "url": "file:///d", "visibleText": "View Bill Pay Bill",
                      "buttons": [{"text": x["name"], "accessibleName": x["name"],
                                   "id": x["selector"][1:], "selector": x["selector"]} for x in NAV]})
    body = client.post("/debug/gemma", json={"goal": "pay my electricity bill", "dom": dom, "url": "file:///d"}).json()
    check("returns judgements", isinstance(body.get("judgements"), list), str(body)[:200])
    check("no browser action in response", "action" not in body and "target" not in body, str(body.keys()))
    check("kept selectors are all real",
          set(body.get("kept", [])).issubset({c["selector"] for c in NAV}), str(body.get("kept")))

    print("\n== 12. run_agent still picks the right element with Gemma on (live e2e) ==")
    from agents.root_agent import run_agent

    a = run(run_agent("open my electricity bill", "file:///d", dom, screenshot=None))
    check("clicks #view-bill", a.action == "click" and a.target == "#view-bill", f"{a.action} {a.target}")
    check("gemma metric attached", isinstance(a.gemma, dict) and "used" in a.gemma, str(a.gemma))

    print("\n" + "=" * 48)
    if _fails:
        print(f"RESULT: {len(_fails)} FAILED -> " + ", ".join(_fails))
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    suite()
