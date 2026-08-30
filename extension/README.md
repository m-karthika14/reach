# REACH Extension — Phase 4

Browser observation + action layer (Phase 1) plus a goal box. The extension is
the **loop runtime**: it observes the page, calls the backend for the next step,
executes it, re-observes, and repeats until the backend says `completed` (or a
safety gate / the Stop button ends it).

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

Loop caps: client step limit 8, backend `max_steps` 8, confidence gate 0.80,
3× repeated `(action,target)` stops, invented selectors refused.

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
