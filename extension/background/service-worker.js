// REACH background service worker (Phase 1).
// Kept intentionally thin - the cloud/agent logic arrives in Phase 2+.
// Its only job today is capturing a screenshot of the visible tab, because
// chrome.tabs.captureVisibleTab is not available from a content script.

console.log("REACH service worker started");

// Phase 12: Alt+R -> open the popup and tell it to start listening.
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "activate-voice") return;
  await chrome.storage.local.set({ reach_voice_pending: Date.now() });
  try {
    await chrome.action.openPopup(); // Chrome 127+
  } catch (e) {
    // Older Chrome: the flag is set; the user opens the popup from the toolbar
    // and it auto-starts listening.
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "CAPTURE_SCREENSHOT") {
    chrome.tabs.captureVisibleTab(
      message.windowId ?? chrome.windows.WINDOW_ID_CURRENT,
      { format: "png" }
    )
      .then((dataUrl) => {
        sendResponse({ success: true, dataUrl });
      })
      .catch((error) => {
        sendResponse({ success: false, error: String(error) });
      });

    // Keep the message channel open for the async response.
    return true;
  }
});
