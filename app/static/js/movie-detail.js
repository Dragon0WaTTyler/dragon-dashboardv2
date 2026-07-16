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
  const subtitleStatus = player.querySelector("[data-subtitle-status]");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let sourceUrl = "";
  let localSession = null;
  let pollTimer = 0;
  let activeKind = "";
  let subtitleOptions = null;
  let subtitleRequest = null;
  let watchReported = false;

  const selectedKind = () => source.selectedOptions[0]?.dataset.kind || "vidsrc";
  const setStatus = (message) => { status.textContent = message; };
  const setPlayerState = (state, message = "") => {
    player.dataset.playbackState = state;
    if (activeKind === "local") {
      badge.textContent = `Local · ${state.charAt(0).toUpperCase()}${state.slice(1)}`;
    }
    if (message) setStatus(message);
  };
  const setSubtitleStatus = (message) => {
    if (subtitleStatus) subtitleStatus.textContent = message;
  };
  const formatSpeed = (bytes) => {
    if (!bytes) return "";
    const megabytes = bytes / 1024 / 1024;
    return `${megabytes.toFixed(megabytes >= 10 ? 0 : 1)} MB/s`;
  };
  const formatBytes = (bytes) => {
    if (!bytes) return "0 MB";
    const megabytes = bytes / 1024 / 1024;
    return `${megabytes.toFixed(megabytes >= 100 ? 0 : 1)} MB`;
  };

  const reportWatchStarted = async () => {
    if (watchReported || !player.dataset.watchEndpoint) return;
    watchReported = true;
    try {
      const response = await fetch(player.dataset.watchEndpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, Accept: "application/json" },
      });
      if (!response.ok) watchReported = false;
    } catch (_error) {
      watchReported = false;
    }
  };

  const clearPoll = () => {
    window.clearTimeout(pollTimer);
    pollTimer = 0;
  };

  const clearSubtitleTracks = () => {
    video.querySelectorAll("track").forEach((track) => track.remove());
    Array.from(video.textTracks || []).forEach((track) => { track.mode = "disabled"; });
  };

  const mountSubtitleTracks = (items) => {
    clearSubtitleTracks();
    if (!items.length) {
      setSubtitleStatus("No Arabic or English subtitles were found.");
      return;
    }
    items.forEach((item, index) => {
      const track = document.createElement("track");
      track.kind = "subtitles";
      track.label = `${item.language_name} · ${item.label}${item.hearing_impaired ? " · HI" : ""}`;
      track.srclang = item.language;
      track.src = item.track_url;
      track.default = index === 0;
      track.addEventListener("load", () => {
        if (index !== 0) return;
        Array.from(video.textTracks).forEach((candidate) => {
          candidate.mode = candidate === track.track ? "showing" : "disabled";
        });
        setSubtitleStatus(`${track.label} subtitles are ready. Use the captions menu inside the player to switch or turn them off.`);
      });
      track.addEventListener("error", () => {
        if (index === 0) {
          setSubtitleStatus("The default subtitle could not be loaded. Try another track from the captions menu inside the player.");
        }
      });
      video.append(track);
    });
    setSubtitleStatus(`${items.length} subtitle option${items.length === 1 ? " is" : "s are"} available from the captions menu inside the player.`);
  };

  const loadSubtitleOptions = () => {
    if (!subtitleStatus || !player.dataset.subtitleEndpoint) return Promise.resolve();
    if (subtitleOptions !== null) {
      mountSubtitleTracks(subtitleOptions);
      return Promise.resolve();
    }
    if (subtitleRequest) return subtitleRequest;
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
        subtitleOptions = items;
        mountSubtitleTracks(items);
      })
      .catch((error) => {
        setSubtitleStatus(String(error?.message || "Subtitle search is unavailable."));
      })
      .finally(() => {
        subtitleRequest = null;
      });
    return subtitleRequest;
  };

  const stopLocal = async ({ silent = false } = {}) => {
    clearPoll();
    clearSubtitleTracks();
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
      if (!silent) setStatus("The player stopped, but the runtime shutdown could not be confirmed.");
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
    if (subtitleStatus) {
      if (kind === "vidsrc") {
        clearSubtitleTracks();
        setSubtitleStatus("Use VidSrc captions or switch to Local to load Dragon subtitles inside the player controls.");
      } else if (subtitleOptions === null) {
        setSubtitleStatus("Arabic will be selected first; switch or turn subtitles off from the player controls after Local starts.");
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

  const localPlaybackUrl = () => {
    if (!localSession) return "";
    if (localSession.streamKind === "transcode") return localSession.transcodeUrl || "";
    return localSession.streamUrl || "";
  };

  const switchLocalToTranscode = () => {
    if (!localSession?.transcodeUrl) return false;
    localSession.streamKind = "transcode";
    video.removeAttribute("src");
    video.load();
    video.src = localSession.transcodeUrl;
    video.hidden = false;
    video.preload = "auto";
    setPlayerState("buffering", "Direct playback was not supported. Switching to local transcoding…");
    video.load();
    video.play().catch(() => {});
    return true;
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
    if (session.downloaded_bytes) details.push(`${formatBytes(session.downloaded_bytes)} cached`);
    if (session.cache_hit) details.push("cache hit");
    const progress = session.buffer_percent ? ` ${session.buffer_percent}% startup buffer.` : "";
    setStatus(`${session.message || "Preparing local stream…"}${progress}${details.length ? ` · ${details.join(" · ")}` : ""}`);
    if (!video.hasAttribute("src")) {
      setPlayerState(session.state === "ready" ? "buffering" : (session.state || "metadata"));
    }
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
        localSession.streamUrl = payload.session.stream_url || localSession.streamUrl;
        localSession.transcodeUrl = payload.session.transcode_url || localSession.transcodeUrl;
        localSession.streamKind = payload.session.stream_kind || localSession.streamKind || "direct";
        if (!video.hasAttribute("src")) {
          const playbackUrl = localPlaybackUrl();
          if (!playbackUrl) {
            throw new Error(
              localSession.streamKind === "transcode"
                ? "Local transcode URL is unavailable"
                : "Direct local stream URL is unavailable"
            );
          }
          video.crossOrigin = "anonymous";
          video.src = playbackUrl;
          video.hidden = false;
          video.preload = "auto";
          setPlayerState(
            "buffering",
            localSession.streamKind === "transcode"
              ? "Local transcoding started. Preparing an MP4 stream for the browser…"
              : "Direct stream connected. Buffering the first playable range…"
          );
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
      transcodeUrl: payload.transcode_url,
      streamKind: payload.session?.stream_kind || "direct",
      stopUrl: payload.stop_url,
    };
    launch.hidden = true;
    video.hidden = false;
    controls.hidden = false;
    reload.hidden = true;
    open.hidden = true;
    stop.hidden = false;
    renderLocalStatus(payload.session || {});
    setPlayerState("metadata", "Reading torrent metadata…");
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
        setPlayerState("metadata", "Starting the local WebTorrent runtime…");
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
      void reportWatchStarted();
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
  video.addEventListener("loadstart", () => {
    if (activeKind === "local") setPlayerState("buffering", "Opening the direct local stream…");
  });
  video.addEventListener("waiting", () => {
    if (activeKind === "local") setPlayerState("buffering", "Buffering requested torrent pieces…");
  });
  video.addEventListener("stalled", () => {
    if (activeKind === "local") setPlayerState("stalled", "The torrent stalled. Waiting for peers; VidSrc remains available as fallback.");
  });
  video.addEventListener("playing", () => {
    if (activeKind === "local") {
      setPlayerState("playing", "Playing directly from the local WebTorrent runtime.");
      void reportWatchStarted();
    }
  });
  video.addEventListener("error", () => {
    if (activeKind !== "local") return;
    const codecFailure = video.error?.code === window.MediaError?.MEDIA_ERR_DECODE;
    if (localSession?.streamKind !== "transcode" && switchLocalToTranscode()) return;
    setPlayerState(
      "failed",
      codecFailure
        ? "This codec is not supported by the browser. Switch to VidSrc."
        : "Local playback failed or peers are unavailable. Switch to VidSrc as fallback.",
    );
  });
  video.textTracks?.addEventListener("change", () => {
    if (!subtitleOptions?.length || selectedKind() !== "local") return;
    const activeTrack = Array.from(video.textTracks).find((track) => track.mode === "showing");
    setSubtitleStatus(activeTrack
      ? `${activeTrack.label} subtitles selected. Use the captions menu inside the player to switch or turn them off.`
      : "Subtitles are off. Use the captions menu inside the player to turn them on.");
  });
  window.addEventListener("pagehide", () => { stopLocal({ silent: true }); });
  syncSourceUi();
})();
