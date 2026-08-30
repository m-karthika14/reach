// REACH target resolver (Phase 1, forward-looking to Step 19 / Phase 6).
//
// The action engine can be told what to touch in two ways:
//   1. A raw CSS selector string          -> "#pay-button"
//   2. A semantic target descriptor       -> { role: "button", name: "Pay Bill" }
//
// Phase 1 mostly uses (1) for manual testing. (2) is what the agent will
// eventually emit so it never has to guess brittle CSS selectors.

(function () {
  "use strict";

  function implicitRole(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset", "image"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      return "textbox";
    }
    return null;
  }

  function accessibleName(el) {
    const aria = el.getAttribute("aria-label");
    if (aria && aria.trim()) return aria.trim();

    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const parts = labelledby
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.innerText || "")
        .join(" ")
        .trim();
      if (parts) return parts;
    }

    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
    }

    const wrappingLabel = el.closest("label");
    if (wrappingLabel && wrappingLabel.innerText.trim()) {
      return wrappingLabel.innerText.trim();
    }

    if (el.getAttribute("placeholder")) return el.getAttribute("placeholder").trim();
    if (el.getAttribute("title")) return el.getAttribute("title").trim();
    if (el.value && typeof el.value === "string" && el.type !== "text") return el.value.trim();

    return (el.innerText || "").trim();
  }

  function isVisible(el) {
    if (!el || !(el instanceof Element)) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  // Resolve a selector string or a { role, name, tag } descriptor to a single element.
  function resolveElement(spec) {
    if (spec == null) return null;
    if (typeof spec === "string") {
      try {
        return document.querySelector(spec);
      } catch (e) {
        return null;
      }
    }

    const { role, name, tag } = spec;
    let candidates = Array.from(document.querySelectorAll(tag || "*"));

    if (role) {
      candidates = candidates.filter(
        (el) => (el.getAttribute("role") || implicitRole(el)) === role
      );
    }

    if (name) {
      const needle = String(name).trim().toLowerCase();
      const exact = candidates.filter(
        (el) => accessibleName(el).toLowerCase() === needle
      );
      const partial = candidates.filter((el) =>
        accessibleName(el).toLowerCase().includes(needle)
      );
      candidates = exact.length ? exact : partial;
    }

    const visible = candidates.filter(isVisible);
    return (visible[0] || candidates[0]) || null;
  }

  // Expose on window so actions.js / content.js (same content-script world) can use it.
  window.REACH = window.REACH || {};
  window.REACH.resolveElement = resolveElement;
  window.REACH.accessibleName = accessibleName;
  window.REACH.implicitRole = implicitRole;
  window.REACH.isVisible = isVisible;
})();
