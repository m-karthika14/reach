# REACH Extension — Phase 11

New **Personalization** panel: a `user id` field plus dropdowns for
**Style** (concise/normal/detailed), **Language**, **Confirm**
(always/risky only/minimal), **Navigation**. Changing one `PATCH`es
`/preferences`; the panel loads the stored profile on open and after any
in-chat preference change (`⚙ preference: …`). Switch the user id to demo
A-vs-B behaviour on the identical request. Chat requests now carry `user_id`.

---

# REACH Extension — Phase 10

Correction learning: tell REACH *"no, that's the payment button"* and the chat
logs `✎ learned: #icon-2 → "payment" (persisted to Firestore)`; the memory panel
shows it (`✓` once a later action verifies it, `⚠` if you've given conflicting
labels). In a **New chat** (or after a restart) asking *"where do I pay?"* logs
`🧠 correction boost/override: #icon-2 → "payment"` and clicks it.

---

# REACH Extension — Phase 9

New **REACH memory** panel — shows what REACH has learned about the current site
(verified elements, user corrections, preferences); **Refresh** pulls
`GET /memory?url=…`. When a turn used remembered knowledge the chat logs
`🧠 used remembered knowledge of this site`. Screenshots are still always sent,
but on a **repeat visit** memory often makes Structure confident enough that
Vision is skipped entirely.

---

# REACH Extension — Phase 8

After an action runs, the chat shows the verification verdict and evidence:
`verify: ⚠ AMBIGUOUS — no receipt / no transaction id` and, for AMBIGUOUS,
`retry blocked — REACH will not repeat a consequential action it can't confirm.`
"try again" after an ambiguous payment is refused; "did it work?" is answered
from stored evidence. New demo pages: `payment-test.html` (VERIFIED),
`ambiguous-test.html` (AMBIGUOUS), `failure-test.html` (FAILED).

---

# REACH Extension — Phase 7

The extension **always sends a screenshot** with chat and loop requests so the
backend can fall back to the Vision Agent (Phase 6) and then the Reconciliation
Agent (Phase 7). The chat log shows the route and, when Vision ran, the
reconciliation verdict:
`reconciliation: CONFLICT — structure "Cancel" vs vision "Pay Now"`.
On CONFLICT/UNKNOWN the chat enters `waiting_clarification` and REACH asks which
element you meant (naming it still re-runs the safety check).

Try it: open `demo-site/conflict-test.html`, say *"pay my electricity bill"*.

Browser observation + action layer (Phase 1) plus:
- **Conversation** panel — stateful multi-turn chat with REACH (`/chat`). The
  extension stores `reach_session_id` in `chrome.storage.local`; every turn
  sends it plus the fresh page observation and a report of what it executed
  last turn. REACH resolves "it" / "the second one" / "actually…" / "stop" /
  "continue" / "yes" against the persisted session.
- **Autonomous task** panel — the Phase 4 observe→reason→act→verify loop
  (`Run task` / `Stop`) and the Phase 3 `Single step` (`/agent`).

## Load

1. Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `k:\projects\reach\extension`
4. After any code change: click the **reload** icon on the REACH card, then
   **reload the web page** (content scripts only inject on fresh page loads).

## Files

| File | Role |
| --- | --- |
| `manifest.json` | MV3 manifest, permissions, script registration |
| `background/service-worker.js` | screenshot capture (`chrome.tabs.captureVisibleTab`) |
| `utils/resolve.js` | resolves a CSS selector **or** `{role, name}` target to an element |
| `content/actions.js` | CLICK / TYPE / SELECT / SCROLL / BACK |
| `content/content.js` | `getPageContext()` + message router |
| `popup/*` , `styles/popup.css` | Inspect button + action test form |

## Conversation (Phase 5)

1. Backend running (local or Cloud Run URL in the **backend** box).
2. Open `demo-site/index.html`, open the popup.
3. Chat, one line at a time:
   ```
   You: open my electricity bill        REACH: Opening it.            [runs click #view-bill]
   You: show the payment history        REACH: Showing payment history [runs click #payment-details]
   You: stop                            REACH: Okay, I've stopped.
   You: continue                        REACH: (resumes from stored state)
   ```
4. **New chat** drops the session id and starts fresh.
5. Consequential actions reply *"say 'yes' to go ahead"* and wait.

## Run task (Phase 4 autonomous loop)

1. Start the backend (`backend/README.md`) or point the **backend** box at the
   Cloud Run URL.
2. Open `demo-site/index.html`, open the popup.
3. Type a goal, e.g. *Open my electricity bill and show the payment details*.
4. **Run task** → the step log fills in live:
   ```
   Goal: Open my electricity bill and show the payment details
   Step 1/8 · running — click #view-bill (100%)
   ↳ executed click
   Step 2/8 · running — click #payment-details (100%)
   ↳ executed click
   ✅ Step 3/8 · completed — Payment History section is now visible
   ```
5. **Stop** halts after the current step. Consequential actions (e.g. `#pay-button`)
   pause with **Approve / Cancel**.

`Single step` keeps the Phase 3 one-shot behaviour (`/agent` + `/verify`).

Loop caps: client step limit 8, backend `max_steps` 8, loop confidence gate 0.85
(stricter than the 0.80 single-step gate), 3rd repeat of any `(action,target)`
stops, invented selectors refused. An impossible goal (e.g. "book a flight" on
the billing demo) stops as `blocked` / `low_confidence`, not random clicks.

Backend URL and last goal are remembered in `chrome.storage.local`.
`storage` permission added to the manifest for this.

## Test with the demo site

Open `k:\projects\reach\demo-site\index.html` in Chrome (`file://` works).

- **Inspect Page** → JSON dump of URL, title, visible text, buttons, links,
  inputs (with `<select>` options), headings, images, ARIA roles + a screenshot.
- **Execute action** form:
  - CLICK `#pay-button` → status line on the page updates
  - TYPE `#email` value `demo@example.com`
  - SELECT `#language` value `kannada`
  - SCROLL `600`
  - Click the *Go to Page B* link, then BACK
