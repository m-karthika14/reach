"""REACH backend (Phase 3): FastAPI -> Google ADK agent team -> Gemini 3.5 Flash.

    POST /agent    goal + page context  ->  Root Agent [perception -> action]  ->  one action
    POST /verify    before + action + after  ->  Verification Agent  ->  {success, reason}
    GET  /health    liveness probe for Cloud Run

main.py is only the HTTP boundary. All reasoning/orchestration lives in agents/.
"""

import logging
from pathlib import Path

# Load backend/.env BEFORE importing modules that read env at import time
# (agents.config, payments). Shell env vars take precedence.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

import memory as _mem
import payments as _pay
from agents import (
    candidates_from_dom,
    gemma_filter_candidates,
    run_agent,
    run_verification,
)
from agents.gemma_classifier import gemma_classifier
from loop import run_loop_step
from models import (
    AgentRequest,
    AgentResponse,
    ChatRequest,
    ChatResponse,
    CreateOrderRequest,
    LoopStepRequest,
    LoopStepResponse,
    PreferencePatch,
    VerifyPaymentRequest,
    VerifyRequest,
    VerifyResponse,
)
from sessions import SessionManager, new_session_id, run_chat_turn

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="REACH", version="0.14.0")

_sessions = SessionManager()

# Extension calls this from a chrome-extension:// origin (and file:// pages).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "service": "REACH",
        "version": app.version,
        "framework": "google-adk",
        "session_backend": _sessions.backend_kind,
        "endpoints": ["/health", "/agent", "/agent/loop", "/verify", "/chat",
                      "/sessions", "/memory", "/preferences", "/payments/*", "/debug/gemma"],
        "payments_mode": "real" if _pay.REAL else "mock",
        "models": {
            "reasoning": "gemini-3.5-flash",
            "fast_filter": gemma_classifier.model if gemma_classifier.enabled else "(disabled)",
        },
    }


@app.post("/debug/gemma")
async def debug_gemma(body: dict):
    """Inspect the Gemma fast-filter in isolation - scores on-page candidates for
    a goal and returns the shortlist. Read-only: never executes a browser action."""
    goal = (body or {}).get("goal", "")
    dom = (body or {}).get("dom", "")
    url = (body or {}).get("url", "")
    if not goal or not dom:
        raise HTTPException(status_code=400, detail="goal and dom are required")
    candidates = candidates_from_dom(dom, limit=40)
    result = await gemma_filter_candidates(goal, candidates, page_context=url)
    return {
        "goal": goal,
        "on_page_selectors": [c["selector"] for c in candidates],
        **result.summary(),  # used, model, candidates_in (count), candidates_out, kept, ...
        "judgements": [j.model_dump() for j in result.judgements],
    }


# --------------------------------------------------------------------------- #
# Phase 13 - demo portal payments (Razorpay Test Mode). Secrets stay in env.
# --------------------------------------------------------------------------- #


@app.post("/payments/create-order")
async def create_order(req: CreateOrderRequest):
    try:
        return _pay.create_order(req.amount, req.consumer or "", req.note or "")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Razorpay: {exc}")


@app.post("/payments/verify")
async def verify_payment(req: VerifyPaymentRequest):
    return _pay.verify_payment(
        req.razorpay_order_id, req.razorpay_payment_id, req.razorpay_signature or ""
    )


@app.post("/payments/test-capture")
async def test_capture(body: dict):
    """Demo-only: finish a TEST order without the card UI (autonomous payment)."""
    key = _pay.PUBLIC_KEY_ID
    if not (key.startswith("rzp_test_") or key == "rzp_test_MOCK"):
        raise HTTPException(status_code=403, detail="test-capture requires a Razorpay test key")
    order_id = (body or {}).get("order_id", "")
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id required")
    return _pay.test_capture(order_id)


@app.post("/payments/webhook")
async def payments_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-razorpay-signature", "")
    return _pay.handle_webhook(raw, sig)


@app.get("/payments/transaction/{order_id}")
async def payment_transaction(order_id: str):
    tx = _pay.get_transaction(order_id)
    if not tx:
        raise HTTPException(status_code=404, detail="unknown order")
    return tx


@app.get("/memory")
async def memory(url: str = "", goal: str = ""):
    """Everything REACH has learned about the site at `url` (Phase 9 - for the UI panel)."""
    return _mem.retriever().retrieve(url, goal)


@app.get("/preferences")
async def get_preferences(user_id: str = "demo-user"):
    """The per-user preference profile (Phase 11)."""
    return _mem.preference_store().get(user_id).model_dump()


@app.patch("/preferences")
async def patch_preferences(patch: PreferencePatch):
    updates = {k: v for k, v in patch.model_dump().items()
               if k != "user_id" and v is not None}
    profile, applied = _mem.preference_store().patch(patch.user_id, updates)
    return {"profile": profile.model_dump(), "applied": applied}


@app.post("/agent", response_model=AgentResponse)
async def agent(request: AgentRequest) -> AgentResponse:
    try:
        return await run_agent(
            goal=request.goal,
            url=request.url,
            dom=request.dom,
            screenshot=request.screenshot,
        )
    except RuntimeError as exc:  # e.g. GOOGLE_CLOUD_PROJECT not set
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface the real error during dev
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/agent/loop", response_model=LoopStepResponse)
async def agent_loop(request: LoopStepRequest) -> LoopStepResponse:
    """One iteration of the browser action loop: verify -> reason -> gate."""
    try:
        return await run_loop_step(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/sessions")
async def create_session():
    """Explicitly start a conversation (Step 5.17). The extension may also just
    call /chat with session_id=null and use the id that comes back."""
    return {"session_id": new_session_id()}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    state = await _sessions.load(session_id)
    return state.model_dump()


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """One stateful conversational turn (Phase 5)."""
    try:
        return await run_chat_turn(_sessions, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest) -> VerifyResponse:
    try:
        result = await run_verification(
            goal=request.goal,
            before_dom=request.before_dom,
            action=request.action,
            after_dom=request.after_dom,
            after_url=request.after_url,
        )
        return VerifyResponse(
            status=result.get("status", "AMBIGUOUS"),
            success=bool(result.get("success", False)),
            reason=str(result.get("reason", "")),
            evidence=[str(e) for e in result.get("evidence", [])],
            retry_allowed=bool(result.get("retry_allowed", False)),
            risk_level=result.get("risk_level"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
