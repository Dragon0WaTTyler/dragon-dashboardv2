(() => {
  const root = document.querySelector("[data-personal-tv]");
  if (!root) return;

  const csrfToken = document.querySelector("meta[name='csrf-token']")?.content || "";
  const setup = root.querySelector("[data-tv-setup]");
  const review = root.querySelector("[data-tv-review]");
  const sessionView = root.querySelector("[data-tv-session]");
  const status = root.querySelector("[data-program-status]");
  const groupsHost = root.querySelector("[data-group-picker]");
  const catalogueStatus = root.querySelector("[data-catalogue-status]");
  const playerHost = root.querySelector("[data-player-host]");
  const profileSummary = root.querySelector("[data-profile-summary]");
  let selectedDuration = 60;
  let selectedGroups = new Set();
  let availableGroups = [];
  let activeSession = null;
  let preferences = {};
  let player = null;
  let apiPromise = null;
  let replacementPending = false;
  let progressTimer = null;
  let lastReportedSecond = -1;

  const request = async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken, ...(options.headers || {}) },
    });
    const body = await response.json();
    if (!response.ok || body.ok === false) throw new Error(body.error || "My TV could not complete that action.");
    return body;
  };
  const setStatus = (message) => { status.textContent = message; };
  const formatDuration = (seconds) => {
    const minutes = Math.max(0, Math.round((seconds || 0) / 60));
    return minutes >= 60 ? `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ""}` : `${minutes} min`;
  };
  const currentItem = () => activeSession?.items?.[activeSession.current_item_index] || null;
  const splitTerms = (value) => value.split(",").map((term) => term.trim()).filter(Boolean);
  const prefInput = (name) => root.querySelector(`[data-preference-${name}]`);

  function renderDuration() {
    root.querySelectorAll("[data-duration]").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.duration) === selectedDuration));
    });
  }

  function renderCatalogueStatus() {
    const selected = availableGroups.filter((group) => selectedGroups.has(group.name));
    if (!selected.length) {
      catalogueStatus.textContent = "Balanced sessions use your cached library. Favo channels are automatically prioritised.";
      return;
    }
    const channels = selected.reduce((total, group) => total + (group.channel_count || 0), 0);
    const videos = selected.reduce((total, group) => total + (group.cached_video_count || group.count || 0), 0);
    const freshest = selected.map((group) => group.last_hydrated_at).filter(Boolean).sort().at(-1);
    const freshness = freshest ? ` Last refreshed ${new Date(freshest).toLocaleDateString()}.` : " It will refresh a bounded channel slice when you build a session.";
    catalogueStatus.textContent = `${channels || "Selected"} channels · ${videos} cached videos.${freshness}`;
  }

  function renderGroups(groups) {
    availableGroups = groups;
    groupsHost.replaceChildren();
    if (!groups.length) {
      groupsHost.textContent = "No PocketTube collections are available yet. You can still start a balanced session.";
      return;
    }
    groups.forEach((group) => {
      if (group.favorite) {
        const favorite = document.createElement("p");
        favorite.className = "group-picker__favorite";
        favorite.textContent = `★ my favoret · ${group.channel_count || group.count || 0} trusted channels are prioritised automatically`;
        groupsHost.append(favorite);
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.group = group.name;
      button.setAttribute("aria-pressed", String(selectedGroups.has(group.name)));
      button.append(document.createTextNode(group.name));
      const count = document.createElement("small");
      count.textContent = group.channel_count ? `${group.channel_count} channels` : `${group.count || 0} cached`;
      button.append(count);
      button.addEventListener("click", () => {
        selectedGroups.has(group.name) ? selectedGroups.delete(group.name) : selectedGroups.add(group.name);
        button.setAttribute("aria-pressed", String(selectedGroups.has(group.name)));
        renderCatalogueStatus();
      });
      groupsHost.append(button);
    });
    renderCatalogueStatus();
  }

  function renderPreferences() {
    prefInput("topics").value = (preferences.preferred_topics || []).join(", ");
    prefInput("formats").value = (preferences.preferred_formats || []).join(", ");
    prefInput("languages").value = (preferences.preferred_languages || []).join(", ");
  }

  function renderProfile(profile) {
    const observed = profile?.observed || {};
    const completed = observed.completed_programmes || 0;
    const skipped = observed.skipped_programmes || 0;
    profileSummary.textContent = completed || skipped
      ? `Dragon observed ${completed} completed and ${skipped} skipped programmes. Your explicit choices stay separate.`
      : "Your explicit choices stay editable; a quick skip never becomes a permanent rule by itself.";
  }

  function destroyPlayer() {
    window.clearInterval(progressTimer);
    progressTimer = null;
    if (player?.destroy) player.destroy();
    player = null;
    lastReportedSecond = -1;
  }

  function loadYoutubeApi() {
    if (window.YT?.Player) return Promise.resolve(window.YT);
    if (apiPromise) return apiPromise;
    apiPromise = new Promise((resolve) => {
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => { previous?.(); resolve(window.YT); };
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.async = true;
      document.head.append(script);
    });
    return apiPromise;
  }

  async function reportProgress(force = false) {
    const item = currentItem();
    if (!activeSession || !item || !player?.getCurrentTime || activeSession.state === "planned") return;
    const second = Math.max(0, Math.floor(player.getCurrentTime()));
    if (!force && second - lastReportedSecond < 15) return;
    lastReportedSecond = second;
    try {
      const body = await request(`/my-tv/api/sessions/${activeSession.id}/progress`, {
        method: "POST",
        body: JSON.stringify({ playhead_seconds: second }),
      });
      activeSession = body.session;
      renderSession({ mount: false });
    } catch (_) {
      // A progress sample is opportunistic. Playback should not stop if the network blips.
    }
  }

  function startProgressTimer() {
    window.clearInterval(progressTimer);
    progressTimer = window.setInterval(() => { reportProgress(); }, 15000);
  }

  async function mountPlayer() {
    const item = currentItem();
    destroyPlayer();
    playerHost.replaceChildren();
    if (!item) return;
    if (item.source === "iptv") {
      const message = document.createElement("div");
      message.className = "tv-player__loading";
      message.textContent = "This live programme is available in IPTV.";
      const link = document.createElement("a");
      link.className = "button button--secondary";
      link.href = "/iptv";
      link.textContent = item.playback_hint || "Open in IPTV";
      playerHost.append(message, link);
      return;
    }
    const frame = document.createElement("div");
    frame.id = "personal-tv-youtube-player";
    playerHost.append(frame);
    try {
      const YT = await loadYoutubeApi();
      player = new YT.Player(frame.id, {
        videoId: item.content_id,
        playerVars: { autoplay: 1, playsinline: 1, rel: 0, modestbranding: 1 },
        events: {
          onReady: (event) => {
            if (item.playhead_seconds > 0) event.target.seekTo(item.playhead_seconds, true);
            if (activeSession?.state === "playing") event.target.playVideo();
          },
          onStateChange: (event) => {
            if (event.data === YT.PlayerState.PLAYING) startProgressTimer();
            if (event.data === YT.PlayerState.PAUSED) reportProgress(true);
            if (event.data === YT.PlayerState.ENDED) {
              window.clearInterval(progressTimer);
              transition("complete_item");
            }
          },
          onError: () => {
            setStatus("This video is unavailable. Finding an equivalent replacement…");
            if (!replacementPending) {
              replacementPending = true;
              transition("replace").finally(() => { replacementPending = false; });
            }
          },
        },
      });
    } catch (_) {
      playerHost.textContent = "YouTube playback could not load. Use Skip or Shuffle rest to continue the programme.";
    }
  }

  function renderReview() {
    if (!activeSession) return;
    destroyPlayer();
    setup.hidden = true;
    review.hidden = false;
    sessionView.hidden = true;
    root.querySelector("[data-review-summary]").textContent = `${activeSession.items.length} programmes · ${formatDuration(activeSession.planned_duration_seconds)} · You can start watching when it feels right.`;
    const list = root.querySelector("[data-review-list]");
    list.replaceChildren();
    activeSession.items.forEach((item, index) => {
      const row = document.createElement("li");
      const thumbnail = document.createElement("img");
      thumbnail.src = item.thumbnail_url || "";
      thumbnail.alt = "";
      thumbnail.loading = "lazy";
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.title;
      const metadata = document.createElement("p");
      metadata.textContent = `${String(index + 1).padStart(2, "0")} · ${item.creator} · ${formatDuration(item.duration_seconds)}`;
      const reason = document.createElement("small");
      reason.textContent = `Selected because it ${item.reason_selected}.`;
      const actions = document.createElement("div");
      actions.className = "tv-review__actions";
      const replaceButton = document.createElement("button");
      replaceButton.type = "button";
      replaceButton.className = "button button--quiet";
      replaceButton.textContent = "Replace";
      replaceButton.addEventListener("click", () => editReviewItem(item.id, "replace"));
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "button button--quiet";
      removeButton.textContent = "Remove";
      removeButton.addEventListener("click", () => editReviewItem(item.id, "remove"));
      actions.append(replaceButton, removeButton);
      details.append(title, metadata, reason, actions);
      row.append(thumbnail, details);
      list.append(row);
    });
  }

  function renderSession({ mount = true } = {}) {
    if (!activeSession) return;
    if (activeSession.state === "planned") {
      renderReview();
      return;
    }
    setup.hidden = true;
    review.hidden = true;
    sessionView.hidden = false;
    const item = currentItem();
    root.querySelector("[data-session-remaining]").textContent = `${formatDuration(Math.max(0, activeSession.planned_duration_seconds - activeSession.elapsed_seconds))} remaining`;
    root.querySelector("[data-now-title]").textContent = item?.title || "Session complete";
    root.querySelector("[data-now-creator]").textContent = item?.creator || "";
    root.querySelector("[data-now-reason]").textContent = item
      ? `Selected because it ${item.reason_selected}. ${item.program_role ? `It is your ${item.program_role.replace("_", " ")}.` : ""}`
      : "Your My TV session is complete.";
    root.querySelector("[data-pause-session]").textContent = activeSession.state === "paused" ? "Resume" : "Pause";
    root.querySelector("[data-lineup-summary]").textContent = `${activeSession.items.length} programmes · ${formatDuration(activeSession.planned_duration_seconds)}`;
    const lineup = root.querySelector("[data-session-lineup]");
    lineup.replaceChildren();
    activeSession.items.forEach((entry, index) => {
      const row = document.createElement("li");
      if (index === activeSession.current_item_index) row.classList.add("is-current");
      if (["completed", "skipped"].includes(entry.state)) row.classList.add("is-done");
      const title = document.createElement("span");
      title.textContent = entry.title;
      const duration = document.createElement("time");
      duration.textContent = formatDuration(entry.duration_seconds);
      row.append(title, duration);
      lineup.append(row);
    });
    if (mount && item && !["completed", "abandoned"].includes(activeSession.state)) mountPlayer();
  }

  async function transition(action, payload = {}) {
    if (!activeSession) return;
    try {
      const body = await request(`/my-tv/api/sessions/${activeSession.id}/${action}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      activeSession = body.session;
      renderSession();
    } catch (error) { setStatus(error.message); }
  }

  async function editReviewItem(itemId, action) {
    if (!activeSession) return;
    try {
      const body = await request(`/my-tv/api/sessions/${activeSession.id}/items/${itemId}/${action}`, {
        method: "POST",
        body: "{}",
      });
      activeSession = body.session;
      renderReview();
    } catch (error) { setStatus(error.message); }
  }

  async function sendFeedback(kind) {
    if (!activeSession) return;
    try {
      const body = await request(`/my-tv/api/sessions/${activeSession.id}/feedback`, {
        method: "POST",
        body: JSON.stringify({ kind }),
      });
      activeSession = body.session;
      renderProfile(body.profile);
      setStatus("My TV preferences updated. You can review them in Tune My TV.");
    } catch (error) { setStatus(error.message); }
  }

  async function savePreferences() {
    try {
      const body = await request("/my-tv/api/preferences", {
        method: "PATCH",
        body: JSON.stringify({
          preferred_topics: splitTerms(prefInput("topics").value),
          preferred_formats: splitTerms(prefInput("formats").value),
          preferred_languages: splitTerms(prefInput("languages").value),
        }),
      });
      preferences = body.preferences;
      renderPreferences();
      setStatus("My TV preferences saved.");
    } catch (error) { setStatus(error.message); }
  }

  async function startSession() {
    const button = root.querySelector("[data-start-session]");
    button.disabled = true;
    setStatus("Checking the selected collection and programming your session…");
    try {
      const body = await request("/my-tv/api/sessions", {
        method: "POST",
        body: JSON.stringify({
          duration_minutes: selectedDuration,
          groups: [...selectedGroups],
          avoid_watched: root.querySelector("[data-avoid-watched]").checked,
          no_shorts: root.querySelector("[data-no-shorts]").checked,
        }),
      });
      activeSession = body.session;
      renderReview();
    } catch (error) { setStatus(error.message); } finally { button.disabled = false; }
  }

  async function deepenCatalogue() {
    if (!selectedGroups.size) {
      setStatus("Choose at least one collection before deepening its catalogue.");
      return;
    }
    const button = root.querySelector("[data-deepen-catalogue]");
    button.disabled = true;
    setStatus("Deepening the selected collections…");
    try {
      const body = await request("/my-tv/api/catalogue/deepen", {
        method: "POST",
        body: JSON.stringify({ groups: [...selectedGroups] }),
      });
      renderGroups(body.groups || []);
      const result = body.result || {};
      setStatus(`Added or refreshed ${result.videos || 0} videos from ${result.channels || 0} channels.`);
    } catch (error) {
      setStatus(error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function bootstrap() {
    try {
      const body = await request("/my-tv/api/bootstrap");
      preferences = body.preferences;
      selectedDuration = preferences.default_duration_minutes;
      selectedGroups = new Set((preferences.selected_groups || []).filter((group) => group !== "my favoret"));
      root.querySelector("[data-avoid-watched]").checked = preferences.avoid_watched;
      root.querySelector("[data-no-shorts]").checked = preferences.no_shorts;
      renderDuration();
      renderGroups(body.groups || []);
      renderPreferences();
      renderProfile(body.profile);
      activeSession = body.active_session;
      if (activeSession) renderSession();
    } catch (error) {
      setStatus(error.message);
      groupsHost.textContent = "Could not load your YouTube collections.";
    }
  }

  root.querySelectorAll("[data-duration]").forEach((button) => button.addEventListener("click", () => {
    selectedDuration = Number(button.dataset.duration);
    renderDuration();
  }));
  root.querySelector("[data-start-session]").addEventListener("click", startSession);
  root.querySelector("[data-deepen-catalogue]").addEventListener("click", deepenCatalogue);
  root.querySelector("[data-start-watching]").addEventListener("click", () => transition("play"));
  root.querySelector("[data-shuffle-review]").addEventListener("click", () => transition("regenerate"));
  root.querySelector("[data-review-back]").addEventListener("click", async () => {
    if (activeSession) await transition("stop");
    activeSession = null;
    review.hidden = true;
    setup.hidden = false;
  });
  root.querySelector("[data-save-preferences]").addEventListener("click", savePreferences);
  root.querySelector("[data-pause-session]").addEventListener("click", async () => {
    if (activeSession?.state === "playing") await reportProgress(true);
    transition(activeSession?.state === "paused" ? "play" : "pause");
  });
  root.querySelector("[data-skip-session]").addEventListener("click", async () => {
    await reportProgress(true);
    transition("skip", { skip_reason: root.querySelector("[data-skip-reason]").value });
  });
  root.querySelector("[data-stop-session]").addEventListener("click", async () => {
    await reportProgress(true);
    transition("stop");
  });
  root.querySelector("[data-regenerate-session]").addEventListener("click", () => transition("regenerate"));
  root.querySelectorAll("[data-feedback]").forEach((button) => button.addEventListener("click", () => sendFeedback(button.dataset.feedback)));
  document.addEventListener("visibilitychange", () => { if (document.hidden) reportProgress(true); });
  window.addEventListener("pagehide", () => { reportProgress(true); });
  bootstrap();
})();
