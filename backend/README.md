# REACH Backend — Phase 4

FastAPI → **Google ADK agent team** → **Gemini 3.5 Flash** (Vertex AI, `asia-south1`).

`main.py` is only the HTTP boundary. Reasoning/orchestration lives in `agents/`;
the browser-loop controller lives in `loop/`.

```
POST /agent        goal + page context      ->  Root Agent [ perception -> action ]  ->  one action
POST /agent/loop   goal + observation + history ->  verify -> reason -> safety gates  ->  next step
POST /verify       before + action + after   ->  Verification Agent                   ->  {success, reason}
GET  /health
```

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
        action == none                   -> status = blocked
        (action,target) x3 in a row      -> status = repeated_action
        confidence < 0.80                -> status = low_confidence
        consequential token in target    -> status = needs_confirmation (requires_confirmation)
        otherwise                        -> status = running  (extension executes, then loops)
```

`loop/state.py` status vocabulary · `loop/history.py` compact history + repeat
detection · `loop/safety.py` consequential-action classifier (`pay`, `buy`,
`delete`, `transfer`, … as whole tokens of the target/value, never the goal) ·
`loop/controller.py` the step above.

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

## Architecture

```
                       ROOT AGENT  (SequentialAgent, shared session state)
                            |
              +-------------+-------------+
              v                           v
      PERCEPTION AGENT              ACTION AGENT
   page_type + relevant_elements   click/type/select/scroll/back/none
              \___________________________/
                            |
                   gemini._normalize        <- Phase 2 safety layer, kept
                   (allowed action, no invented selector, confidence)
                            |
                      AgentResponse

      VERIFICATION AGENT  (separate turn, after the extension re-inspects)
      goal + before + action + after  ->  { success, reason }
```

| Path | Role |
| --- | --- |
| `agents/config.py` | ADK→Vertex env wiring, `MODEL = "gemini-3.5-flash"` |
| `agents/schemas.py` | agent-to-agent typed outputs (`PerceptionResult`, `ActionDecision`, `VerificationResult`) |
| `agents/perception_agent.py` | LlmAgent, `output_key="perception"` |
| `agents/action_agent.py` | LlmAgent, `output_key="action"` |
| `agents/verification_agent.py` | LlmAgent, `output_key="verification"` |
| `agents/root_agent.py` | `SequentialAgent`, ADK `Runner` + `InMemorySessionService`, orchestration logging, `run_agent(...history_text)` / `run_verification()` |
| `loop/` | Phase 4 controller: `run_loop_step(LoopStepRequest) -> LoopStepResponse` |
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

`requirements.txt` now pins `google-adk==2.8.0`. After the local flow works:

```powershell
.\deploy.ps1   # gcloud run deploy --source . --region asia-south1 --min-instances 0
```

The Cloud Run runtime service account needs `roles/aiplatform.user` (granted in Phase 2).

## Note

`vertexai.generative_models` (used by `gemini.py`'s fallback) is deprecated
(support ends 2026-06-24). The ADK path uses `google-genai` under the hood.
