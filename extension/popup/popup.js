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

// ---- Conversation (Phase 5: stateful multi-turn dialogue) -----------------

const chatLog = $("chatLog");
const chatInput = $("chatInput");
const sessionInfo = $("sessionInfo");
let chatSessionId = null;
let chatPrevDom = null;      // observation before the last executed action
let chatLastExecuted = null; // {action,target,value,success} to report next turn

chrome.storage.local.get(["reach_session_id"], (saved) => {
  chatSessionId = saved.reach_session_id || null;
  renderSessionInfo();
});

function renderSessionInfo() {
  sessionInfo.textContent = chatSessionId ? `session: ${chatSessionId}` : "no session yet";
}

function chatMsg(kind, who, text) {
  const el = document.createElement("div");
  el.className = "chat-msg " + kind;
  el.innerHTML = who ? `<span class="who">${who}:</span> ` : "";
  el.appendChild(document.createTextNode(text));
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
}

// ---- Personalization (Phase 11) -----------------------------------------

const userIdInput = $("userId");
const PREF_FIELDS = {
  prefVerbosity: "verbosity",
  prefLanguage: "language",
  prefConfirm: "confirmation_style",
  prefNav: "preferred_navigation"
};

function currentUserId() {
  return (userIdInput.value.trim() || "demo-user");
}

async function loadPreferences() {
  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  try {
    const r = await fetch(`${backend}/preferences?user_id=${encodeURIComponent(currentUserId())}`);
    if (!r.ok) return;
    const p = await r.json();
    for (const [id, field] of Object.entries(PREF_FIELDS)) {
      if (p[field] != null) $(id).value = p[field];
    }
  } catch (e) { /* offline */ }
}

async function patchPreference(field, value) {
  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  try {
    await fetch(`${backend}/preferences`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: currentUserId(), [field]: value })
    });
  } catch (e) { /* offline */ }
}

for (const [id, field] of Object.entries(PREF_FIELDS)) {
  $(id).addEventListener("change", () => patchPreference(field, $(id).value));
}
userIdInput.addEventListener("change", () => {
  chrome.storage.local.set({ reach_user_id: currentUserId() });
  loadPreferences();
});
chrome.storage.local.get(["reach_user_id"], (s) => {
  if (s.reach_user_id) userIdInput.value = s.reach_user_id;
  loadPreferences();
});

const memoryPanel = $("memoryPanel");

function renderMemory(mem) {
  if (!mem || (!mem.page_memory?.length && !mem.corrections?.length && !mem.preferences?.length)) {
    memoryPanel.textContent = "no memory of this site yet";
    return;
  }
  const esc = (s) => String(s).replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
  let html = "";
  if (mem.domain) html += `<div class="mem-group">${esc(mem.domain)}</div>`;
  if (mem.page_memory?.length) {
    html += `<div class="mem-group">learned elements</div>`;
    for (const r of mem.page_memory) {
      html += `<div>${r.verified ? '<span class="mem-verified">✓</span> ' : "· "}${esc(r.element)} = <code>${esc(r.selector)}</code> (${Math.round((r.confidence || 0) * 100)}%)</div>`;
    }
  }
  if (mem.corrections?.length) {
    html += `<div class="mem-group">user corrections</div>`;
    for (const c of mem.corrections) {
      if (c.conflicting) {
        html += `<div>⚠ <code>${esc(c.selector)}</code> — conflicting feedback, not trusted</div>`;
      } else {
        html += `<div>${c.verified ? '<span class="mem-verified">✓</span> ' : "· "}<code>${esc(c.selector)}</code> → "${esc(c.correct_label)}"` +
          (c.previous_label ? ` (was "${esc(c.previous_label)}")` : "") +
          ` ${Math.round((c.confidence || 0) * 100)}%${c.count > 1 ? ` ×${c.count}` : ""}</div>`;
      }
    }
  }
  const pr = mem.preferences;
  if (pr && typeof pr === "object" && !Array.isArray(pr)) {
    html += `<div class="mem-group">preferences (${esc(pr.user_id || "demo-user")})</div>`;
    for (const k of ["verbosity", "language", "confirmation_style", "preferred_navigation"]) {
      if (pr[k] != null) html += `<div>${k} = <code>${esc(pr[k])}</code></div>`;
    }
  }
  memoryPanel.innerHTML = html;
}

async function refreshMemory() {
  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  const tab = await activeTab();
  const url = tab ? tab.url : "";
  try {
    const r = await fetch(`${backend}/memory?url=${encodeURIComponent(url || "")}`);
    if (r.ok) renderMemory(await r.json());
  } catch (e) { /* offline - leave panel as is */ }
}
$("refreshMemory").addEventListener("click", refreshMemory);

$("newChat").addEventListener("click", () => {
  chatSessionId = null;
  chatPrevDom = null;
  chatLastExecuted = null;
  chrome.storage.local.remove("reach_session_id");
  chatLog.innerHTML = "";
  renderSessionInfo();
});

async function sendChat() {
  const message = chatInput.value.trim();
  if (!message) return;
  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  chatInput.value = "";
  chatMsg("user", "You", message);

  const tab = await activeTab();
  if (!tab?.id) return chatMsg("meta", "", "No active tab.");
  const page = await sendToTab(tab.id, { type: "GET_PAGE_CONTEXT" });
  if (page?.__error) return chatMsg("meta", "", "Cannot read this page: " + page.__error);

  // Always send a screenshot so the backend can fall back to the Vision Agent
  // when the DOM is ambiguous (Phase 6). It only *uses* it when routing says so.
  let screenshot = null;
  const s = await captureScreenshot(tab.windowId);
  if (s?.success) screenshot = s.dataUrl;

  let r;
  try {
    const resp = await fetch(backend + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: chatSessionId,
        user_id: currentUserId(),
        message,
        url: page.url,
        dom: JSON.stringify(page),
        screenshot,
        prev_dom: chatPrevDom,
        last_executed: chatLastExecuted
      })
    });
    if (!resp.ok) return chatMsg("meta", "", `Backend ${resp.status}: ${await resp.text()}`);
    r = await resp.json();
  } catch (e) {
    return chatMsg("meta", "", "Could not reach the backend: " + e);
  }

  // clear the "last executed" report now that it's been sent
  chatPrevDom = null;
  chatLastExecuted = null;

  chatSessionId = r.session_id;
  chrome.storage.local.set({ reach_session_id: chatSessionId });
  renderSessionInfo();

  chatMsg("reach", "REACH", r.message);
  if (r.memory) renderMemory(r.memory);
  if (r.preference_updated) {
    chatMsg("meta", "", "⚙ preference: " + Object.entries(r.preference_updated).map(([k, v]) => `${k}=${v}`).join(", "));
    loadPreferences();
  }
  if (r.memory_updated && r.correction) {
    chatMsg("meta", "", `✎ learned: ${r.correction.selector} → "${r.correction.correct_label}" (persisted to Firestore)`);
  }
  if (r.ranking && r.ranking.correction_applied) {
    const rk = r.ranking;
    chatMsg("meta", "",
      `🧠 correction ${rk.effect}: ${rk.corrected_selector} → "${rk.correct_label}"` +
      (rk.effect === "override" ? ` (chosen over ${rk.base_target || "model pick"})` : ` (${Math.round((rk.final_confidence || 0) * 100)}%)`));
  } else if (r.memory_used) {
    chatMsg("meta", "", "🧠 used remembered knowledge of this site");
  }
  if (r.reconciliation && r.reconciliation.status) {
    const rc = r.reconciliation;
    chatMsg("meta", "",
      `reconciliation: ${rc.status}` +
      (rc.status !== "AGREE"
        ? ` — structure "${rc.structure_interpretation || "?"}" vs vision "${rc.vision_interpretation || "?"}"`
        : ""));
  }
  if (r.verification_status) {
    const v = r.verification_status;
    const icon = v.status === "VERIFIED" ? "✓" : v.status === "AMBIGUOUS" ? "⚠" : "✗";
    chatMsg("meta", "", `verify: ${icon} ${v.status || (v.success ? "ok" : "?")} — ${v.reason || ""}`);
    if (Array.isArray(v.evidence) && v.evidence.length) {
      chatMsg("meta", "", "evidence: " + v.evidence.slice(0, 4).join("; "));
    }
    if (v.status === "AMBIGUOUS") {
      chatMsg("meta", "", "retry blocked — REACH will not repeat a consequential action it can't confirm.");
    }
  }

  const a = r.action;
  if (a && a.perception_mode) {
    const t = a.timings || {};
    const ms = a.vision_used
      ? `structure ${t.structure_ms}ms + vision ${t.vision_ms}ms`
      : `structure ${t.structure_ms}ms`;
    chatMsg("meta", "", `perception: ${a.vision_used ? "vision 👁" : "structure"} (${ms})`);
  }
  if (!a || a.action === "none") return;

  if (r.requires_confirmation) {
    chatMsg("meta", "", `pending: ${a.action} ${a.target || ""} — say "yes" to proceed`);
    return;
  }
  if ((a.confidence ?? 0) < 0.85) {
    chatMsg("meta", "", `not run (confidence ${Math.round((a.confidence ?? 0) * 100)}%)`);
    return;
  }

  const msg = { type: "EXECUTE_ACTION", action: ACTION_MAP[a.action] };
  if (a.target) msg.selector = a.target;
  if (a.value != null) msg.value = a.value;
  if (a.action === "scroll") msg.amount = 600;

  const result = await sendToTab(tab.id, msg);
  if (result && result.success) {
    chatMsg("meta", "", `↳ executed ${a.action} ${a.target || ""}`);
    chatPrevDom = JSON.stringify(page);
    chatLastExecuted = { action: a.action, target: a.target, value: a.value, success: true };
  } else {
    chatMsg("meta", "", "↳ execution failed: " + JSON.stringify(result));
  }
}

$("chatSend").addEventListener("click", sendChat);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

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
    ok ? `Executed ${action.action}. Verifying…` : `Execution failed.`,
    detail + `<div>result: <code>${JSON.stringify(result)}</code></div>`
  );
  if (!ok) return;

  // Verification Agent: re-inspect the page and ask the backend if the goal advanced.
  await new Promise((r) => setTimeout(r, 900));
  const afterPage = await sendToTab(tab.id, { type: "GET_PAGE_CONTEXT" });
  if (afterPage?.__error) return;

  try {
    const vResp = await fetch(backend + "/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal,
        action,
        before_dom: JSON.stringify(page),
        after_dom: JSON.stringify(afterPage),
        after_url: afterPage.url
      })
    });
    if (!vResp.ok) return;
    const v = await vResp.json();
    showAgent(
      v.success ? "ok" : "hold",
      v.success ? `Verified: ${action.action} achieved the goal.` : "Could not verify the goal.",
      detail +
        `<div>result: <code>${JSON.stringify(result)}</code></div>` +
        `<div>verification: <code>${v.success}</code> — ${v.reason || ""}</div>`
    );
  } catch (e) {
    /* verification is best-effort; leave the "Executed" state as-is */
  }
});

// ---- Run task (Phase 4 autonomous loop) -----------------------------------

const MAX_CLIENT_STEPS = 8;
const SETTLE_MS = 1000;
const LOOP_STOP = ["blocked", "failed", "ambiguous", "max_steps_reached", "repeated_action", "low_confidence"];

const runTaskBtn = $("runTask");
const stopTaskBtn = $("stopTask");
const loopLog = $("loopLog");
let loopAbort = false;

function logLine(kind, text) {
  const el = document.createElement("div");
  el.className = "loop-line " + (kind || "");
  el.textContent = text;
  loopLog.appendChild(el);
  loopLog.scrollTop = loopLog.scrollHeight;
}

function askApproval() {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "loop-line approve";
    const yes = document.createElement("button");
    yes.textContent = "Approve";
    yes.className = "primary";
    const no = document.createElement("button");
    no.textContent = "Cancel";
    yes.onclick = () => { wrap.remove(); resolve(true); };
    no.onclick = () => { wrap.remove(); resolve(false); };
    wrap.append(yes, no);
    loopLog.appendChild(wrap);
    loopLog.scrollTop = loopLog.scrollHeight;
  });
}

function endLoop() {
  runTaskBtn.disabled = false;
  stopTaskBtn.hidden = true;
  loopAbort = false;
}

stopTaskBtn.addEventListener("click", () => {
  loopAbort = true;
  stopTaskBtn.disabled = true;
  logLine("hold", "⏹ Stop requested — halting after this step.");
});

function describe(step) {
  return (
    `${step.action}` +
    (step.target ? ` ${step.target}` : "") +
    (step.value != null ? ` = ${step.value}` : "") +
    ` (${Math.round((step.confidence ?? 0) * 100)}%` +
    (step.vision_used ? ", vision 👁" : step.perception_mode ? ", structure" : "") +
    (step.reconciliation ? `, reconcile ${step.reconciliation.status}` : "") +
    `)`
  );
}

runTaskBtn.addEventListener("click", async () => {
  const goal = goalInput.value.trim();
  if (!goal) return;
  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  chrome.storage.local.set({ goal, backend });

  agentResult.hidden = true;
  loopLog.hidden = false;
  loopLog.innerHTML = "";
  loopAbort = false;
  runTaskBtn.disabled = true;
  stopTaskBtn.hidden = false;
  stopTaskBtn.disabled = false;
  logLine("head", `Goal: ${goal}`);

  const tab = await activeTab();
  if (!tab?.id) { logLine("err", "No active tab."); return endLoop(); }

  let history = [];
  let prevDom = null;
  let lastAction = null;

  try {
    for (let i = 0; i < MAX_CLIENT_STEPS; i++) {
      if (loopAbort) { logLine("hold", "Cancelled by user."); break; }

      const page = await sendToTab(tab.id, { type: "GET_PAGE_CONTEXT" });
      if (page?.__error) { logLine("err", "Cannot read page: " + page.__error); break; }
      const dom = JSON.stringify(page);

      let screenshot = null;
      const shot = await captureScreenshot(tab.windowId);
      if (shot?.success) screenshot = shot.dataUrl;

      let step;
      try {
        const r = await fetch(backend + "/agent/loop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            goal,
            url: page.url,
            dom,
            screenshot,
            history,
            prev_dom: prevDom,
            last_action: lastAction,
            max_steps: MAX_CLIENT_STEPS
          })
        });
        if (!r.ok) { logLine("err", `Backend ${r.status}: ${await r.text()}`); break; }
        step = await r.json();
      } catch (e) {
        logLine("err", "Could not reach backend: " + e);
        break;
      }

      const label = `Step ${step.step}/${MAX_CLIENT_STEPS} · ${step.status}`;

      if (step.status === "completed") {
        logLine("ok", `✅ ${label} — ${step.reason || "goal achieved"}`);
        break;
      }
      if (LOOP_STOP.includes(step.status)) {
        logLine("err", `⛔ ${label} — ${step.reason || ""}`);
        break;
      }

      if (step.status === "needs_confirmation") {
        logLine("hold", `⚠ ${label} — wants: ${describe(step)}`);
        if (step.reason) logLine("hold", step.reason);
        const ok = await askApproval();
        if (!ok) { logLine("hold", "Declined — stopping."); break; }
      } else {
        logLine("", `${label} — ${describe(step)}`);
        if (step.reason) logLine("dim", step.reason);
      }

      if (step.action === "none") { logLine("err", "No executable action returned."); break; }

      const msg = { type: "EXECUTE_ACTION", action: ACTION_MAP[step.action] };
      if (step.target) msg.selector = step.target;
      if (step.value != null) msg.value = step.value;
      if (step.action === "scroll") msg.amount = 600;

      const result = await sendToTab(tab.id, msg);
      if (!result || !result.success) {
        logLine("err", "Execution failed: " + JSON.stringify(result));
        break;
      }
      logLine("dim", `↳ executed ${step.action}`);

      history.push({ step: step.step, action: step.action, target: step.target, value: step.value });
      prevDom = dom;
      lastAction = { action: step.action, target: step.target, value: step.value };

      await new Promise((r) => setTimeout(r, SETTLE_MS));
      if (i === MAX_CLIENT_STEPS - 1) logLine("err", "Reached client step cap.");
    }
  } finally {
    endLoop();
  }
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
