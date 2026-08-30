const status = document.getElementById("status");

function set(cls, msg) {
  status.className = cls;
  status.textContent = msg;
}

document.getElementById("grant").addEventListener("click", async () => {
  set("", "Requesting microphone…");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    // Immediately stop the tracks - we only needed the permission grant.
    stream.getTracks().forEach((t) => t.stop());
    set("ok", "Microphone allowed. You can close this tab and use voice in the REACH popup.");
  } catch (e) {
    set(
      "err",
      "Permission was not granted (" + e.name + "). Open " +
        "chrome://settings/content/microphone, remove any block for this extension, and retry."
    );
  }
});

// Report current permission state on load, if the API is available.
navigator.permissions?.query({ name: "microphone" }).then((p) => {
  if (p.state === "granted") set("ok", "Microphone is already allowed. You can close this tab.");
  else if (p.state === "denied") set("err", "Microphone is currently blocked. Fix it in chrome://settings/content/microphone, then retry.");
}).catch(() => {});
