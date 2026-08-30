/* ===== REACH Energy demo portal — shared logic ===== */

const BILL = { amount: 1240, consumer: "REACH-2026-001", due: "30 Aug 2026", usage: "312 kWh", prev: 1180 };

// Backend base URL (Cloud Run or localhost). Overridable via ?backend= or the demo panel.
function backendUrl() {
  const q = new URLSearchParams(location.search).get("backend");
  if (q) localStorage.setItem("reach_demo_backend", q);
  return (localStorage.getItem("reach_demo_backend") || "http://127.0.0.1:8080").replace(/\/$/, "");
}
function setBackend(v) { localStorage.setItem("reach_demo_backend", (v || "").replace(/\/$/, "")); }

// Scenario: normal | vision | conflict | ambiguous | success
function scenario() {
  const q = new URLSearchParams(location.search).get("scenario");
  if (q) localStorage.setItem("reach_scenario", q);
  return localStorage.getItem("reach_scenario") || "normal";
}
function setScenario(v) { localStorage.setItem("reach_scenario", v); }

const money = (r) => "₹" + Number(r).toLocaleString("en-IN");

// ---------- REACH activity / reasoning panel ----------
const Activity = (() => {
  let host = null;
  const seq = [
    ["observe", "Page observed", "DOM + ARIA + screenshot captured"],
    ["memory", "Memory retrieved", "page & correction memory for this site"],
    ["structure", "Structure analysed", ""],
    ["vision", "Vision analysed", ""],
    ["reconcile", "Reconciliation", ""],
    ["action", "Action selected", ""],
    ["execute", "Executed in browser", ""],
    ["verify", "Result verified", ""],
  ];
  function mount(el) {
    host = el;
    host.innerHTML = seq.map(([id, lbl, sub]) =>
      `<div class="step pending" data-id="${id}">
         <span class="dot">•</span>
         <span class="lbl">${lbl}${sub ? `<br><span class="sub">${sub}</span>` : ""}</span>
       </div>`).join("");
  }
  function set(id, state, sub) {
    if (!host) return;
    const row = host.querySelector(`.step[data-id="${id}"]`);
    if (!row) return;
    row.className = "step " + state;
    row.querySelector(".dot").textContent =
      state === "ok" ? "✓" : state === "warn" ? "!" : state === "block" ? "✕" : "•";
    if (sub !== undefined) {
      const l = row.querySelector(".lbl");
      const base = l.childNodes[0].textContent;
      l.innerHTML = `${base}${sub ? `<br><span class="sub">${sub}</span>` : ""}`;
    }
  }
  function reset() { if (host) seq.forEach(([id]) => set(id, "pending")); }
  return { mount, set, reset };
})();

// The content script dispatches these when REACH observes / acts on the page.
window.addEventListener("reach:activity", (e) => {
  const d = e.detail || {};
  if (d.step === "observe") { Activity.reset(); Activity.set("observe", "ok"); }
  if (d.step === "act") {
    Activity.set("action", "ok", `${d.action} ${d.target || ""}`.trim());
    Activity.set("execute", "ok");
  }
});

// Demo-mode simulation of the pipeline for a given scenario (labelled Demo Mode).
function simulatePipeline(sc) {
  Activity.reset();
  const t = (fn, ms) => setTimeout(fn, ms);
  Activity.set("observe", "ok");
  t(() => Activity.set("memory", "ok",
      sc === "success" ? "known: payment icon (verified)" : "no prior knowledge"), 250);
  t(() => {
    if (sc === "conflict") Activity.set("structure", "ok", "label: “Cancel”");
    else if (sc === "normal") Activity.set("structure", "ok", "clear payment control");
    else Activity.set("structure", "warn", "icon-only — meaning unclear");
  }, 550);
  t(() => {
    if (sc === "normal") { Activity.set("vision", "pending"); }
    else Activity.set("vision", "ok", sc === "conflict" ? "💳 “Pay Now”" : "💳 payment");
  }, 900);
  t(() => {
    if (sc === "conflict") {
      Activity.set("reconcile", "block", "CONFLICT — structure ≠ vision");
      Activity.set("action", "block", "blocked — not activated");
      setStatus("err", "⚠️ REACH found conflicting information about this button, so it won't activate it.");
    } else {
      Activity.set("reconcile", "ok", "AGREE");
      Activity.set("action", "ok", "click payment");
    }
  }, 1300);
}

// ---------- status line ----------
function setStatus(kind, msg) {
  const el = document.getElementById("status");
  if (!el) return;
  el.className = "status " + (kind || "");
  el.textContent = msg;
}

// ---------- payment ----------
// Hands-free (blind-user friendly): create a REAL Razorpay order via the
// Razorpay API - it appears in the Razorpay dashboard under Orders - then
// complete it on the backend. No checkout modal, no card/OTP, nothing to click.
async function payAuto(amountRupees, consumer) {
  setStatus("", "Paying " + money(amountRupees) + " through Razorpay…");
  let order;
  try {
    const r = await fetch(backendUrl() + "/payments/create-order", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: amountRupees, consumer, note: "Electricity bill" })
    });
    order = await r.json();
  } catch (e) {
    return setStatus("err", "Couldn't reach the payment service. Is the backend running?");
  }

  if (order.mock) {
    return setStatus("err",
      "This backend has NO Razorpay keys — set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET and " +
      "point the Backend field at it. (Currently pointed at a mock backend.)");
  }

  try {
    const c = await fetch(backendUrl() + "/payments/test-capture", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: order.order_id })
    });
    const v = await c.json();
    sessionStorage.setItem("reach_receipt", JSON.stringify(v));
    setStatus("ok", "Payment complete — opening your receipt…");
    setTimeout(() => (location.href = "success.html?order_id=" + encodeURIComponent(order.order_id)), 500);
  } catch (e) {
    setStatus("err", "Payment could not be completed.");
  }
}

const payWithRazorpay = payAuto;

async function finishPayment(orderId, paymentId, signature) {
  setStatus("", "Verifying payment…");
  let v;
  try {
    const r = await fetch(backendUrl() + "/payments/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        razorpay_order_id: orderId, razorpay_payment_id: paymentId, razorpay_signature: signature
      })
    });
    v = await r.json();
  } catch (e) {
    setStatus("err", "Could not verify the payment.");
    return;
  }
  sessionStorage.setItem("reach_receipt", JSON.stringify(v));
  location.href = "success.html?order_id=" + encodeURIComponent(orderId);
}

// ---------- shared chrome (topbar) ----------
function topbar(active) {
  const nav = [["index.html", "Dashboard"], ["bill.html", "Bill"], ["payment.html", "Pay"]];
  return `<div class="topbar">
    <div class="brand"><span class="spark">⚡</span> REACH Energy</div>
    <nav>${nav.map(([h, t]) =>
      `<a href="${h}"${h === active ? ' aria-current="page"' : ""}>${t}</a>`).join("")}</nav>
    <span class="spacer"></span>
    <button class="icon-btn" aria-label="button">🔔</button>
    <button class="icon-btn" aria-label="button">👤</button>
  </div>`;
}

function demoControls() {
  const sc = scenario();
  const opts = [
    ["normal", "Normal — clear payment control"],
    ["vision", "Vision required — icon only"],
    ["conflict", "Structure / Vision conflict"],
    ["ambiguous", "Payment ambiguous (stuck, no receipt)"],
  ];
  return `<div class="card side demo-ctl">
    <h2>Demo controls <span class="tag-demo">demo mode</span></h2>
    ${opts.map(([v, l]) =>
      `<label><input type="radio" name="sc" value="${v}" ${v === sc ? "checked" : ""}> ${l}</label>`).join("")}
    <div class="field">
      <span style="font-size:12px;color:var(--muted)">Backend</span>
      <input id="backendField" value="${backendUrl()}" />
    </div>
    <div class="hint" id="payMode">checking payment mode…</div>
    <div class="hint">Scenario changes which elements the payment page exposes to REACH.</div>
  </div>`;
}

function wireDemoControls() {
  document.querySelectorAll('input[name="sc"]').forEach((r) =>
    r.addEventListener("change", () => { setScenario(r.value); location.reload(); }));
  const bf = document.getElementById("backendField");
  if (bf) bf.addEventListener("change", () => setBackend(bf.value.trim()));
  // Show whether payments are live or mock.
  fetch(backendUrl() + "/").then((r) => r.json()).then((info) => {
    const el = document.getElementById("payMode");
    if (!el) return;
    const real = info.payments_mode === "real";
    el.textContent = real ? "Razorpay: LIVE (test)" : "Razorpay: MOCK — keys not set";
    el.style.color = real ? "var(--ok)" : "var(--danger)";
  }).catch(() => {});
}
