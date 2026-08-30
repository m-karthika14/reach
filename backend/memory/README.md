# `memory/` — persistent memory + RAG (Phase 9)

Firestore db **`reach-memory`**, four collections:

| Collection | What it holds |
| --- | --- |
| `page_memory` | learned elements: `{domain, page, element, selector, description, verified, confidence, hits, misses}` — id is stable per `(domain, page, selector)` so repeats update in place |
| `correction_memory` | `{domain, page, user_said, agent_assumed, correct_element, reason}` |
| `preference_memory` | `{preference, value}` — id `pref_<name>` |
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
