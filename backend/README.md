# REACH Backend — Phase 8

FastAPI → **Google ADK agent team** → **Gemini 3.5 Flash** (Vertex AI, `asia-south1`),
persistent Firestore sessions, Structure + Vision + Reconciliation, and
**evidence-based verification** that refuses to claim success it can't prove.

`main.py` is only the HTTP boundary. Reasoning lives in `agents/`, the
browser-loop controller in `loop/`, session state in `sessions/`.

```
POST /chat         session_id + message + observation  ->  stateful turn  ->  reply + action
POST /sessions     ->  { session_id }                        (explicit start; /chat also auto-creates)
GET  /sessions/{id} ->  full stored SessionState
POST /agent        goal + page context      ->  Root Agent [ perception -> action ]  ->  one action
POST /agent/loop   goal + observation + history ->  verify -> reason -> safety gates  ->  next step
POST /verify       before + action + after   ->  Verification Agent                   ->  {success, reason}
GET  /health
```

## Phase 5 - stateful multi-turn dialogue

`sessions/` (Firestore db `reach-memory`, collection `sessions`):

| File | Role |
| --- | --- |
| `models.py` | `SessionState` - session_id, user_goal, current_task, current_step, current_page, previous_actions, current_candidates, pending_confirmation, verification_status, conversation_history, status |
| `firestore_store.py` | `FirestoreSessionStore` (real) + `InMemorySessionStore` fallback; `get_store()` tries Firestore once, downgrades with a log line if unreachable |
| `manager.py` | load / save / per-session `asyncio.Lock` / `reconcile_page` (fresh observation wins) / candidate extraction / history trim (keep 12 turns) |
| `conversation.py` | `run_chat_turn`: reconcile page → fold in last execution + verify it → **Dialogue Agent** interprets → command / correction / reference / continue → Root Agent reasons → risk gate → persist |

`agents/dialogue_agent.py` — `DialogueInterpretation { intent, command, resolved_goal, resolved_request, reply }`.
Resolves "it" / "that" / "the second one", corrections ("actually…"), and
commands (stop / continue / pause / yes / no) from the conversation history +
on-page candidates.

### Phase 6/7 - verified locally (live ADK + Vertex)

| Case | Route | Result |
| --- | --- | --- |
| "click View Bill", clear `<button>`, screenshot sent | structure only | `click #view-bill`; **vision + reconciliation skipped** (fast path) |
| "open the payment screen", 3 icon buttons `aria-label="button"` | structure → vision → **reconciliation AGREE** | `click #icon-pay` (ambiguous ≠ contradictory) |
| unlabeled buttons + vague goal + blank screenshot | structure → vision → **reconciliation UNKNOWN** | `[SAFETY] action blocked`; `action=none` |
| structural contradiction (text "Pay Now" / aria-label "Cancel") | structure → vision → **non-AGREE** | Action Agent **not reached**; `action=none`, message "I won't activate it" |
| Vision returns off-page selector | — | `_match_selector` rejects it |

`conflict-test.html` (aria-label "Cancel", pseudo-element renders "Pay Now") drives
a real **CONFLICT** in Chrome, where the screenshot actually shows "Pay Now".

### Phase 5 - verified locally (live ADK + Firestore)

| Scenario | Result |
| --- | --- |
| "Open my electricity bill" → "open it" → "actually show payment history" → "stop" → "continue" | goal remembered; "it"→bill; correction switches task; stop→`cancelled`; continue→resumes→`completed` |
| candidates on page → "click the second one" | resolves to `#payment-details` |
| "pay my electricity bill" → "yes" | `waiting_confirmation` → approves stored action → executes `#pay-button` |
| session A "open it" while session B exists | resolves to A's bill, not B's goal (isolated) |
| create session, **new `SessionManager`** (simulated restart), "open it" | goal + history reloaded from Firestore, "it" still resolves |

## Phase 4 - the browser action loop

The loop *iteration* runs in the **extension** (it owns Chrome). The backend
does one reasoning step per call:

```
POST /agent/loop
  1. if history >= max_steps            -> status = max_steps_reached
  2. if last_action + prev_dom present  -> Verification Agent(before -> after)
        success                          -> status = completed, done = true
  3. Root Agent (perception -> action) with the action history
  4. safety gates:
        action == none                    -> status = blocked
        (action,target) proposed a 3rd time (anywhere in history) -> status = repeated_action
        confidence < 0.85                 -> status = low_confidence
        consequential token in target     -> status = needs_confirmation (requires_confirmation)
        otherwise                         -> status = running  (extension executes, then loops)
```

`loop/state.py` status vocabulary · `loop/history.py` compact history + repeat
detection (total occurrences, not just consecutive; `scroll`/`back` exempt) ·
`loop/safety.py` consequential-action classifier (`pay`, `buy`, `delete`,
`transfer`, … as whole tokens of the target/value, never the goal) ·
`loop/controller.py` the step above.

The loop confidence bar (0.85) is deliberately stricter than the single-step
`/agent` gate (0.80): a confident agent returns ~0.95-1.0, so ~0.80 in a loop
means guessing - stop rather than wander.

Loop log (demo-ready):

```
reach.loop: [LOOP] Step 1  goal='Open my electricity bill and show the payment details'  (0 prior actions)
reach.loop: [REASON] action=click target=#view-bill confidence=1.00 done=False
reach.loop: [LOOP] Step 2  (1 prior actions)
reach.loop: [VERIFY] success=False reason=only the bill is shown, no payment history
reach.loop: [REASON] action=click target=#payment-details confidence=1.00
reach.loop: [LOOP] Step 3  (2 prior actions)
reach.loop: [VERIFY] success=True reason=Payment History section is now visible
```

### Verified locally (multi-step, live ADK)

| Goal | Loop |
| --- | --- |
| Open my electricity bill **and show the payment details** | click `#view-bill` → click `#payment-details` → **completed** (3 steps) |
| Open my electricity bill | click `#view-bill` → **completed** (2 steps) |
| Book me a flight to Paris | **blocked** step 1 (no invented selectors, no random clicks) |
| Pay my electricity bill | **needs_confirmation** on `#pay-button` step 1 |

## Architecture (Phase 6 routing in `agents/root_agent.py`)

```
                 STRUCTURE AGENT  (DOM / ARIA only, fast)
                 page_type + relevant_elements + confidence + needs_vision
                            |
                     [ROUTER]  confidence >= 0.85 and not needs_vision ?
                       /                                        \
                     yes                                         no  (and a screenshot exists)
                      |                                           |
                      |                                  VISION AGENT  (screenshot + candidates)
                      |                                  selected_selector + meaning + confidence
                      |                                           |
                      |                          selector must exist in the real DOM,
                      |                          else the pick is rejected (hallucination guard)
                      |                                           |
                      |                                  RECONCILIATION AGENT   (Phase 7)
                      |                                  structure vs vision -> AGREE / CONFLICT / UNKNOWN
                      |                                           |
                      |                      deterministic gate in Python:
                      |                      status != AGREE  ->  action = none, Action Agent NOT reached
                      |                      ("I found conflicting information ... I won't activate it.")
                       \_________________________________________/
                            |
                       ACTION AGENT   (gets perception.mode = structure | vision;
                                       prefers a vision_target when present)
                            |
                   gemini._normalize      <- Phase 2 safety layer, kept
                   (allowed action, no invented selector, confidence)
                            |
                      AgentResponse  (+ perception_mode, vision_used, timings)

      VERIFICATION AGENT  (Phase 8 - separate turn, after the extension re-inspects)
      goal + before + action + after
        -> deterministic evidence extraction (compare_page_states)
        -> agent judges the GOAL -> VERIFIED | FAILED | AMBIGUOUS
        -> deterministic overrides:
             success = (status == VERIFIED)                 # no false success
             retry_allowed = policy(status, risk_level)     # AMBIGUOUS/high-risk -> never
      { status, success, reason, evidence[], retry_allowed, risk_level }
```

### Phase 8 - verification lifecycle

`policy.py` (import-cycle-free, shared by `agents/` and `loop/`):
`classify_risk` · `risk_level` (low/medium/high) · `retry_allowed(status, level)`
(only a non-high-risk **FAILED** may retry; VERIFIED/AMBIGUOUS/BLOCKED/NEEDS_CONFIRMATION never).

- **Loop**: `AMBIGUOUS` -> `LoopStatus.AMBIGUOUS` hard stop, no retry.
  `FAILED` + not `retry_allowed` -> stop; `FAILED` + `retry_allowed` -> one recovery pass.
- **Chat**: `try again` after an `AMBIGUOUS` consequential action -> deterministic
  refusal ("I can't safely retry ... could duplicate it"). `did it work?` ->
  answered from stored `last_verification` evidence, never guessed.
- **NEEDS_CONFIRMATION**: pre-action risk gate; the reply names the amount when
  one is on the page ("This will pay ₹2,450. Say \"yes\" ...").
- `SessionState.last_verification` persisted to Firestore.

Vision is a **fallback, not the default**: an unambiguous page costs one
Structure call; only an ambiguous/icon page adds the Vision call. `run_agent`
logs `[STRUCTURE] confidence=` / `[ROUTER] vision=` / `[VISION] selected=` and
returns `timings {structure_ms, vision_ms?, action_ms}`.

| Path | Role |
| --- | --- |
| `agents/config.py` | ADK→Vertex env wiring, `MODEL = "gemini-3.5-flash"` |
| `agents/schemas.py` | typed outputs: `StructureResult`, `VisionResult`, `ActionDecision`, `VerificationResult`, `DialogueInterpretation` |
| `agents/structure_agent.py` | DOM/ARIA-only, `output_key="structure"` (+ `confidence`, `needs_vision`) |
| `agents/vision_agent.py` | multimodal, `output_key="vision"` - picks a candidate selector from the screenshot |
| `agents/reconciliation_agent.py` | `output_key="reconciliation"` - AGREE / CONFLICT / UNKNOWN (runs only when Vision ran) |
| `agents/action_agent.py` | LlmAgent, `output_key="action"` - consumes the merged perception |
| `agents/verification_agent.py` | LlmAgent, `output_key="verification"` |
| `agents/dialogue_agent.py` | Phase 5 message interpreter |
| `agents/root_agent.py` | `SequentialAgent`, ADK `Runner` + `InMemorySessionService`, orchestration logging, `run_agent(...history_text)` / `run_verification()` |
| `loop/` | Phase 4 controller: `run_loop_step(LoopStepRequest) -> LoopStepResponse` |
| `sessions/` | Phase 5: `SessionManager`, `run_chat_turn`, Firestore-backed `SessionState` |
| `tools/page_context.py` | `summarize_page_context` FunctionTool |
| `tools/action_tools.py` | `click_element` / `type_text` / `select_option` / `scroll_page` / `go_back` → structured action requests |
| `tools/verification_tools.py` | `compare_page_states` FunctionTool |
| `memory/` | reserved for Phase 5 (Firestore). Not implemented. |
| `gemini.py` | page summariser + `_normalize` safety layer (reused by the agents); `ask_gemini` kept as a fallback if the ADK pipeline throws |
| `models.py` | HTTP contract: `AgentRequest/Response`, `VerifyRequest/Response` |

Each `/agent` call = **2 Gemini calls** (perception, then action). `/verify` = 1.

## Run locally

```powershell
cd K:\projects\reach\backend
..\.venv\Scripts\Activate.ps1
$env:GOOGLE_CLOUD_PROJECT = "reach-agent-507107"
python -m uvicorn main:app --reload --port 8080
```

(`python -m uvicorn`, not the bare shim.) ADK routes through Vertex because
`config.py` sets `GOOGLE_GENAI_USE_VERTEXAI=TRUE` + `GOOGLE_CLOUD_LOCATION=asia-south1`.

## Orchestration log (demo-ready)

```
reach.adk: [ROOT] goal='open my electricity bill' url='file:///d' (2 known selectors)
reach.adk: [ACT] perception_agent emitted output
reach.adk: [ACT] action_agent emitted output
reach.adk: [PERCEPTION] {'page_type': 'billing', 'relevant_elements': [{'selector': '#view-bill', ...}]}
reach.adk: [ACTION] raw {'action': 'click', 'target': '#view-bill', 'confidence': 1.0, ...}
reach.adk: [ROOT] -> action=click target=#view-bill confidence=1.00
reach.adk: [VERIFICATION] -> {'success': True, 'reason': "URL changed to .../bill and 'Amount Due' is shown"}
```

## Verified locally

| Goal | `/agent` result |
| --- | --- |
| Open my electricity bill | `click #view-bill` (1.0) |
| Set language to Kannada | `select #language` = `kannada` (1.0) |
| Buy a plane ticket to Paris | `none` (0.0) |
| click #ghost-button | `none` (invented selector refused) |

`/verify` (click `#view-bill` → bill page) → `{"success": true, "reason": "..."}`

## Deploy

`requirements.txt` pins `google-adk==2.8.0` + `google-cloud-firestore==2.29.0`.

```powershell
.\deploy.ps1   # gcloud run deploy --source . --region asia-south1 --min-instances 0
```

Cloud Run runtime service account needs:
- `roles/aiplatform.user` (Phase 2)
- `roles/datastore.user` (Phase 5 - Firestore sessions):
  ```powershell
  gcloud projects add-iam-policy-binding reach-agent-507107 `
    --member "serviceAccount:$NUM-compute@developer.gserviceaccount.com" `
    --role "roles/datastore.user"
  ```
  If missing, `/chat` still works but sessions fall back to per-instance memory
  (lost on restart / across instances) - the `/` response shows
  `session_backend: memory` vs `firestore`.

Set `REACH_SESSION_BACKEND=memory` to force the in-memory store (e.g. offline dev).

## Note

`vertexai.generative_models` (used by `gemini.py`'s fallback) is deprecated
(support ends 2026-06-24). The ADK path uses `google-genai` under the hood.
