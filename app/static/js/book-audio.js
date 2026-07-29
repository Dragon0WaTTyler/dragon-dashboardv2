(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const players = document.querySelectorAll("[data-book-audio-player]");
  if (!players.length) return;

  function asNumber(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  async function saveProgress(root, audio, completed = false) {
    const endpoint = root.dataset.progressUrl;
    if (!endpoint || !csrf) return;
    const duration = Number.isFinite(audio.duration) ? Math.round(audio.duration) : asNumber(audio.dataset.duration);
    const payload = {
      position_seconds: Math.round(audio.currentTime || 0),
      duration_seconds: duration,
      current_chapter: 0,
      playback_speed: audio.playbackRate || 1,
      completed,
    };
    try {
      await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      });
    } catch (_error) {
      // Progress saving is opportunistic; playback should continue if local state cannot update.
    }
  }

  players.forEach((root) => {
    const audio = root.querySelector("audio");
    const speed = root.querySelector("[data-audio-speed]");
    if (!audio) return;

    const savedPosition = asNumber(audio.dataset.position);
    const savedSpeed = asNumber(audio.dataset.speed, 1);
    if (speed) speed.value = String(savedSpeed);
    audio.playbackRate = savedSpeed;

    audio.addEventListener(
      "loadedmetadata",
      () => {
        if (savedPosition > 0 && savedPosition < audio.duration - 5) {
          audio.currentTime = savedPosition;
        }
      },
      { once: true }
    );

    speed?.addEventListener("change", () => {
      audio.playbackRate = asNumber(speed.value, 1);
      saveProgress(root, audio);
    });

    let lastSavedAt = 0;
    audio.addEventListener("timeupdate", () => {
      if (audio.currentTime - lastSavedAt < 15) return;
      lastSavedAt = audio.currentTime;
      saveProgress(root, audio);
    });
    audio.addEventListener("pause", () => saveProgress(root, audio));
    audio.addEventListener("ended", () => saveProgress(root, audio, true));
  });
})();
