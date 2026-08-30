"""REACH backend (Phase 3): FastAPI -> Google ADK agent team -> Gemini 3.5 Flash.

    POST /agent    goal + page context  ->  Root Agent [perception -> action]  ->  one action
    POST /verify    before + action + after  ->  Verification Agent  ->  {success, reason}
    GET  /health    liveness probe for Cloud Run

main.py is only the HTTP boundary. All reasoning/orchestration lives in agents/.
"""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents import run_agent, run_verification
from loop import run_loop_step
from models import (
    AgentRequest,
    AgentResponse,
    ChatRequest,
    ChatResponse,
    LoopStepRequest,
    LoopStepResponse,
    VerifyRequest,
    VerifyResponse,
)
from sessions import SessionManager, new_session_id, run_chat_turn

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="REACH", version="0.5.0")

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
        "endpoints": ["/health", "/agent", "/agent/loop", "/verify", "/chat", "/sessions"],
    }


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
            success=bool(result.get("success", False)),
            reason=str(result.get("reason", "")),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
