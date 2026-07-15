(() => {
  const player = document.querySelector("[data-vidsrc-player]");
  if (!player) return;

  const launch = player.querySelector("[data-player-launch]");
  const frame = player.querySelector("[data-player-frame]");
  const status = player.querySelector("[data-player-status]");
  const controls = player.querySelector("[data-player-controls]");
  const reload = player.querySelector("[data-player-reload]");
  const open = player.querySelector("[data-player-open]");
  const endpoint = player.dataset.sourceEndpoint;
  let sourceUrl = "";

  const setStatus = (message) => {
    status.textContent = message;
  };

  const showError = (message) => {
    launch.disabled = false;
    launch.hidden = false;
    frame.hidden = true;
    controls.hidden = true;
    setStatus(message);
  };

  const loadFrame = () => {
    if (!sourceUrl) return;
    frame.hidden = false;
    frame.src = sourceUrl;
    launch.hidden = true;
    controls.hidden = false;
    open.hidden = false;
    open.href = sourceUrl;
    setStatus("VidSrc is loading…");
  };

  launch.addEventListener("click", async () => {
    launch.disabled = true;
    setStatus("Preparing VidSrc…");
    try {
      const response = await fetch(endpoint, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("source unavailable");
      const payload = await response.json();
      sourceUrl = String(payload?.source?.url || "").trim();
      if (!sourceUrl) throw new Error("source unavailable");
      loadFrame();
    } catch (_error) {
      showError("VidSrc is unavailable for this movie. Try again later.");
    }
  });

  frame.addEventListener("load", () => {
    setStatus("VidSrc loaded. Playback controls are inside the player.");
  });

  reload.addEventListener("click", () => {
    if (!sourceUrl) return;
    frame.src = "about:blank";
    window.setTimeout(loadFrame, 0);
  });
})();
