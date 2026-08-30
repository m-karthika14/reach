// REACH content script (Phase 1).
//
// Responsibilities:
//   1. Observe the page  -> getPageContext()  (URL, title, text, buttons, links,
//      inputs, selects, textareas, headings, images, ARIA roles/labels)
//   2. Route action requests from the popup to window.REACH.actions.*

(function () {
  "use strict";

  const accessibleName = window.REACH?.accessibleName || ((el) => (el.innerText || "").trim());
  const isVisible = window.REACH?.isVisible || (() => true);

  function getVisibleText() {
    return (document.body?.innerText || "").trim();
  }

  function cssPath(el) {
    // Best-effort stable-ish selector for a given element (used so the popup can
    // replay an action against something it saw during inspection).
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      let part = node.tagName.toLowerCase();
      if (node.classList.length) {
        part += "." + Array.from(node.classList).map((c) => CSS.escape(c)).join(".");
      }
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(
          (c) => c.tagName === node.tagName
        );
        if (siblings.length > 1) {
          part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
        }
      }
      parts.unshift(part);
      if (node.id) break;
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  function getPageContext() {
    const buttons = Array.from(
      document.querySelectorAll('button, input[type="button"], input[type="submit"], [role="button"]')
    ).map((el, index) => ({
      index,
      text: (el.innerText || el.value || "").trim(),
      ariaLabel: el.getAttribute("aria-label"),
      accessibleName: accessibleName(el),
      role: el.getAttribute("role") || "button",
      id: el.id || null,
      selector: cssPath(el),
      disabled: el.disabled === true || el.getAttribute("aria-disabled") === "true",
      visible: isVisible(el)
    }));

    const links = Array.from(document.querySelectorAll("a[href]")).map((el, index) => ({
      index,
      text: (el.innerText || "").trim(),
      href: el.href,
      ariaLabel: el.getAttribute("aria-label"),
      accessibleName: accessibleName(el),
      selector: cssPath(el),
      visible: isVisible(el)
    }));

    const inputs = Array.from(
      document.querySelectorAll('input:not([type="button"]):not([type="submit"]):not([type="reset"]), textarea, select')
    ).map((el, index) => ({
      index,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type"),
      name: el.getAttribute("name"),
      id: el.id || null,
      selector: cssPath(el),
      placeholder: el.getAttribute("placeholder"),
      ariaLabel: el.getAttribute("aria-label"),
      accessibleName: accessibleName(el),
      role: el.getAttribute("role") || window.REACH?.implicitRole?.(el) || null,
      required: el.required === true,
      value: typeof el.value === "string" ? el.value : "",
      options:
        el.tagName === "SELECT"
          ? Array.from(el.options).map((o) => ({ value: o.value, label: o.text.trim() }))
          : undefined,
      visible: isVisible(el)
    }));

    const headings = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6")).map((el) => ({
      level: Number(el.tagName[1]),
      text: (el.innerText || "").trim()
    }));

    const images = Array.from(document.querySelectorAll("img")).slice(0, 100).map((el, index) => ({
      index,
      alt: el.getAttribute("alt"),
      ariaLabel: el.getAttribute("aria-label"),
      src: el.currentSrc || el.src,
      visible: isVisible(el)
    }));

    const ariaRoles = Array.from(document.querySelectorAll("[role]")).reduce((acc, el) => {
      const role = el.getAttribute("role");
      acc[role] = (acc[role] || 0) + 1;
      return acc;
    }, {});

    return {
      url: window.location.href,
      title: document.title,
      visibleText: getVisibleText(),
      counts: {
        buttons: buttons.length,
        links: links.length,
        inputs: inputs.length,
        headings: headings.length,
        images: images.length
      },
      buttons,
      links,
      inputs,
      headings,
      images,
      ariaRoles,
      scroll: {
        y: window.scrollY,
        maxY: Math.max(0, document.documentElement.scrollHeight - window.innerHeight)
      },
      capturedAt: new Date().toISOString()
    };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message.type !== "string") return;

    if (message.type === "PING") {
      sendResponse({ ok: true, url: window.location.href });
      return;
    }

    if (message.type === "GET_PAGE_CONTEXT") {
      sendResponse(getPageContext());
      return;
    }

    if (message.type === "EXECUTE_ACTION") {
      const handler = window.REACH?.actions?.[message.action];
      let result;
      if (!handler) {
        result = { success: false, error: `Unknown action: ${message.action}` };
      } else {
        try {
          result = handler(message);
        } catch (error) {
          result = { success: false, action: message.action, error: String(error) };
        }
      }
      sendResponse(result);
      return;
    }
  });

  console.log("REACH content script ready:", window.location.href);
})();
