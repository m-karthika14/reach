# REACH — Reliable Execution Agent for Accessible Computer Help

A voice-first browser agent that operates websites for people who can't — screen-reader
users, low-vision users, anyone who needs hands-free help. Say **"REACH, pay my
electricity bill"** and it perceives the page (DOM **and** vision), decides the next
action, **verifies** the outcome, refuses when it isn't sure, remembers what it
learned, and adapts to how *you* like to work.

Built on two Google models — **Gemini 3.5 Flash** for reasoning and **Gemma 4**
(`gemma-4-26b-a4b-it-maas`) as a fast candidate pre-filter — plus **Google ADK**
(multi-agent), **Cloud Run**, and **Firestore**. Both models are reached through
Vertex AI with Application Default Credentials (no API keys). Payments run through
**Razorpay Test Mode**.

---

## Architecture

```
                                  ┌─────────────────────────────────────────────┐
   ┌──────────────┐   voice / text │              CHROME EXTENSION               │
   │    USER      │◄──────────────►│  wake word "REACH" · Web Speech STT/TTS     │
   └──────────────┘   speech       │  content script: read DOM+ARIA, screenshot, │
                                   │  CLICK / TYPE / SELECT / SCROLL / BACK      │
                                   └───────────────┬─────────────────────────────┘
                                                   │  POST /chat  { session_id, user_id,
                                                   │                message, url, dom, screenshot }
                                                   ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────┐
   │                          CLOUD RUN  ·  FastAPI  (backend/main.py)                       │
   │                                                                                       │
   │   sessions/  ── multi-turn state (Firestore)      memory/  ── RAG (Firestore)          │
   │   loop/      ── autonomous step controller        policy.py ── risk + retry rules      │
   │                                                                                       │
   │                         agents/  ·  Google ADK  ·  Gemini 3.5 Flash                    │
   │                                                                                       │
   │   MEMORY RETRIEVAL (page + corrections + user prefs)                                   │
   │        │                                                                              │
   │        ▼                                                                              │
   │   DIALOGUE AGENT ─ resolve "it" / ordinals / "actually…" / stop / yes / preferences   │
   │        │                                                                              │
   │        ▼                                                                              │
   │   STRUCTURE AGENT (DOM/ARIA) [Gemini] ─ every on-page button/link → candidate list    │
   │        │                                                                              │
   │        ▼                                                                              │
   │   GEMMA FAST-FILTER [Gemma 4 · Vertex MaaS] ─ score + rank candidates for the goal    │
   │        │  focused shortlist  (Structure's picks are a floor; fail-open = keep all)    │
   │        ▼                                                                              │
   │   STRUCTURE confidence≥0.85 & !needs_vision ───────────────────────►  ACTION AGENT    │
   │        │ low / icon-only                                              ▲   [Gemini]    │
   │        ▼                                                              │                │
   │   VISION AGENT (screenshot) [Gemini] ──► RECONCILIATION ──AGREE─────►─┘                │
   │                                     │ CONFLICT / UNKNOWN                               │
   │                                     ▼                                                 │
   │                              deterministic gate  →  action = none  ("I won't act")    │
   │                                                                                       │
   │   ACTION  →  gemini._normalize (no invented selector, confidence)                      │
   │          →  correction-aware ranking  →  risk gate (consequential → confirm)           │
   │                                                                                       │
   │   VERIFICATION AGENT  (after the extension re-inspects)                                │
   │      goal + before + after + evidence  →  VERIFIED / FAILED / AMBIGUOUS                │
   │      AMBIGUOUS → success=false, retry blocked  ·  VERIFIED → learn to memory           │
   │                                                                                       │
   │   /payments/*  ── Razorpay Test Mode order + capture  →  payment_transactions          │
   └───────────────────────────────────────────────────────────────────────────────────────┘
                                                   │
                                                   ▼
                              ┌────────────────────────────────────────┐
                              │  FIRESTORE  (database "reach-memory")   │
                              │  sessions · page_memory ·              │
                              │  correction_memory · preference_memory │
                              │  task_history · payment_transactions   │
                              └────────────────────────────────────────┘

   DEMO PORTAL (demo-site/, any static host) — "REACH Energy" electricity portal with
   deliberately inaccessible icons + a Structure/Vision conflict button, talks to the
   backend for payments.
```

**One request, end to end:**
`observe → retrieve memory → interpret → structure → gemma fast-filter → (vision) →
reconcile → decide → safety gate → execute → observe again → verify → learn →
speak the result`

### Two models, on purpose

| Model | Role | Why |
| --- | --- | --- |
| **Gemini 3.5 Flash** | all reasoning agents (dialogue, structure, vision, reconciliation, action, verification) | multimodal, strong instruction-following, final authority on every decision |
| **Gemma 4** (`gemma-4-26b-a4b-it-maas`, Vertex AI MaaS, `global` endpoint) | fast relevance filter between candidate generation and the Gemini reasoning path | a small open model is enough to say *"of these 30 buttons, these 4 relate to the goal"*; Gemini then reasons over a short list instead of the whole page |

Gemma **never acts** — no clicks, types, navigation or payments. It only scores
candidates. It cannot veto an element the Structure Agent already flagged
(that set is a floor), a Gemma-named selector that isn't a real on-page element
is dropped before it reaches anything, and **any** Gemma failure (timeout, bad
JSON, model/credential error) falls back to "keep every candidate" — the
pipeline is never worse off than before Gemma existed. Toggle with
`GEMMA_ENABLED=0`; inspect it in isolation via `POST /debug/gemma`.

---

## Repo layout

```
reach/
├── backend/                 FastAPI + ADK agents + memory + payments  (deploys to Cloud Run)
│   ├── main.py              HTTP boundary only
│   ├── agents/              Google ADK: dialogue, structure, vision, reconciliation, action,
│   │                        verification, styler; root_agent orchestrates + logs
│   │   └── gemma_classifier.py  Gemma 4 fast candidate filter (Vertex MaaS, fail-open)
│   ├── loop/                Phase 4 autonomous step controller
│   ├── sessions/            Firestore-backed multi-turn state + /chat turn
│   ├── memory/              RAG: page_memory, correction_memory, preference_memory, task_history
│   ├── policy.py            risk classification + deterministic retry policy
│   ├── payments.py          Razorpay Test Mode (orders, verify, webhook)  — secrets from env
│   ├── gemini.py            page summariser + safety normaliser (no invented selectors)
│   ├── deploy.ps1           one-command Cloud Run deploy (IAM + env vars)
│   ├── test_e2e.py          reproducible end-to-end suite (13 checks)
│   ├── test_gemma.py        Gemma fast-filter suite (invoked, never invents, fail-open)
│   └── test_gemini.py / test_firestore.py / test_agent.py
├── extension/               Chrome MV3 extension  (loaded unpacked, runs in the browser)
│   ├── manifest.json
│   ├── background/          Alt+R command → open popup
│   ├── content/             DOM extraction + action engine
│   ├── popup/               voice ("REACH" wake word) + conversation UI
│   └── permission/          one-time microphone grant page
└── demo-site/               "REACH Energy" portal (static): index / bill / payment / success
    └── *-test.html          controlled scenario pages (conflict / ambiguous / failure / …)
```

---

## Prerequisites

| Need | Notes |
| --- | --- |
| Python 3.12 + the repo venv | `python -m venv .venv` at repo root, then `pip install -r backend/requirements.txt` |
| Google Cloud project | `reach-agent-507107` (or your own) with billing on |
| gcloud CLI | authenticated: `gcloud auth login` **and** `gcloud auth application-default login` |
| Vertex AI | enabled; runtime identity has `roles/aiplatform.user` — covers **both** Gemini 3.5 Flash (`asia-south1`) and Gemma 4 MaaS (`global` endpoint). No API key. |
| Firestore | a database named **`reach-memory`** (Native mode); identity has `roles/datastore.user` |
| Chrome | for the extension (Web Speech API for voice) |
| Razorpay **test** keys | optional — without them payments run in clearly-labelled MOCK mode |

Create `backend/.env` (gitignored) from the template:

```
GOOGLE_CLOUD_PROJECT=reach-agent-507107
GOOGLE_CLOUD_LOCATION=asia-south1
RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxxxxx
```

**Gemma fast-filter** needs no secret. It defaults to `gemma-4-26b-a4b-it-maas`
on the Vertex `global` endpoint using the same ADC / service-account credentials
as Gemini. Optional non-secret overrides (set in the shell, `.env`, or
`deploy.ps1`'s `--set-env-vars`):

| Var | Default | Meaning |
| --- | --- | --- |
| `GEMMA_ENABLED` | `1` | `0` bypasses Gemma entirely (Structure → Gemini only) |
| `GEMMA_MODEL` | `gemma-4-26b-a4b-it-maas` | any Gemma model your project can reach on Vertex |
| `GEMMA_LOCATION` | `global` | region for the Gemma call (MaaS Gemma is global-only) |
| `GEMMA_TIMEOUT_S` | `10` | fall back to "keep all candidates" if Gemma is slower |
| `GEMMA_MIN_CANDIDATES` | `6` | skip the filter when the page has fewer elements than this |

---

## Run it locally

### 0 — One-time setup
```powershell
git clone <this-repo> K:\projects\reach
cd K:\projects\reach
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

# Google Cloud auth (needed for Vertex AI + Firestore)
gcloud auth login
gcloud auth application-default login
gcloud config set project reach-agent-507107

# create the Firestore database (once per project)
gcloud firestore databases create --database=reach-memory --location=asia-south1 --type=firestore-native

# secrets
copy backend\.env.example backend\.env      # then edit backend\.env (see template above)
```

Then run the three pieces below (three terminals).

### 1 — Backend
```powershell
cd K:\projects\reach\backend
..\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --port 8080
```
`main.py` auto-loads `backend/.env`. Startup log should show
`[payments] Razorpay REAL mode …` and `[sessions] using Firestore store`.

```powershell
Invoke-RestMethod http://127.0.0.1:8080/
#  framework: google-adk   payments_mode: real   session_backend: firestore
```

### 2 — Demo portal (must be http, not file://)
```powershell
cd K:\projects\reach\demo-site
K:\projects\reach\.venv\Scripts\python.exe -m http.server 5500
```
Open `http://localhost:5500/index.html`. In the **Settings ▸ Backend** field
(bottom of the page) set `http://127.0.0.1:8080` — the badge should read
**Razorpay: LIVE (test)**.

### 3 — Chrome extension
1. `chrome://extensions` → **Developer mode** on → **Load unpacked** → `K:\projects\reach\extension`
   (or click ↻ on the card after any code change).
2. Open the popup → **Settings ▸ backend** = `http://127.0.0.1:8080`.
3. Voice panel → **mic setup** link → **Allow microphone** (one time, in the tab that opens).
4. Say **"REACH"** → *"Yes?"* → give a command. Or type in the Conversation box.

---

## Run it in the cloud

```powershell
$env:Path += ";K:\g-cli\google-cloud-sdk\bin"
cd K:\projects\reach\backend
.\deploy.ps1
```
`deploy.ps1` enables the APIs, grants the Cloud Run runtime SA
`roles/aiplatform.user` + `roles/datastore.user`, reads `RAZORPAY_*` from
`backend/.env` into `--set-env-vars`, and builds + deploys from source.

```powershell
$URL = gcloud run services describe reach-backend --region asia-south1 --format "value(status.url)"
Invoke-RestMethod "$URL/"        # payments_mode: real   session_backend: firestore
```

Then point the extension **Settings ▸ backend** and the demo-portal **Backend**
field at `$URL`. The demo portal can stay local (`http.server`) or be hosted
(Firebase Hosting: `npx firebase-tools init hosting` with public dir `.`, then
`npx firebase-tools deploy --only hosting`). CORS on the backend is `*`.

Redeploy anytime with `.\deploy.ps1` (same URL). Cold start on `--min-instances 0`
is ~5–15 s; add `--min-instances 1` to keep it warm.

---

## Reproducible testing

### A. Automated end-to-end suite

```powershell
cd K:\projects\reach\backend
..\.venv\Scripts\Activate.ps1
$env:GOOGLE_CLOUD_PROJECT   = "reach-agent-507107"
$env:REACH_SESSION_BACKEND  = "memory"     # isolate from prod Firestore
python test_e2e.py
```

Runs against **real Gemini 3.5 Flash** via FastAPI's TestClient (no server
needed). ~4–8 minutes. Prints `PASS` / `FAIL` per check; exits non-zero on any
failure. Covers:

| # | Check | Expected |
| --- | --- | --- |
| 1 | `/health`, `/` | ok · `framework: google-adk` |
| 2 | `/agent` structure path | `click #view-bill`, **Vision not used** |
| 3 | invented selector `#ghost-button` | `action: none` (refused) |
| 4 | impossible goal ("book a flight") | `action: none` (blocked) |
| 5 | `/verify` | bill open → **VERIFIED**; "Processing…" → **AMBIGUOUS**, `success=false`, `retry_allowed=false` |
| 6 | `/agent/loop` | one `running` step → `#view-bill` |
| 7 | `/chat` multi-turn | T1 clicks bill; T2 "actually download it" → correction understood |
| 8 | `/chat` "pay my electricity bill" | `waiting_confirmation` (consequential → asks first) |
| 9 | memory | VERIFIED writes `page_memory`; **stale selector ignored, live page wins** |
| 10 | correction learning | `record_correction` retrievable in a **new** session; **user-scoped** |
| 11 | `/preferences` | invalid value rejected; valid value persists |
| 12 | `/payments/*` | real Razorpay order created (or MOCK) → capture → `SUCCESS` |
| 13 | **Gemma fast-filter** | `/debug/gemma` shortlist ⊆ real on-page selectors & narrower than input; `/agent` still clicks `#view-bill` with Gemma on; `/` advertises both models |

### B. Individual smoke tests

```powershell
python test_gemini.py       # Vertex AI + gemini-3.5-flash reachable
python test_gemma.py        # Gemma 4 invoked over Vertex (ADC); never invents a selector; fail-open
python test_firestore.py    # Firestore "reach-memory" writable
# with the server running on :8080:
python test_agent.py        # POST /agent with sample goals
```

`test_gemma.py` (12 checks, ~1–3 min): Gemma actually runs and narrows a
noisy nav bar to the goal-relevant elements; an invented / echoed selector is
rejected or salvaged, never passed on; malformed JSON, a timeout, `GEMMA_ENABLED=0`
and a tiny candidate list each fall back to "keep everything"; Structure-relevant
selectors survive the filter; `/debug/gemma` is read-only; `run_agent` end-to-end
still picks the right element.

### C. Manual demo scenarios (deterministic)

Open `http://localhost:5500/payment.html`; the **Demo controls** panel (top-right)
switches which elements the page exposes to REACH:

| Scenario | What REACH does |
| --- | --- |
| `normal` | Structure confident → click → real Razorpay order + capture → **VERIFIED**, speaks the receipt |
| `vision` | icon-only `💳` `aria-label="button"` → Structure unsure → **Vision** → AGREE → click |
| `conflict` | button says "Pay Now" but `aria-label="Cancel"` → **CONFLICT → blocked**, REACH refuses aloud |
| `ambiguous` | payment stalls, no receipt → verification **AMBIGUOUS → no retry, no false success** |

Also: [demo-site/conflict-test.html](demo-site/conflict-test.html),
[ambiguous-test.html](demo-site/ambiguous-test.html),
[failure-test.html](demo-site/failure-test.html),
[payment-test.html](demo-site/payment-test.html) for isolated repros.

### D. Memory / correction / personalization by hand

```
New chat →  "open my electricity bill"          (learns #view-bill on VERIFIED)
New chat →  "open my bill"                       (memory panel shows the learned element; Vision skipped)
            "no, the credit-card icon is payment" (correction persisted to Firestore)
New chat →  "where do I pay?"                    (retrieved correction re-ranks the candidate)
Settings →  Style = concise  vs  detailed  with user id A vs B  (same goal, different spoken reply)
```

---

## HTTP API

| Endpoint | Purpose |
| --- | --- |
| `GET /health`, `GET /` | liveness; `/` reports `framework`, `payments_mode`, `session_backend`, `models` (Gemini + Gemma) |
| `POST /debug/gemma` | `{goal, dom, url}` → Gemma's candidate scores + shortlist. Read-only, runs no action. |
| `POST /chat` | **primary** — one stateful conversational turn (voice + text) |
| `POST /agent` | single-shot: goal + page → one action |
| `POST /agent/loop` | one step of the autonomous observe→reason→act loop |
| `POST /verify` | goal + before/action/after → `VERIFIED / FAILED / AMBIGUOUS` + evidence |
| `GET/PATCH /preferences` | per-user profile (verbosity, language, confirmation, navigation) |
| `GET /memory` | what REACH has learned about a site (for the extension panel) |
| `POST /sessions`, `GET /sessions/{id}` | session lifecycle / inspection |
| `POST /payments/create-order`, `/payments/verify`, `/payments/test-capture`, `/payments/webhook` | Razorpay Test Mode |

Per-area detail: [backend/README.md](backend/README.md) ·
[backend/memory/README.md](backend/memory/README.md) ·
[extension/README.md](extension/README.md) ·
[demo-site/README.md](demo-site/README.md).

---



## Google technology used

| Requirement | REACH |
| --- | --- |
| Gemini 3.5+ | `gemini-3.5-flash` on Vertex AI (every reasoning agent) |
| Gemma | `gemma-4-26b-a4b-it-maas` on Vertex AI (MaaS, `global`) — fast candidate pre-filter feeding the Gemini path; ADC auth, no API key |
| Google agent framework | **Google ADK** — 7 `LlmAgent`s + `Runner` + session state, orchestrated by `root_agent` |
| Google Cloud infrastructure | **Cloud Run** (FastAPI), **Firestore** (`reach-memory`), Cloud Build, Vertex AI |
| Browser interface | Chrome MV3 extension (voice + DOM + screenshot + action engine) |
