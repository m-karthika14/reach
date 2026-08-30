# REACH Extension — Phase 3

Browser observation + action layer (Phase 1) **plus** a goal box that calls the
backend. As of Phase 3 the backend is a Google ADK agent team
(`/agent` = perception → action), and after the extension runs the action it
re-inspects the page and calls `/verify` (Verification Agent).

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

## Ask REACH (Phase 2)

1. Start the backend (`backend/README.md`) at `http://127.0.0.1:8080`.
2. Open `demo-site/index.html`, open the popup.
3. Type a goal (e.g. *Open my electricity bill*) → **Ask REACH**.
4. The popup shows `action / target / confidence / reasoning`. If
   `confidence >= 0.80` and **auto-run** is checked, it executes via the Phase 1
   engine, the demo page's status line updates, then the popup re-inspects and
   calls `/verify` — showing `Verified: … achieved the goal` or `Could not verify`.

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
