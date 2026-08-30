# REACH Backend — Phase 2

`goal + page context` → **Gemini 3.5 Flash** → one structured browser action.

No ADK / Firestore / RAG / vision yet — those are Phase 3+.

## Files

| File | Role |
| --- | --- |
| `models.py` | `AgentRequest` / `AgentResponse` contract |
| `gemini.py` | Vertex AI call (`gemini-3.5-flash`, `asia-south1`), page summariser, safety normalisation |
| `main.py` | FastAPI: `GET /health`, `POST /agent` |
| `test_agent.py` | manual local test against a running server |
| `Dockerfile` / `.dockerignore` | Cloud Run container |
| `deploy.ps1` | build + deploy to Cloud Run (run only after local works) |

## Run locally

```powershell
cd K:\projects\reach\backend
..\.venv\Scripts\Activate.ps1
$env:GOOGLE_CLOUD_PROJECT = "reach-agent-507107"
python -m uvicorn main:app --reload --port 8080
```

(Use `python -m uvicorn`, not the bare `uvicorn` shim — the `.exe` shim on this
machine is pinned to a different interpreter.)

Auth uses your existing `gcloud` Application Default Credentials.

## Test

```powershell
# health
curl http://127.0.0.1:8080/health

# agent (in another shell, server running)
python test_agent.py
```

Verified live responses:

| Goal | Response |
| --- | --- |
| Open my electricity bill | `click #view-bill` (1.0) |
| Enter my email demo@example.com | `type #email` = `demo@example.com` (1.0) |
| Set the language to Kannada | `select #language` = `kannada` (1.0) |
| Buy me a plane ticket to Paris | `none` (0.0) |

## Safety normalisation (in `gemini.py`)

- `action` forced into the allowed set, else `none`
- `confidence` clamped to `0..1`
- element actions (`click`/`type`/`select`) with **no target** → `none`
- target **not present** in the page summary → `none` (refuses invented elements)

The extension additionally gates on `confidence >= 0.80` before auto-running.

## Deploy (later)

```powershell
.\deploy.ps1   # gcloud run deploy --source . --region asia-south1 --min-instances 0
```

## Note

The `vertexai.generative_models` SDK is deprecated (support ends 2026-06-24). It
is used deliberately here because it is the config already proven in
`test_gemini.py`. Migrating to `google-genai` is a later cleanup.
