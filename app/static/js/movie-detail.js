(() => {
  const player = document.querySelector("[data-movie-player]");
  if (!player) return;

  const source = player.querySelector("[data-player-source]");
  const launch = player.querySelector("[data-player-launch]");
  const launchTitle = player.querySelector("[data-player-launch-title]");
  const badge = player.querySelector("[data-player-badge]");
  const frame = player.querySelector("[data-player-frame]");
  const video = player.querySelector("[data-player-video]");
  const status = player.querySelector("[data-player-status]");
  const controls = player.querySelector("[data-player-controls]");
  const reload = player.querySelector("[data-player-reload]");
  const open = player.querySelector("[data-player-open]");
  const stop = player.querySelector("[data-player-stop]");
  const subtitleSelect = player.querySelector("[data-subtitle-select]");
  const subtitleStatus = player.querySelector("[data-subtitle-status]");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let sourceUrl = "";
  let localSession = null;
  let pollTimer = 0;
  let activeKind = "";
  let subtitleOptionsLoaded = false;
  let subtitleRequest = null;

  const selectedKind = () => source.selectedOptions[0]?.dataset.kind || "vidsrc";
  const setStatus = (message) => { status.textContent = message; };
  const setSubtitleStatus = (message) => {
    if (subtitleStatus) subtitleStatus.textContent = message;
  };
  const formatSpeed = (bytes) => {
    if (!bytes) return "";
    const megabytes = bytes / 1024 / 1024;
    return `${megabytes.toFixed(megabytes >= 10 ? 0 : 1)} MB/s`;
  };

  const clearPoll = () => {
    window.clearTimeout(pollTimer);
    pollTimer = 0;
  };

  const clearSubtitleTrack = () => {
    video.querySelectorAll("track").forEach((track) => track.remove());
    Array.from(video.textTracks || []).forEach((track) => { track.mode = "disabled"; });
  };

  const applySelectedSubtitle = () => {
    if (!subtitleSelect || selectedKind() !== "local") return;
    clearSubtitleTrack();
    const option = subtitleSelect.selectedOptions[0];
    if (!option || option.value === "off" || option.value === "auto") {
      setSubtitleStatus(option?.value === "off"
        ? "Subtitles are off."
        : "Arabic will be selected first when Local starts.");
      return;
    }
    const track = document.createElement("track");
    track.kind = "subtitles";
    track.label = option.dataset.languageName || "Subtitles";
    track.srclang = option.dataset.language || "ar";
    track.src = option.value;
    track.default = true;
    setSubtitleStatus(`Loading ${track.label} subtitles…`);
    track.addEventListener("load", () => {
      Array.from(video.textTracks).forEach((item) => {
        item.mode = item === track.track ? "showing" : "disabled";
      });
      setSubtitleStatus(`${track.label} subtitles are ready.`);
    });
    track.addEventListener("error", () => {
      setSubtitleStatus("That subtitle could not be loaded. Try another release.");
    });
    video.append(track);
  };

  const loadSubtitleOptions = () => {
    if (!subtitleSelect || !player.dataset.subtitleEndpoint) return Promise.resolve();
    if (subtitleOptionsLoaded) {
      applySelectedSubtitle();
      return Promise.resolve();
    }
    if (subtitleRequest) return subtitleRequest;
    subtitleSelect.disabled = true;
    setSubtitleStatus("Finding Arabic and English subtitles…");
    subtitleRequest = fetch(player.dataset.subtitleEndpoint, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.error?.message || "Subtitle search is unavailable");
        }
        const items = Array.isArray(payload.items) ? payload.items : [];
        subtitleSelect.replaceChildren();
        items.forEach((item) => {
          const option = document.createElement("option");
          option.value = item.track_url;
          option.dataset.language = item.language;
          option.dataset.languageName = item.language_name;
          option.textContent = `${item.language_name} · ${item.label}${item.hearing_impaired ? " · HI" : ""}`;
          subtitleSelect.append(option);
        });
        const off = document.createElement("option");
        off.value = "off";
        off.textContent = "Off";
        subtitleSelect.append(off);
        subtitleOptionsLoaded = true;
        if (items.length) {
          subtitleSelect.selectedIndex = 0;
          applySelectedSubtitle();
        } else {
          subtitleSelect.value = "off";
          setSubtitleStatus("No Arabic or English subtitles were found.");
        }
      })
      .catch((error) => {
        subtitleSelect.replaceChildren();
        const off = document.createElement("option");
        off.value = "off";
        off.textContent = "Off";
        subtitleSelect.append(off);
        setSubtitleStatus(String(error?.message || "Subtitle search is unavailable."));
      })
      .finally(() => {
        subtitleRequest = null;
        subtitleSelect.disabled = selectedKind() !== "local";
      });
    return subtitleRequest;
  };

  const stopLocal = async ({ silent = false } = {}) => {
    clearPoll();
    clearSubtitleTrack();
    video.pause();
    video.removeAttribute("src");
    video.load();
    if (!localSession?.stopUrl) {
      localSession = null;
      return;
    }
    const stopUrl = localSession.stopUrl;
    localSession = null;
    try {
      await fetch(stopUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, Accept: "application/json" },
        keepalive: true,
      });
    } catch (_error) {
      if (!silent) setStatus("The player stopped, but its cache cleanup could not be confirmed.");
    }
  };

  const resetViewport = () => {
    sourceUrl = "";
    frame.src = "about:blank";
    frame.hidden = true;
    video.hidden = true;
    launch.hidden = false;
    launch.disabled = false;
    controls.hidden = true;
    open.hidden = true;
    stop.hidden = true;
  };

  const syncSourceUi = () => {
    const kind = selectedKind();
    badge.textContent = kind === "vidsrc" ? "VidSrc" : "Local";
    launchTitle.textContent = kind === "vidsrc" ? "Play with VidSrc" : "Start local player";
    setStatus(kind === "vidsrc"
      ? "Ready. No external connection has been made."
      : "Ready. The magnet will start only after you press play.");
    if (subtitleSelect) {
      subtitleSelect.disabled = kind !== "local" || Boolean(subtitleRequest);
      if (kind === "vidsrc") {
        clearSubtitleTrack();
        setSubtitleStatus("Use VidSrc captions or switch to Local for Dragon subtitles.");
      } else if (!subtitleOptionsLoaded) {
        setSubtitleStatus("Arabic will be selected first when Local starts.");
      }
    }
  };

  const showError = (message) => {
    clearPoll();
    launch.disabled = false;
    launch.hidden = false;
    frame.hidden = true;
    video.hidden = true;
    controls.hidden = true;
    setStatus(message);
  };

  const loadVidSrc = () => {
    frame.hidden = false;
    frame.src = sourceUrl;
    launch.hidden = true;
    controls.hidden = false;
    reload.hidden = false;
    open.hidden = false;
    open.href = sourceUrl;
    stop.hidden = true;
    setStatus("VidSrc is loading…");
  };

  const renderLocalStatus = (session) => {
    const details = [];
    if (session.file_name) details.push(session.file_name);
    if (session.peers) details.push(`${session.peers} peer${session.peers === 1 ? "" : "s"}`);
    if (session.download_speed) details.push(formatSpeed(session.download_speed));
    const progress = session.buffer_percent ? ` ${session.buffer_percent}% cached.` : "";
    setStatus(`${session.message || "Preparing local stream…"}${progress}${details.length ? ` · ${details.join(" · ")}` : ""}`);
  };

  const pollLocal = async () => {
    if (!localSession) return;
    try {
      const response = await fetch(localSession.statusUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || "Local player unavailable");
      renderLocalStatus(payload.session || {});
      if (payload.session?.state === "failed") {
        throw new Error(payload.session.message || "Local player failed");
      }
      if (payload.session?.state === "ready") {
        if (!video.hasAttribute("src")) {
          video.src = localSession.streamUrl;
          video.hidden = false;
          video.load();
          video.play().catch(() => {});
        }
      }
      pollTimer = window.setTimeout(pollLocal, payload.session?.complete ? 5000 : 1000);
    } catch (error) {
      showError(String(error?.message || "Local player unavailable"));
    }
  };

  const startLocal = async () => {
    const response = await fetch(player.dataset.localEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({ source_id: source.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error?.message || "Local player unavailable");
    localSession = {
      statusUrl: payload.status_url,
      streamUrl: payload.stream_url,
      stopUrl: payload.stop_url,
    };
    launch.hidden = true;
    video.hidden = false;
    controls.hidden = false;
    reload.hidden = true;
    open.hidden = true;
    stop.hidden = false;
    renderLocalStatus(payload.session || {});
    void loadSubtitleOptions();
    pollLocal();
  };

  source.addEventListener("change", async () => {
    await stopLocal({ silent: true });
    resetViewport();
    syncSourceUi();
  });

  launch.addEventListener("click", async () => {
    launch.disabled = true;
    activeKind = selectedKind();
    try {
      if (activeKind === "local") {
        setStatus("Starting the local WebTorrent runtime…");
        await startLocal();
        return;
      }
      setStatus("Preparing VidSrc…");
      const response = await fetch(player.dataset.vidsrcEndpoint, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || "source unavailable");
      sourceUrl = String(payload?.source?.url || "").trim();
      if (!sourceUrl) throw new Error("source unavailable");
      loadVidSrc();
    } catch (error) {
      showError(String(error?.message || "Playback is unavailable for this movie."));
    }
  });

  frame.addEventListener("load", () => {
    if (activeKind === "vidsrc" && frame.src !== "about:blank") {
      setStatus("VidSrc loaded. Playback controls are inside the player.");
    }
  });

  reload.addEventListener("click", () => {
    if (!sourceUrl) return;
    frame.src = "about:blank";
    window.setTimeout(loadVidSrc, 0);
  });
  stop.addEventListener("click", async () => {
    await stopLocal();
    resetViewport();
    syncSourceUi();
  });
  subtitleSelect?.addEventListener("change", applySelectedSubtitle);
  window.addEventListener("pagehide", () => { stopLocal({ silent: true }); });
  syncSourceUi();
})();
