"""REACH backend (Phase 2): FastAPI + Gemini 3.5 Flash.

    POST /agent   goal + page context  ->  one structured browser action
    GET  /health  liveness probe for Cloud Run
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from gemini import ask_gemini
from models import AgentRequest, AgentResponse

app = FastAPI(title="REACH", version="0.2.0")

# The extension calls this from a chrome-extension:// origin (and file:// pages).
# Wide-open CORS is fine for local dev; tighten for production later.
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
    return {"service": "REACH", "version": app.version, "endpoints": ["/health", "/agent"]}


@app.post("/agent", response_model=AgentResponse)
def agent(request: AgentRequest) -> AgentResponse:
    try:
        return ask_gemini(
            goal=request.goal,
            url=request.url,
            dom=request.dom,
            screenshot=request.screenshot,
        )
    except RuntimeError as exc:  # e.g. GOOGLE_CLOUD_PROJECT not set
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface the real error during dev
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
