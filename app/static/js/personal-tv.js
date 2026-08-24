(() => {
  const root = document.querySelector("[data-personal-tv]");
  if (!root) return;

  const csrfToken = document.querySelector("meta[name='csrf-token']")?.content || "";
  const setup = root.querySelector("[data-tv-setup]");
  const sessionView = root.querySelector("[data-tv-session]");
  const status = root.querySelector("[data-program-status]");
  const groupsHost = root.querySelector("[data-group-picker]");
  const playerHost = root.querySelector("[data-player-host]");
  const profileSummary = root.querySelector("[data-profile-summary]");
  let selectedDuration = 60;
  let selectedGroups = new Set();
  let activeSession = null;
  let preferences = {};
  let player = null;
  let apiPromise = null;
  let replacementPending = false;

  const formatDuration = (seconds) => {
    const minutes = Math.round((seconds || 0) / 60);
    return minutes >= 60
      ? Math.floor(minutes / 60) + "h " + (minutes % 60 ? minutes % 60 + "m" : "")
      : minutes + " min";
  };
  const request = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken, ...(options.headers || {}) } });
    const body = await response.json();
    if (!response.ok || body.ok === false) throw new Error(body.error || "My TV could not complete that action.");
    return body;
  };
  const setStatus = (message) => { status.textContent = message; };
  const currentItem = () => activeSession?.items?.[activeSession.current_item_index] || null;
  const splitTerms = (value) => value.split(",").map((term) => term.trim()).filter(Boolean);
  const prefInput = (name) => root.querySelector("[data-preference-" + name + "]");

  function renderDuration() {
    root.querySelectorAll("[data-duration]").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.duration) === selectedDuration));
    });
  }
  function renderGroups(groups) {
    groupsHost.replaceChildren();
    if (!groups.length) {
      groupsHost.textContent = "No Dragon Groups are cached yet. You can still start a balanced YouTube session.";
      return;
    }
    groups.forEach((group) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.group = group.name;
      if (group.favorite) button.classList.add("is-favorite");
      button.setAttribute("aria-pressed", String(selectedGroups.has(group.name)));
      button.append(document.createTextNode(group.name));
      const count = document.createElement("small");
      count.textContent = group.count;
      button.append(count);
      if (group.favorite) button.title = "Your Favo channels stay a priority in My TV.";
      button.addEventListener("click", () => {
        selectedGroups.has(group.name) ? selectedGroups.delete(group.name) : selectedGroups.add(group.name);
        button.setAttribute("aria-pressed", String(selectedGroups.has(group.name)));
      });
      groupsHost.append(button);
    });
  }
  function renderPreferences() {
    prefInput("topics").value = (preferences.preferred_topics || []).join(", ");
    prefInput("formats").value = (preferences.preferred_formats || []).join(", ");
    prefInput("languages").value = (preferences.preferred_languages || []).join(", ");
    root.querySelector("[data-discovery-level]").value = preferences.discovery_level || "balanced";
  }
  function renderProfile(profile) {
    const observed = profile?.observed || {};
    const finished = observed.completed_programmes || 0;
    const skipped = observed.skipped_programmes || 0;
    profileSummary.textContent = finished || skipped
      ? "Dragon observed " + finished + " completed and " + skipped + " skipped programmes. Review these controls any time."
      : "Your choices will stay here; observed viewing signals stay separate.";
  }
  function renderPrepared(programs) {
    const section = root.querySelector("[data-prepared-programs]");
    const list = root.querySelector("[data-prepared-list]");
    list.replaceChildren();
    section.hidden = !programs?.length;
    (programs || []).forEach((program) => {
      const row = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = program.name;
      const time = document.createElement("time");
      time.textContent = new Date(program.starts_at).toLocaleString();
      const button = document.createElement("button");
      button.className = "button button--quiet";
      button.type = "button";
      button.textContent = "Start now";
      button.addEventListener("click", async () => {
        const body = await request("/my-tv/api/programs/" + program.id + "/start", { method: "POST", body: "{}" });
        activeSession = body.session;
        renderSession();
      });
      row.append(name, time, button);
      list.append(row);
    });
  }
  function destroyPlayer() {
    if (player?.destroy) player.destroy();
    player = null;
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
          onReady: (event) => { if (activeSession?.state === "playing") event.target.playVideo(); },
          onStateChange: (event) => { if (event.data === YT.PlayerState.ENDED) transition("complete_item"); },
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
      playerHost.textContent = "YouTube playback could not load. Use Skip or Refresh rest to continue the programme.";
    }
  }
  function renderSession({ mount = true } = {}) {
    if (!activeSession) return;
    setup.hidden = true;
    sessionView.hidden = false;
    const item = currentItem();
    root.querySelector("[data-session-remaining]").textContent = formatDuration(Math.max(0, activeSession.planned_duration_seconds - activeSession.elapsed_seconds)) + " remaining";
    root.querySelector("[data-now-title]").textContent = item?.title || "Session complete";
    root.querySelector("[data-now-creator]").textContent = item?.creator || "";
    root.querySelector("[data-now-reason]").textContent = item
      ? "Selected because it " + item.reason_selected + ". " + (item.program_role ? "It is your " + item.program_role.replace("_", " ") + "." : "")
      : "Your My TV session is complete.";
    root.querySelector("[data-pause-session]").textContent = activeSession.state === "paused" ? "Resume" : "Pause";
    root.querySelector("[data-lineup-summary]").textContent = activeSession.items.length + " programmes · " + formatDuration(activeSession.planned_duration_seconds);
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
      const body = await request("/my-tv/api/sessions/" + activeSession.id + "/" + action, { method: "POST", body: JSON.stringify(payload) });
      activeSession = body.session;
      renderSession();
    } catch (error) { setStatus(error.message); }
  }
  async function sendFeedback(kind) {
    if (!activeSession) return;
    try {
      const body = await request("/my-tv/api/sessions/" + activeSession.id + "/feedback", { method: "POST", body: JSON.stringify({ kind }) });
      activeSession = body.session;
      renderProfile(body.profile);
      setStatus("My TV preferences updated. You can edit them below.");
    } catch (error) { setStatus(error.message); }
  }
  async function applyIntent() {
    const text = root.querySelector("[data-intent]").value.trim();
    if (!text) return;
    try {
      const body = await request("/my-tv/api/intent", { method: "POST", body: JSON.stringify({ text }) });
      const intent = body.intent;
      selectedDuration = intent.duration_minutes;
      selectedGroups = new Set(intent.groups || []);
      root.querySelector("[data-no-shorts]").checked = intent.no_shorts;
      prefInput("topics").value = (intent.topics || []).join(", ");
      prefInput("formats").value = (intent.formats || []).join(", ");
      prefInput("languages").value = (intent.languages || []).join(", ");
      renderDuration();
      root.querySelectorAll("[data-group]").forEach((button) => button.setAttribute("aria-pressed", String(selectedGroups.has(button.dataset.group))));
      setStatus("Intent understood. Review the choices, then start My TV.");
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
          discovery_level: root.querySelector("[data-discovery-level]").value,
        }),
      });
      preferences = body.preferences;
      renderPreferences();
      setStatus("My TV preferences saved.");
    } catch (error) { setStatus(error.message); }
  }
  async function prepareDayparts() {
    try {
      const body = await request("/my-tv/api/programs/generate", { method: "POST", body: "{}" });
      renderPrepared(body.programs);
      setStatus("Today's My TV programmes are ready. You can still start, replace, or change anything.");
    } catch (error) { setStatus(error.message); }
  }
  async function startSession() {
    const button = root.querySelector("[data-start-session]");
    button.disabled = true;
    setStatus("Programming your session…");
    try {
      const body = await request("/my-tv/api/sessions", {
        method: "POST",
        body: JSON.stringify({
          duration_minutes: selectedDuration,
          groups: [...selectedGroups],
          topics: splitTerms(prefInput("topics").value),
          formats: splitTerms(prefInput("formats").value),
          languages: splitTerms(prefInput("languages").value),
          discovery_level: root.querySelector("[data-discovery-level]").value,
          avoid_watched: root.querySelector("[data-avoid-watched]").checked,
          no_shorts: root.querySelector("[data-no-shorts]").checked,
          allow_live: root.querySelector("[data-allow-live]").checked,
        }),
      });
      activeSession = body.session;
      renderSession();
    } catch (error) { setStatus(error.message); } finally { button.disabled = false; }
  }
  async function bootstrap() {
    try {
      const body = await request("/my-tv/api/bootstrap");
      preferences = body.preferences;
      selectedDuration = preferences.default_duration_minutes;
      selectedGroups = new Set(preferences.selected_groups || []);
      root.querySelector("[data-avoid-watched]").checked = preferences.avoid_watched;
      root.querySelector("[data-no-shorts]").checked = preferences.no_shorts;
      renderDuration();
      renderGroups(body.groups || []);
      renderPreferences();
      renderProfile(body.profile);
      renderPrepared(body.prepared_programs);
      activeSession = body.active_session;
      if (activeSession) renderSession();
    } catch (error) {
      setStatus(error.message);
      groupsHost.textContent = "Could not load your YouTube groups.";
    }
  }
  root.querySelectorAll("[data-duration]").forEach((button) => button.addEventListener("click", () => { selectedDuration = Number(button.dataset.duration); renderDuration(); }));
  root.querySelector("[data-start-session]").addEventListener("click", startSession);
  root.querySelector("[data-apply-intent]").addEventListener("click", applyIntent);
  root.querySelector("[data-save-preferences]").addEventListener("click", savePreferences);
  root.querySelector("[data-prepare-dayparts]").addEventListener("click", prepareDayparts);
  root.querySelector("[data-pause-session]").addEventListener("click", () => transition(activeSession?.state === "paused" ? "play" : "pause"));
  root.querySelector("[data-skip-session]").addEventListener("click", () => transition("skip"));
  root.querySelector("[data-stop-session]").addEventListener("click", () => transition("stop"));
  root.querySelector("[data-regenerate-session]").addEventListener("click", () => transition("regenerate"));
  root.querySelectorAll("[data-feedback]").forEach((button) => button.addEventListener("click", () => sendFeedback(button.dataset.feedback)));
  bootstrap();
})();
