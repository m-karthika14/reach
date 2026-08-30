// REACH popup — voice + conversation UI.
//   voice (wake word "REACH") / text  ->  POST /chat  ->  speak + act on the page
//   personalization + memory panels are tucked into <details id="adv">.

const $ = (id) => document.getElementById(id);

// Resilient wrapper: if chrome.storage is unavailable (e.g. the extension was
// not fully reloaded after a manifest/permission change), fall back to an
// in-memory map so the rest of the popup still works.
const storageLocal = (() => {
  try {
    if (chrome && chrome.storage && chrome.storage.local) return chrome.storage.local;
  } catch (e) { /* noop */ }
  console.warn("chrome.storage.local unavailable - using in-memory fallback. Reload the extension.");
  const mem = {};
  return {
    get: (keys, cb) => {
      const out = {};
      (Array.isArray(keys) ? keys : [keys]).forEach((k) => { if (k in mem) out[k] = mem[k]; });
      cb && cb(out);
    },
    set: (obj, cb) => { Object.assign(mem, obj); cb && cb(); },
    remove: (keys, cb) => {
      (Array.isArray(keys) ? keys : [keys]).forEach((k) => delete mem[k]);
      cb && cb();
    }
  };
})();

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

// ---- config --------------------------------------------------------------

const DEFAULT_BACKEND = "http://127.0.0.1:8080";
const backendInput = $("backend");

storageLocal.get(["backend"], (saved) => {
  backendInput.value = saved.backend || DEFAULT_BACKEND;
});
backendInput.addEventListener("change", () =>
  storageLocal.set({ backend: backendInput.value.trim() })
);

const ACTION_MAP = { click: "CLICK", type: "TYPE", select: "SELECT", scroll: "SCROLL", back: "BACK" };

// ---- Conversation (Phase 5: stateful multi-turn dialogue) -----------------

const chatLog = $("chatLog");
const chatInput = $("chatInput");
const sessionInfo = $("sessionInfo");
let chatSessionId = null;
let chatPrevDom = null;      // observation before the last executed action
let chatLastExecuted = null; // {action,target,value,success} to report next turn

storageLocal.get(["reach_session_id"], (saved) => {
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
  storageLocal.set({ reach_user_id: currentUserId() });
  loadPreferences();
});
storageLocal.get(["reach_user_id"], (s) => {
  if (s.reach_user_id) userIdInput.value = s.reach_user_id;
  loadPreferences();
});

const memoryPanel = $("memoryPanel");

function renderMemory(mem) {
  if (!mem || (!mem.page_memory?.length && !mem.corrections?.length)) {
    memoryPanel.textContent = "";
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
  storageLocal.remove("reach_session_id");
  chatLog.innerHTML = "";
  renderSessionInfo();
});

async function sendChat() {
  const message = chatInput.value.trim();
  if (!message) return;
  chatInput.value = "";
  return submitMessage(message);
}

// A chat error that is also surfaced to voice/screen-reader users (Step 12.22).
function chatErr(msg) {
  chatMsg("meta", "", msg);
  if (typeof voiceState !== "undefined" && voiceState !== "idle") {
    setVoiceState("error", msg);
    speak(msg);
  }
  return null;
}

// Set true when a turn actually executed a browser action (so voice can auto-verify).
let lastTurnExecuted = false;

// Shared by the text box and the voice controller. Returns the /chat response.
async function submitMessage(message) {
  if (!message) return null;
  lastTurnExecuted = false;
  const backend = (backendInput.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  chatMsg("user", "You", message);

  const tab = await activeTab();
  if (!tab?.id) return chatErr("No active tab.");
  const page = await sendToTab(tab.id, { type: "GET_PAGE_CONTEXT" });
  if (page?.__error) return chatErr("Cannot read this page: " + page.__error);

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
    if (!resp.ok) return chatErr(`Backend ${resp.status}: ${await resp.text()}`);
    r = await resp.json();
  } catch (e) {
    return chatErr("Could not reach the backend: " + e);
  }

  // clear the "last executed" report now that it's been sent
  chatPrevDom = null;
  chatLastExecuted = null;

  chatSessionId = r.session_id;
  storageLocal.set({ reach_session_id: chatSessionId });
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
  if (!a || a.action === "none") return r;

  if (r.requires_confirmation) {
    chatMsg("meta", "", `pending: ${a.action} ${a.target || ""} — say "yes" to proceed`);
    return r;
  }
  if ((a.confidence ?? 0) < 0.85) {
    chatMsg("meta", "", `not run (confidence ${Math.round((a.confidence ?? 0) * 100)}%)`);
    return r;
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
    lastTurnExecuted = true;
  } else {
    chatMsg("meta", "", "↳ execution failed: " + JSON.stringify(result));
  }
  return r;
}

$("chatSend").addEventListener("click", sendChat);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

// ---- Voice + accessibility (Phase 12) -------------------------------------
// Voice is just another input into the SAME /chat pipeline - no second agent.
// Hands-free flow:  say "REACH"  ->  chime  ->  speak command  ->  REACH acts
//                   & speaks the result  ->  back to listening for "REACH".

const voiceBtn = $("voiceBtn");
const voiceStatus = $("voiceStatus");
const voiceTranscript = $("voiceTranscript");
const ttsToggle = $("ttsToggle");
const wakeToggle = $("wakeToggle");
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const LANG_TAG = { en: "en-US", kn: "kn-IN", hi: "hi-IN", ta: "ta-IN", te: "te-IN" };

// Wake word - lenient, since a false positive only costs a "Yes?" + timeout.
const WAKE = /\b(reach|reache|reech|rich|reece|preach|beach|each|hey reach|ok reach|okay reach)\b/i;

// Strict allowlists - unclear speech is NEVER a confirmation (Step 12.13).
const AFFIRM = /^\s*(yes|yeah|yep|yup|yidhu|sure|ok|okay|k|do it|go ahead|confirm|confirmed|proceed|pay|pay it|pay now|correct|please do|approved?|haudu|haan)\b/i;
const NEGATIVE = /^\s*(no|nope|nah|don'?t|do not|cancel|stop|illa|nahi)\b/i;

let recognition = null;   // command / confirmation recognizer (one-shot)
let wakeRec = null;       // wake-word recognizer (continuous)
let voiceState = "idle";
let listenTimer = null;
let awaitingConfirm = false;
let wakeArmed = false;     // wakeRec is currently running
let voiceGoal = null;          // the task the user asked for (carried across steps)
let voiceApprovedTask = false; // user already said "yes" to this task
let voiceSteps = 0;            // hard cap on autonomous continuation steps
let voiceBusy = false;         // a follow-up turn is in flight
let voiceVerifyRetries = 0;    // re-checks while a payment page is still settling

const STATE_ICON = {
  idle: "🎙", waiting: "👂", listening: "🔴", processing: "⏳", speaking: "🔊", error: "⚠"
};
const STATE_ARIA = {
  idle: "Start REACH", waiting: "Listening for “REACH”", listening: "Listening — click to stop",
  processing: "REACH is thinking", speaking: "REACH is speaking — click to stop", error: "Voice error — click to retry"
};

function setVoiceState(s, statusMsg) {
  voiceState = s;
  voiceBtn.dataset.state = s;
  voiceBtn.textContent = STATE_ICON[s] || STATE_ICON.idle;
  voiceBtn.setAttribute("aria-label", STATE_ARIA[s] || "Activate REACH");
  voiceBtn.title = STATE_ARIA[s] || "";
  if (statusMsg !== undefined) voiceStatus.textContent = statusMsg;
}

function speak(text, { onend } = {}) {
  if (!text || !window.speechSynthesis || !ttsToggle.checked) { onend && onend(); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = LANG_TAG[$("prefLanguage").value] || "en-US";
  setVoiceState("speaking", "REACH is responding.");
  const done = () => { if (voiceState === "speaking") setVoiceState("idle", ""); onend && onend(); };
  u.onend = done;
  u.onerror = done;
  window.speechSynthesis.speak(u);
}

// ---- wake-word listening (continuous) ----
function startWake() {
  if (!SR || !wakeToggle.checked || wakeArmed) return;
  if (voiceState === "listening" || voiceState === "processing" || voiceState === "speaking") return;
  try {
    wakeRec = new SR();
    wakeRec.lang = LANG_TAG[$("prefLanguage").value] || "en-US";
    wakeRec.continuous = true;
    wakeRec.interimResults = true;
    wakeRec.onstart = () => { wakeArmed = true; setVoiceState("waiting", "Listening — say “REACH”."); };
    wakeRec.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      text = text.trim();
      voiceTranscript.textContent = text;
      const m = text.match(WAKE);
      if (!m) return;
      stopWake();
      // "reach, open my bill" said in one breath -> use the trailing part now.
      const rest = text.slice(m.index + m[0].length).replace(/^[\s,.:;-]+/, "").trim();
      voiceTranscript.textContent = "";
      if (rest.split(/\s+/).length >= 2) {
        setVoiceState("processing", "REACH is processing your request.");
        voiceGoal = rest; voiceApprovedTask = false; voiceSteps = 0;
        submitMessage(rest).then(handleReply);
      } else {
        speak("Yes?", { onend: () => startListening(false) });
      }
    };
    wakeRec.onerror = (e) => {
      wakeArmed = false;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setVoiceState("error", "Microphone access isn't granted. Click “microphone setup”.");
        openMicSetup();
        return;
      }
      // no-speech / aborted / network -> quietly re-arm
      setTimeout(startWake, 600);
    };
    wakeRec.onend = () => {
      wakeArmed = false;
      if (wakeToggle.checked && voiceState === "waiting") setTimeout(startWake, 400);
    };
    wakeRec.start();
  } catch (e) {
    wakeArmed = false;
    setTimeout(startWake, 800);
  }
}

function stopWake() {
  wakeArmed = false;
  try { wakeRec && wakeRec.abort(); } catch (e) { /* noop */ }
  wakeRec = null;
}

// Return to the resting state: wake-listening if enabled, else idle.
function restVoice(msg) {
  if (wakeToggle.checked && SR) {
    setVoiceState("waiting", msg || "Listening — say “REACH”.");
    setTimeout(startWake, 300);
  } else {
    setVoiceState("idle", msg || "");
  }
}

function stopVoice() {
  clearTimeout(listenTimer);
  awaitingConfirm = false;
  try { recognition && recognition.abort(); } catch (e) { /* noop */ }
  try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* noop */ }
  restVoice("Stopped.");
}

// ---- command / confirmation listening (one-shot) ----
function startListening(forConfirm = false) {
  if (!SR) {
    setVoiceState("error", "Speech recognition isn't available in this browser.");
    return;
  }
  stopWake();
  awaitingConfirm = forConfirm;
  voiceTranscript.textContent = "";
  recognition = new SR();
  recognition.lang = LANG_TAG[$("prefLanguage").value] || "en-US";
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () =>
    setVoiceState("listening", forConfirm ? "Say “yes” or “no”." : "REACH is listening — say your request.");

  recognition.onresult = (e) => {
    let text = "";
    for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
    voiceTranscript.textContent = text.trim();
  };

  recognition.onerror = (e) => {
    clearTimeout(listenTimer);
    const blocked = e.error === "not-allowed" || e.error === "service-not-allowed";
    const msg = blocked
      ? "Microphone access isn't granted. Click “microphone setup” below to allow it in a tab (once)."
      : e.error === "no-speech"
      ? "I didn't hear anything."
      : "Voice error: " + e.error + ".";
    setVoiceState("error", msg);
    if (blocked) { openMicSetup(); return; }
    speak(msg, { onend: () => restVoice() });
  };

  recognition.onend = async () => {
    clearTimeout(listenTimer);
    const text = voiceTranscript.textContent.trim();
    if (!text) {
      speak("I didn't hear anything.", { onend: () => restVoice("I didn't hear anything.") });
      return;
    }

    if (awaitingConfirm) {
      awaitingConfirm = false;
      if (AFFIRM.test(text)) { voiceApprovedTask = true; return handleReply(await submitMessage("yes")); }
      if (NEGATIVE.test(text)) { voiceGoal = null; return handleReply(await submitMessage("no")); }
      // Ambiguous during a confirmation -> do NOT act (Step 12.13 / 12.34).
      speak("I didn't catch a clear yes or no, so I won't proceed. Please say yes or no.",
        { onend: () => startListening(true) });
      return;
    }

    setVoiceState("processing", "REACH is processing your request.");
    voiceGoal = text;          // remember the task so we can carry it across steps
    voiceApprovedTask = false;
    voiceSteps = 0;
    handleReply(await submitMessage(text));
  };

  try {
    recognition.start();
  } catch (e) {
    setVoiceState("error", "Couldn't start the microphone.");
    return;
  }
  listenTimer = setTimeout(() => { try { recognition.stop(); } catch (e) { /* noop */ } }, 9000);
}

async function handleReply(r) {
  if (!r) return restVoice();

  if (r.requires_confirmation) {
    // Same task the user already approved by voice -> proceed without re-asking.
    if (voiceApprovedTask) {
      speak(r.message, { onend: async () => { await handleReply(await submitMessage("yes")); } });
    } else {
      speak(r.message, { onend: () => startListening(true) });
    }
    return;
  }

  // A browser action just ran (navigate / pay / click). Speak progress, let the
  // page settle, then re-issue the SAME goal so a multi-step task finishes.
  // The re-issued turn also carries the verification of the step just done.
  if (lastTurnExecuted && !voiceBusy && voiceSteps < 5) {
    voiceBusy = true;
    voiceSteps += 1;
    speak(r.message || "Working on it.", {
      onend: () => setTimeout(async () => {
        setVoiceState("processing", voiceSteps > 1 ? "Continuing…" : "Working…");
        const v = await submitMessage(voiceGoal || "did it work?");
        voiceBusy = false;
        await handleReply(v);
      }, 3000)
    });
    return;
  }

  // Terminal — report the verified outcome of the task.
  const vs = r.verification_status;

  // If the page is still redirecting / opening Razorpay, that's not a real
  // AMBIGUOUS yet — wait and re-check (payment flows take ~10-20s).
  const stillSettling = vs && vs.status === "AMBIGUOUS" &&
    /loading|redirect|processing|opening|intermediate|not yet|in an? .*state|pending/i.test(
      (vs.reason || "") + " " + (vs.evidence || []).join(" "));
  if (stillSettling && !voiceBusy && voiceVerifyRetries < 4) {
    voiceVerifyRetries += 1;
    voiceBusy = true;
    setVoiceState("processing", "Waiting for the payment to finish…");
    setTimeout(async () => {
      const v = await submitMessage(voiceGoal || "did it work?");
      voiceBusy = false;
      await handleReply(v);
    }, 5000);
    return;
  }

  voiceGoal = null; voiceApprovedTask = false; voiceSteps = 0; voiceVerifyRetries = 0;
  if (vs && vs.status === "VERIFIED") {
    speak("Done. " + (vs.reason || ""), { onend: () => restVoice("Done.") });
  } else if (vs && vs.status === "AMBIGUOUS") {
    speak("I can't confirm the payment finished, so I won't retry it. " + (vs.reason || ""),
      { onend: () => restVoice("Couldn't confirm.") });
  } else {
    speak(r.message, { onend: () => restVoice("REACH finished.") });
  }
}

function openMicSetup() {
  try {
    chrome.tabs.create({ url: chrome.runtime.getURL("permission/permission.html") });
  } catch (e) {
    window.open(chrome.runtime.getURL("permission/permission.html"), "_blank");
  }
}
$("micSetup").addEventListener("click", (e) => { e.preventDefault(); openMicSetup(); });

voiceBtn.addEventListener("click", () => {
  if (voiceState === "listening" || voiceState === "speaking") stopVoice();
  else startListening(false);          // click = skip the wake word
});

wakeToggle.addEventListener("change", () => {
  if (wakeToggle.checked) startWake();
  else { stopWake(); setVoiceState("idle", "Wake word off — press the mic to talk."); }
});

// On open: Alt+R -> immediate command listen; otherwise arm the wake word.
storageLocal.get(["reach_voice_pending"], (s) => {
  if (!SR) return setVoiceState("idle", "Voice input isn't supported here — type below.");
  if (s.reach_voice_pending && Date.now() - s.reach_voice_pending < 5000) {
    storageLocal.remove("reach_voice_pending");
    startListening(false);
    return;
  }
  if (wakeToggle.checked) startWake();
  else setVoiceState("idle", "Press the mic or Alt+R and speak your request.");
});

