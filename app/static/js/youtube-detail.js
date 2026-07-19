(() => {
  const detail = document.querySelector("[data-youtube-detail]");
  if (!detail) return;

  const videoId = detail.dataset.videoId;
  const playerShell = detail.querySelector("[data-youtube-player]");
  const launch = detail.querySelector("[data-player-launch]");
  const frame = detail.querySelector("[data-player-frame]");
  const status = detail.querySelector("[data-player-status]");
  const focusButton = detail.querySelector("[data-player-focus]");
  const resumeCopy = detail.querySelector("[data-resume-copy]");
  const progressKey = `dragon:youtube-progress:${videoId}`;
  let player = null;
  let progressTimer = null;
  let requestedStart = null;
  let focusScrollY = 0;

  function formatTime(value) {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return hours
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
      : `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function readProgress() {
    try {
      const value = JSON.parse(window.localStorage.getItem(progressKey) || "null");
      return value && Number(value.seconds) > 5 ? value : null;
    } catch (_error) {
      return null;
    }
  }

  function saveProgress() {
    if (!player || typeof player.getCurrentTime !== "function") return;
    const seconds = Math.floor(player.getCurrentTime() || 0);
    const duration = Math.floor(player.getDuration?.() || 0);
    try {
      if (duration && seconds >= duration - 10) {
        window.localStorage.removeItem(progressKey);
      } else if (seconds > 0) {
        window.localStorage.setItem(
          progressKey,
          JSON.stringify({ seconds, duration, updatedAt: new Date().toISOString() }),
        );
      }
    } catch (_error) {
      // Playback remains usable when storage is unavailable.
    }
  }

  function loadApi() {
    if (window.YT?.Player) return Promise.resolve(window.YT);
    if (window.dragonYouTubeApiPromise) return window.dragonYouTubeApiPromise;
    window.dragonYouTubeApiPromise = new Promise((resolve) => {
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        if (typeof previous === "function") previous();
        resolve(window.YT);
      };
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.async = true;
      document.head.appendChild(script);
    });
    return window.dragonYouTubeApiPromise;
  }

  function attachPlayer() {
    loadApi().then(() => {
      player = new window.YT.Player(frame, {
        events: {
          onReady: (event) => {
            if (requestedStart !== null) event.target.seekTo(requestedStart, true);
            if (status) status.textContent = "Playing inside Dragon.";
          },
          onStateChange: (event) => {
            if (event.data === window.YT.PlayerState.PLAYING && !progressTimer) {
              progressTimer = window.setInterval(saveProgress, 5000);
            }
            if (
              event.data === window.YT.PlayerState.PAUSED ||
              event.data === window.YT.PlayerState.ENDED
            ) {
              saveProgress();
            }
          },
        },
      });
    });
  }

  function loadPlayer(startAt) {
    const saved = readProgress();
    requestedStart = Number.isFinite(startAt) ? startAt : Number(saved?.seconds || 0);
    const parameters = new URLSearchParams({
      enablejsapi: "1",
      rel: "0",
      playsinline: "1",
      autoplay: "1",
      origin: window.location.origin,
    });
    if (requestedStart > 0) parameters.set("start", String(Math.floor(requestedStart)));
    frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?${parameters}`;
    frame.hidden = false;
    launch.hidden = true;
    playerShell.classList.add("is-loaded");
    if (status) {
      status.textContent = requestedStart > 0
        ? `Resuming at ${formatTime(requestedStart)}…`
        : "Loading YouTube…";
    }
    attachPlayer();
  }

  const saved = readProgress();
  if (saved && resumeCopy) resumeCopy.textContent = `Resume from ${formatTime(saved.seconds)}`;

  launch?.addEventListener("click", () => loadPlayer());

  detail.querySelectorAll("[data-youtube-start]").forEach((chapter) => {
    chapter.addEventListener("click", () => {
      const seconds = Number(chapter.dataset.youtubeStart || 0);
      if (!playerShell.classList.contains("is-loaded")) {
        loadPlayer(seconds);
        return;
      }
      if (player && typeof player.seekTo === "function") {
        player.seekTo(seconds, true);
        player.playVideo?.();
        if (status) status.textContent = `Jumped to ${formatTime(seconds)}.`;
      } else {
        loadPlayer(seconds);
      }
    });
  });

  function setFocusMode(enabled) {
    detail.classList.toggle("is-focus-mode", enabled);
    document.documentElement.classList.toggle("youtube-focus-mode", enabled);
    document.body.classList.toggle("youtube-focus-mode", enabled);
    if (focusButton) {
      focusButton.textContent = enabled ? "Exit focus mode" : "Enter focus mode";
      focusButton.setAttribute("aria-pressed", String(enabled));
    }
    if (enabled) {
      focusScrollY = window.scrollY;
      if (!playerShell.classList.contains("is-loaded")) loadPlayer();
      window.scrollTo({ top: 0, behavior: "instant" });
    } else {
      window.scrollTo({ top: focusScrollY, behavior: "instant" });
    }
  }

  focusButton?.addEventListener("click", () => {
    setFocusMode(!detail.classList.contains("is-focus-mode"));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && detail.classList.contains("is-focus-mode")) {
      setFocusMode(false);
    }
  });

  const description = detail.querySelector("[data-description-body]");
  const descriptionToggle = detail.querySelector("[data-description-toggle]");
  if (description && descriptionToggle && description.scrollHeight > 240) {
    description.classList.add("is-collapsed");
    descriptionToggle.hidden = false;
    descriptionToggle.addEventListener("click", () => {
      const expanded = descriptionToggle.getAttribute("aria-expanded") === "true";
      descriptionToggle.setAttribute("aria-expanded", String(!expanded));
      descriptionToggle.textContent = expanded ? "Show full description" : "Show less";
      description.classList.toggle("is-collapsed", expanded);
    });
  }

  window.addEventListener("beforeunload", saveProgress);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) saveProgress();
  });
})();
