# `memory/` — persistent memory + RAG (Phase 9)

Firestore db **`reach-memory`**, four collections:

| Collection | What it holds |
| --- | --- |
| `page_memory` | learned elements: `{domain, page, element, selector, description, verified, confidence, hits, misses}` — id is stable per `(domain, page, selector)` so repeats update in place |
| `correction_memory` | `{user_id, domain, page, selector, role, accessible_name, element_text, agent_prediction, correct_label, user_said, strength, confidence, verified}` — **append-only** (history kept, Step 10.8) |
| `preference_memory` | **one doc per user**, id `pref_<user_id>`: `{user_id, language, verbosity, confirmation_style, preferred_navigation, confirmation_before_payment, frequently_used_sites}` (Phase 11, `preferences.py`) |
| `task_history` | `{session_id, goal, domain, page, actions[], result}` |

## Files

| File | Role |
| --- | --- |
| `models.py` | the four pydantic schemas |
| `store.py` | Firestore wrapper + in-memory fallback (`REACH_SESSION_BACKEND=memory` forces it) |
| `util.py` | `domain_of(url)` / `page_of(url)` (handles `file://` demo URLs) |
| `writer.py` | `MemoryWriter` — `learn_page_element` / `weaken_page_element` / `record_correction` / `set_preference` / `record_task` / `apply_verification_outcome` |
| `retrieval.py` | `MemoryRetriever.retrieve(url, goal)` → small dict; `render_memory()` → prompt text |

## Rules (enforced, not hoped for)

- **Memory is a hint, never authority.** The current PAGE SUMMARY is ground
  truth; agent prompts say so, and `_normalize` still rejects any selector not
  on the page — so stale memory can't drive an action.
- **Only verified knowledge is strengthened.** `apply_verification_outcome`:
  `VERIFIED` → `learn_page_element` (verified=true, confidence↑); `FAILED` →
  `weaken_page_element` (confidence −0.3, verified false below 0.6);
  `AMBIGUOUS`/`BLOCKED` → `task_history` only.
- **Retrieval is filtered**, not a dump: match domain → rank by
  same-page + verified + confidence + recency → cap (6 page / 4 corrections / 3 tasks).

## The RAG loop

```
run_agent:  retrieve(url, goal)  ->  render into STRUCTURE + ACTION prompts
                                     (a remembered, still-present selector lets
                                      Structure be confident and skip Vision)
            ...action... execute... verify...
loop/chat:  apply_verification_outcome(...)  ->  page_memory / task_history
```

`GET /memory?url=<page>` returns the retrieved dict for the extension's
"REACH memory" panel.

## Phase 10 - correction learning

`"no, that's the payment button"` → the Dialogue Agent emits a structured
`correction {selector, previous_label, correct_label, strength}` (selector found
from the last assistant message / pending confirmation / last action).
`conversation.py` calls `writer.record_correction(...)` → a **new** row in
`correction_memory` (id auto), `confidence` from `strength` (weak .60 / normal
.78 / strong .90), consistent repeats bump it.

Retrieval `_aggregate_corrections` groups by selector: multiple **different**
labels → `conflicting: true` (never ranked on); consistent → highest confidence,
`count`, `verified` (any).

**Correction-aware ranking** (`root_agent._apply_correction_ranking`, runs after
the Action Agent, before `_normalize`): `match_corrections_to_candidates` maps a
correction to a live selector (exact, else by role+name+text signature). If a
non-conflicting corrected element is on the page and its label matches the goal:
- Action already targets it → **boost** confidence to ≥0.95
- Action targets something else with conf <0.9 → **override** target, conf 0.92
- explanation (`base_target`, `corrected_selector`, `effect`, `final_confidence`)
  returned as `AgentResponse.ranking`

`mark_correction_verified` flips `verified=true` after a VERIFIED action on that
element (Step 10.21). Corrections are `user_id`-scoped (Step 10.33) and the live
page still wins — a stale correction whose selector is gone has no effect, and a
memory-vs-vision contradiction goes through Reconciliation → CONFLICT → no act.
