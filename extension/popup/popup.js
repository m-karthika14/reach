// REACH popup (Phase 1).
// Drives two things against the active tab's content script:
//   - GET_PAGE_CONTEXT  (+ optional screenshot via the service worker)
//   - EXECUTE_ACTION     (CLICK / TYPE / SELECT / SCROLL / BACK)

const $ = (id) => document.getElementById(id);

const output = $("output");
const thumbWrap = $("thumbWrap");
const thumb = $("thumb");

function print(value) {
  output.textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function sendToTab(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ __error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response);
    });
  });
}

function captureScreenshot(windowId) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT", windowId }, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ success: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response);
    });
  });
}

// ---- Inspect ---------------------------------------------------------------

$("inspect").addEventListener("click", async () => {
  print("Inspecting...");
  thumbWrap.hidden = true;

  const tab = await activeTab();
  if (!tab?.id) return print("No active tab.");

  const page = await sendToTab(tab.id, { type: "GET_PAGE_CONTEXT" });
  if (page?.__error) {
    return print(
      "Could not inspect this page.\n\n" +
        page.__error +
        "\n\nThe content script does not run on chrome:// pages, the Web Store, " +
        "or PDF viewer. Try a normal http(s) page or the demo-site."
    );
  }

  let screenshotInfo = "skipped";
  if ($("withScreenshot").checked) {
    const shot = await captureScreenshot(tab.windowId);
    if (shot?.success && shot.dataUrl) {
      screenshotInfo = `captured (${Math.round(shot.dataUrl.length / 1024)} KB base64)`;
      thumb.src = shot.dataUrl;
      thumbWrap.hidden = false;
    } else {
      screenshotInfo = `failed: ${shot?.error || "unknown"}`;
    }
  }

  print({
    screenshot: screenshotInfo,
    page
  });
});

// ---- Action form ---------------------------------------------------------------

const actionType = $("actionType");
const selectorRow = $("selectorRow");
const valueRow = $("valueRow");
const amountRow = $("amountRow");

function syncActionForm() {
  const type = actionType.value;
  selectorRow.hidden = type === "SCROLL" || type === "BACK";
  valueRow.hidden = !(type === "TYPE" || type === "SELECT");
  amountRow.hidden = type !== "SCROLL";
}
actionType.addEventListener("change", syncActionForm);
syncActionForm();

// ---- Ask REACH (goal -> backend -> Gemini -> action) ------------------------

const CONFIDENCE_GATE = 0.8;
const DEFAULT_BACKEND = "http://127.0.0.1:8080";

const backendInput = $("backend");
const goalInput = $("goal");
const agentResult = $("agentResult");

// Restore saved backend URL + goal.
chrome.storage.local.get(["backend", "goal"], (saved) => {
  backendInput.value = saved.backend || DEFAULT_BACKEND;
  if (saved.goal) goalInput.value = saved.goal;
});
backendInput.addEventListener("change", () =>
  chrome.storage.local.set({ backend: backendInput.value.trim() })
);
goalInput.addEventListener("change", () =>
  chrome.storage.local.set({ goal: goalInput.value.trim() })
);

function showAgent(kind, verdict, detailHtml) {
  agentResult.hidden = false;
  agentResult.className = "agent-result " + kind;
  agentResult.innerHTML =
    `<div class="verdict">${verdict}</div>` + (detailHtml || "");
}

const ACTION_MAP = { click: "CLICK", type: "TYPE", select: "SELECT", scroll: "SCROLL", back: "BACK" };

$("ask").addEventListener("click", async () => {
  const goal = goalInput.value.trim();
  if (!goal) return showAgent("err", "Enter a goal first.");

  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  chrome.storage.local.set({ goal, backend });

  showAgent("hold", "Thinking…", "");

  const tab = await activeTab();
  if (!tab?.id) return showAgent("err", "No active tab.");

  const page = await sendToTab(tab.id, { type: "GET_PAGE_CONTEXT" });
  if (page?.__error) {
    return showAgent("err", "Cannot read this page.", `<div>${page.__error}</div>`);
  }

  let screenshot = null;
  if ($("askScreenshot").checked) {
    const shot = await captureScreenshot(tab.windowId);
    if (shot?.success) screenshot = shot.dataUrl;
  }

  let action;
  try {
    const resp = await fetch(backend + "/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, url: page.url, dom: JSON.stringify(page), screenshot })
    });
    if (!resp.ok) {
      const text = await resp.text();
      return showAgent("err", `Backend ${resp.status}`, `<div>${text}</div>`);
    }
    action = await resp.json();
  } catch (e) {
    return showAgent(
      "err",
      "Could not reach the backend.",
      `<div>${e}</div><div>Is uvicorn running at <code>${backend}</code>?</div>`
    );
  }

  const pct = Math.round((action.confidence ?? 0) * 100);
  const detail =
    `<div>action: <code>${action.action}</code>` +
    (action.target ? ` target: <code>${action.target}</code>` : "") +
    (action.value != null ? ` value: <code>${action.value}</code>` : "") +
    `</div><div>confidence: <code>${pct}%</code></div>` +
    (action.reasoning ? `<div>${action.reasoning}</div>` : "");

  if (action.action === "none") {
    return showAgent("hold", "REACH will not act here.", detail);
  }
  if ((action.confidence ?? 0) < CONFIDENCE_GATE) {
    return showAgent("hold", `Not confident enough (< ${CONFIDENCE_GATE * 100}%).`, detail);
  }
  if (!$("autoRun").checked) {
    return showAgent("ok", "Ready to run (auto-run off).", detail);
  }

  // Confidence gate passed -> execute via the Phase 1 action engine.
  const message = { type: "EXECUTE_ACTION", action: ACTION_MAP[action.action] };
  if (action.target) message.selector = action.target;
  if (action.value != null) message.value = action.value;
  if (action.action === "scroll") message.amount = 600;

  const result = await sendToTab(tab.id, message);
  const ok = result && result.success;
  showAgent(
    ok ? "ok" : "err",
    ok ? `Executed ${action.action}.` : `Execution failed.`,
    detail + `<div>result: <code>${JSON.stringify(result)}</code></div>`
  );
});

$("run").addEventListener("click", async () => {
  const tab = await activeTab();
  if (!tab?.id) return print("No active tab.");

  const type = actionType.value;
  const message = { type: "EXECUTE_ACTION", action: type };

  if (type !== "SCROLL" && type !== "BACK") {
    const sel = $("selector").value.trim();
    if (!sel) return print('Enter a CSS selector first (e.g. "#pay-button").');
    message.selector = sel;
  }
  if (type === "TYPE" || type === "SELECT") {
    message.value = $("value").value;
  }
  if (type === "SCROLL") {
    message.amount = Number($("amount").value) || 600;
  }

  print(`Running ${type}...`);
  const result = await sendToTab(tab.id, message);
  if (result?.__error) {
    return print("Action failed to reach the page.\n\n" + result.__error);
  }
  print(result);
});
