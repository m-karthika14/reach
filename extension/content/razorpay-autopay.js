// REACH — auto-complete Razorpay Checkout via the NETBANKING test flow.
//
// Netbanking test mode = no card, no OTP: pick a bank -> Razorpay opens a mock
// bank page -> click "Success" -> payment CAPTURED (shows in the dashboard).
//
// Runs in every frame on *.razorpay.com, only when Checkout was opened from the
// REACH demo (document.referrer).

(function () {
  "use strict";

  const FROM_REACH =
    /localhost:5500|127\.0\.0\.1:5500|reach-energy|reach-agent/i.test(document.referrer || "") ||
    /reach/i.test(location.hash);
  if (!FROM_REACH) return;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const body = () => (document.body && document.body.innerText) || "";
  const vis = (el) => el && el.offsetParent !== null && !el.disabled && el.getClientRects().length;

  function setValue(el, v) {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    el.focus();
    set ? set.call(el, v) : (el.value = v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function typeInto(re, value) {
    for (const el of document.querySelectorAll("input:not([type=hidden]), textarea")) {
      if (!vis(el)) continue;
      const hay = [el.name, el.id, el.placeholder, el.getAttribute("aria-label")]
        .filter(Boolean).join(" ").toLowerCase();
      if (re.test(hay)) { setValue(el, value); return true; }
    }
    return false;
  }
  function click(re, { maxLen = 60 } = {}) {
    const els = document.querySelectorAll(
      'button,[role="button"],a,li,.btn,input[type=submit],input[type=button],div[tabindex],label'
    );
    for (const el of els) {
      if (!vis(el)) continue;
      const t = (el.innerText || el.value || el.getAttribute("aria-label") || "").trim();
      if (t && t.length <= maxLen && re.test(t)) { el.click(); return t; }
    }
    return null;
  }
  function submitAnyForm() {
    for (const f of document.querySelectorAll("form")) {
      const btn = f.querySelector(
        'button, input[type=submit], [value="Success" i], [value*="success" i]'
      );
      if (btn && vis(btn)) { btn.click(); return true; }
      if (vis(f)) { try { f.submit(); return true; } catch (e) {} }
    }
    return false;
  }

  let done = false;

  async function drive() {
    for (let i = 0; i < 120 && !done; i++) {
      const b = body();

      // 1. Mock bank / gateway page -> click Success
      if (/success/i.test(b) && /(failure|fail)/i.test(b)) {
        if (click(/^success$/i) || click(/success/i) || submitAnyForm()) { done = true; break; }
      }
      if (/payment successful|thank you|redirecting|transaction successful|payment complete/i.test(b)) {
        done = true; break;
      }

      // 2. Failure / retry screen -> back to Netbanking
      if (/could not be completed|payment failed|not supported|declined|try (a )?different/i.test(b)) {
        click(/retry/i) || click(/net\s*banking/i) || click(/other/i);
        await sleep(500);
        continue;
      }

      // 3. Pick the Netbanking method
      click(/^net\s*banking$/i) || click(/net\s*banking/i);

      // 4. Choose a bank (prefer Bank of Baroda; else any test bank)
      typeInto(/bank|search/, "Baroda");
      click(/bank of baroda|baroda/i) ||
        click(/^(hdfc|sbi|state bank|icici|axis|kotak)\b/i) ||
        click(/^(all banks|other banks|more banks|select .*bank)$/i);

      // 5. Proceed to the bank page
      click(/^(pay\b|pay ₹|pay now|proceed|continue|confirm|make payment)/i);

      await sleep(650);
    }
    console.log("[REACH autopay] netbanking done=" + done);
  }

  const start = () => setTimeout(drive, 500);
  if (["complete", "interactive"].includes(document.readyState)) start();
  else window.addEventListener("DOMContentLoaded", start);
})();
