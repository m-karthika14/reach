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

// ---------- payments ----------
// Autonomous path: create a real test order, auto-capture it, show the receipt.
// No card UI - so REACH can pay hands-free and the Verification Agent still gets
// a real transaction id + receipt off success.html.
async function payAuto(amountRupees, consumer) {
  setStatus("", "Paying your electricity bill…");
  let order;
  try {
    const r = await fetch(backendUrl() + "/payments/create-order", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: amountRupees, consumer, note: "Electricity bill" })
    });
    order = await r.json();
  } catch (e) {
    setStatus("err", "Couldn't reach the payment service. Is the backend running?");
    return;
  }
  try {
    const c = await fetch(backendUrl() + "/payments/test-capture", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: order.order_id })
    });
    const v = await c.json();
    sessionStorage.setItem("reach_receipt", JSON.stringify(v));
    setStatus("ok", "Payment successful — redirecting to your receipt…");
    setTimeout(() => (location.href = "success.html?order_id=" + encodeURIComponent(order.order_id)), 500);
  } catch (e) {
    setStatus("err", "Payment could not be completed.");
  }
}

async function payWithRazorpay(amountRupees, consumer) {
  setStatus("", "Creating secure order…");
  let order;
  try {
    const r = await fetch(backendUrl() + "/payments/create-order", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: amountRupees, consumer, note: "Electricity bill" })
    });
    order = await r.json();
  } catch (e) {
    setStatus("err", "Couldn't reach the payment service. Is the backend running?");
    return;
  }

  // Mock mode (no Razorpay keys) or checkout.js missing -> synthesise a paid receipt.
  if (order.mock || !window.Razorpay) {
    return finishPayment(order.order_id, "pay_" + Math.random().toString(36).slice(2, 16), "");
  }

  const rzp = new window.Razorpay({
    key: order.key_id,
    amount: order.amount,
    currency: order.currency,
    name: "REACH Energy",
    description: "Electricity bill — " + consumer,
    order_id: order.order_id,
    theme: { color: "#6d28d9" },
    handler: (res) => finishPayment(res.razorpay_order_id, res.razorpay_payment_id, res.razorpay_signature),
    modal: { ondismiss: () => setStatus("warn", "Payment window closed — nothing was charged.") }
  });
  rzp.on("payment.failed", () => setStatus("err", "Payment failed. No amount was charged."));
  rzp.open();
  setStatus("", "Opening secure checkout…");
}

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
    ["ambiguous", "Payment ambiguous (no receipt)"],
    ["success", "Instant success (skip checkout)"],
  ];
  return `<div class="card side demo-ctl">
    <h2>Demo controls <span class="tag-demo">demo mode</span></h2>
    ${opts.map(([v, l]) =>
      `<label><input type="radio" name="sc" value="${v}" ${v === sc ? "checked" : ""}> ${l}</label>`).join("")}
    <div class="field">
      <span style="font-size:12px;color:var(--muted)">Backend</span>
      <input id="backendField" value="${backendUrl()}" />
    </div>
    <div class="hint">Scenario changes which elements the payment page exposes to REACH.</div>
  </div>`;
}

function wireDemoControls() {
  document.querySelectorAll('input[name="sc"]').forEach((r) =>
    r.addEventListener("change", () => { setScenario(r.value); location.reload(); }));
  const bf = document.getElementById("backendField");
  if (bf) bf.addEventListener("change", () => setBackend(bf.value.trim()));
}
