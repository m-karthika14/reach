// REACH action executor (Phase 1).
//
// Supported actions: CLICK, TYPE, SELECT, SCROLL, BACK.
// Each function returns a plain result object: { success, action, ... }.
//
// Every "element" action accepts either:
//   selector  -> a CSS selector string
//   target    -> a { role, name, tag } descriptor (resolved via window.REACH.resolveElement)

(function () {
  "use strict";

  function resolve(message) {
    const spec = message.target != null ? message.target : message.selector;
    const el = window.REACH?.resolveElement
      ? window.REACH.resolveElement(spec)
      : (typeof spec === "string" ? document.querySelector(spec) : null);
    return { el, spec };
  }

  function clickElement(message) {
    const { el, spec } = resolve(message);
    if (!el) return { success: false, action: "CLICK", error: "Element not found", spec };

    el.scrollIntoView({ block: "center", inline: "center" });
    el.click();

    return { success: true, action: "CLICK", spec, resolvedText: (el.innerText || "").trim().slice(0, 80) };
  }

  function typeIntoElement(message) {
    const { el, spec } = resolve(message);
    if (!el) return { success: false, action: "TYPE", error: "Element not found", spec };
    if (!("value" in el)) {
      return { success: false, action: "TYPE", error: "Element is not typable", spec };
    }

    const value = message.value ?? "";
    el.focus();

    // Use the native setter so frameworks (React etc.) notice the change.
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, value);
    else el.value = value;

    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));

    return { success: true, action: "TYPE", spec, value };
  }

  function selectOption(message) {
    const { el, spec } = resolve(message);
    if (!el || el.tagName !== "SELECT") {
      return { success: false, action: "SELECT", error: "Select element not found", spec };
    }

    const value = message.value;
    const byValue = Array.from(el.options).find((o) => o.value === value);
    const byLabel = Array.from(el.options).find(
      (o) => o.text.trim().toLowerCase() === String(value).trim().toLowerCase()
    );
    const chosen = byValue || byLabel;
    if (!chosen) {
      return { success: false, action: "SELECT", error: `No option matching "${value}"`, spec };
    }

    el.value = chosen.value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));

    return { success: true, action: "SELECT", spec, value: chosen.value, label: chosen.text.trim() };
  }

  function scrollPage(message) {
    const amount = Number.isFinite(message.amount) ? message.amount : 500;

    if (message.selector || message.target) {
      const { el, spec } = resolve(message);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        return { success: true, action: "SCROLL", mode: "element", spec };
      }
    }

    window.scrollBy({ top: amount, behavior: "smooth" });
    return {
      success: true,
      action: "SCROLL",
      mode: "page",
      amount,
      scrollY: window.scrollY
    };
  }

  function goBack() {
    window.history.back();
    return { success: true, action: "BACK" };
  }

  window.REACH = window.REACH || {};
  window.REACH.actions = {
    CLICK: clickElement,
    TYPE: typeIntoElement,
    SELECT: selectOption,
    SCROLL: scrollPage,
    BACK: goBack
  };
})();
