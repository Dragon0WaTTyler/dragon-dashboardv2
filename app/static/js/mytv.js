(() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const elements = Object.fromEntries(
    [...document.querySelectorAll("[id]")].map((element) => [element.id, element])
  );
  const state = {
    bootstrap: null,
    activeGroups: [],
    manageGroups: [],
    channels: [],
    page: 1,
    pages: 1,
    total: 0,
    activeChannel: null,
    syncTimer: null,
    healthTimer: null,
    playbackTimer: null,
  };

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body) headers.set("Content-Type", "application/json");
    if (options.method && options.method !== "GET") headers.set("X-CSRFToken", csrfToken);
    const cache = options.method && options.method !== "GET" ? "no-store" : "no-cache";
    const response = await fetch(url, { ...options, headers, cache });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("json") ? await response.json() : await response.text();
    if (!response.ok) throw new Error(payload?.message || payload?.description || payload || `Request failed (${response.status})`);
    return payload;
  }

  function escapeHtml(value = "") {
    return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }
  function number(value) { return new Intl.NumberFormat().format(value || 0); }
  function toast(message, error = false) {
    const item = document.createElement("div");
    item.className = `tv-toast${error ? " is-error" : ""}`;
    item.textContent = message;
    elements.toastRegion.append(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  async function loadBootstrap({ quiet = false } = {}) {
    try {
      const data = await api("/my-tv/api/bootstrap");
      state.bootstrap = data;
      elements.statEnabled.textContent = number(data.stats.enabled_channels);
      elements.statTotal.textContent = number(data.stats.total_channels);
      elements.statGroups.textContent = number(data.stats.groups);
      elements.statSources.textContent = number(data.stats.imported_playlists);
      elements.sourceRepoFiles.textContent = number(data.stats.repo_files);
      elements.sourceSyncedFiles.textContent = number(data.stats.imported_playlists);
      elements.sourcePendingFiles.textContent = number(data.stats.pending_files);
      updateSyncBanner(data.sync);
      updateHealthBanner(data.health);
      if (!data.stats.repo_files && data.sync.state !== "running" && elements.tvConfig.dataset.autoCatalog === "true") {
        await startSync("fetch", [], true);
        return;
      }
      await loadActiveGroups();
      await loadChannels();
      if (data.sync.state === "running") pollSync();
      if (data.health.state === "running") pollHealth();
      else if (data.health.needs_check && data.stats.enabled_channels && elements.tvConfig.dataset.autoHealth === "true") startHealthCheck({ quiet: true });
    } catch (error) { if (!quiet) toast(error.message, true); }
  }

  async function loadActiveGroups() {
    const params = new URLSearchParams({ active_only: "1" });
    const data = await api(`/my-tv/api/groups?${params}`);
    state.activeGroups = data.groups;
    const current = elements.groupFilter.value;
    elements.groupFilter.innerHTML = '<option value="">All active bouquets</option>' + data.groups.map((item) => `<option value="${item.id}">${escapeHtml(item.name)} · ${number(item.channel_count)}</option>`).join("");
    elements.groupFilter.value = data.groups.some((item) => String(item.id) === current) ? current : "";
  }

  async function loadManageGroups() {
    const params = new URLSearchParams({ visibility: elements.bouquetVisibility.value });
    if (elements.groupSearch.value.trim()) params.set("q", elements.groupSearch.value.trim());
    const data = await api(`/my-tv/api/groups?${params}`);
    state.manageGroups = data.groups;
    renderBouquets();
  }

  function renderBouquets() {
    elements.bouquetEmpty.hidden = state.manageGroups.length > 0;
    elements.bouquetList.hidden = state.manageGroups.length === 0;
    if (state.manageGroups.length === 0) {
      const labels = {
        on: ["No bouquets are on", "Switch to All bouquets or turn on a bouquet."],
        off: ["No bouquets are off", "Switch to All bouquets or turn off a bouquet."],
        all: ["No bouquets found", "Try another search."],
      };
      const [title, text] = labels[elements.bouquetVisibility.value];
      elements.bouquetEmptyTitle.textContent = title;
      elements.bouquetEmptyText.textContent = text;
    }
    elements.bouquetList.innerHTML = state.manageGroups.map((item) => `<article class="tv-bouquet-row">
      <div class="tv-bouquet-copy"><strong>${escapeHtml(item.name)}</strong><p>${number(item.channel_count)} unique channels · ${number(item.raw_group_count)} source copies merged · ${item.enabled_exceptions} on / ${item.disabled_exceptions} off</p></div>
      <button class="tv-switch" type="button" role="switch" aria-checked="${item.enabled}" aria-label="${item.enabled ? "Disable" : "Enable"} bouquet ${escapeHtml(item.name)}" data-toggle-group="${item.id}"></button>
      <div class="tv-bouquet-actions" aria-label="Bulk channel actions"><button class="button button--secondary" type="button" data-group-action="enable" data-group-id="${item.id}">All on</button><button class="button button--danger" type="button" data-group-action="disable" data-group-id="${item.id}">All off</button><button class="button button--quiet" type="button" data-group-action="inherit" data-group-id="${item.id}">Use default</button></div>
    </article>`).join("");
  }

  async function loadChannels() {
    elements.channelGrid.setAttribute("aria-busy", "true");
    const params = new URLSearchParams({ page: state.page, per_page: 36, state: elements.stateFilter.value });
    if (elements.groupFilter.value) params.set("theme_id", elements.groupFilter.value);
    if (elements.channelSearch.value.trim()) params.set("q", elements.channelSearch.value.trim());
    try {
      const data = await api(`/my-tv/api/channels?${params}`);
      state.channels = data.channels;
      state.page = data.pagination.page;
      state.pages = data.pagination.pages;
      state.total = data.pagination.total;
      renderChannels();
      elements.pagination.hidden = state.total === 0 || state.pages <= 1;
      elements.previousPage.disabled = state.page <= 1;
      elements.nextPage.disabled = state.page >= state.pages;
      elements.pageStatus.textContent = `Page ${number(state.page)} of ${number(state.pages)} · ${number(state.total)} channels`;
    } finally { elements.channelGrid.removeAttribute("aria-busy"); }
  }

  function logo(item, className = "tv-channel-logo") {
    const fallback = escapeHtml((item.name || "TV").slice(0, 2).toUpperCase());
    return item.logo_url ? `<span class="${className}"><img src="${escapeHtml(item.logo_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-tv-fallback="${fallback}"></span>` : `<span class="${className}">${fallback}</span>`;
  }

  function renderChannels() {
    elements.channelEmpty.hidden = state.channels.length > 0;
    elements.channelGrid.hidden = state.channels.length === 0;
    elements.channelGrid.innerHTML = state.channels.map((item) => `<article class="tv-channel-card${item.enabled ? "" : " is-disabled"}${state.activeChannel?.id === item.id ? " is-playing" : ""}">
      ${logo(item)}<div class="tv-channel-copy"><h3 title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</h3><p title="${escapeHtml(item.group_name)}">${escapeHtml(item.group_name)}</p><small>${item.enabled_override === null ? "Bouquet default" : item.enabled_override ? "Always on" : "Always off"} · ${item.health_status === "online" ? "Online" : "Unchecked"}</small></div>
      <div class="tv-channel-actions"><button class="tv-favorite-button" type="button" aria-label="${item.favorite ? "Remove" : "Add"} ${escapeHtml(item.name)} ${item.favorite ? "from" : "to"} favorites" aria-pressed="${item.favorite}" data-favorite-channel="${item.id}">★</button><button class="tv-play-button" type="button" aria-label="Play ${escapeHtml(item.name)}" data-play-channel="${item.id}" ${item.enabled ? "" : "disabled"}></button></div>
      <button class="tv-switch tv-channel-switch" type="button" role="switch" aria-checked="${item.enabled}" aria-label="${item.enabled ? "Disable" : "Enable"} ${escapeHtml(item.name)}" data-toggle-channel="${item.id}"></button>
    </article>`).join("");
  }

  async function startSync(mode, ids = [], quiet = false) {
    try {
      const result = await api("/my-tv/api/sync", { method: "POST", body: JSON.stringify({ mode, playlist_ids: ids }) });
      updateSyncBanner(result.sync);
      pollSync();
      if (!quiet) toast(mode === "fetch" ? "Fetching changed files…" : mode === "catalog" ? "Refreshing source catalogue…" : "Import started…");
    } catch (error) { if (!quiet) toast(error.message, true); }
  }

  function updateSyncBanner(status) {
    const running = status?.state === "running";
    elements.syncBanner.hidden = !running;
    if (!status) return;
    elements.syncMessage.textContent = status.error || status.message || "Working…";
    elements.syncCount.textContent = status.total ? `${number(status.current)}/${number(status.total)} · ${number(status.channels)} channels` : `${number(status.new_files)} new · ${number(status.changed_files)} changed`;
    elements.refreshCatalog.disabled = running;
  }

  function pollSync() {
    window.clearTimeout(state.syncTimer);
    const poll = async () => {
      try {
        const status = await api("/my-tv/api/sync");
        updateSyncBanner(status);
        if (status.state === "running") state.syncTimer = window.setTimeout(poll, 1200);
        else {
          const refreshHealth = status.state === "complete" && status.mode === "fetch";
          toast(status.state === "complete" ? status.message : status.error || status.message, status.state === "error");
          await loadBootstrap({ quiet: true });
          if (refreshHealth) startHealthCheck({ quiet: true });
        }
      } catch (error) { toast(error.message, true); }
    };
    state.syncTimer = window.setTimeout(poll, 700);
  }

  function updateHealthBanner(status) {
    const running = status?.state === "running";
    elements.healthBanner.hidden = !running;
    if (!status) return;
    elements.healthMessage.textContent = status.error || status.message || "Checking live sources…";
    elements.healthCount.textContent = status.total ? `${number(status.current)}/${number(status.total)} · ${number(status.online)} online · ${number(status.offline)} unavailable` : "Preparing checks…";
    elements.healthCheck.disabled = running;
  }

  async function startHealthCheck({ quiet = false, themeId = null } = {}) {
    try {
      const result = await api("/my-tv/api/health", { method: "POST", body: JSON.stringify({ theme_id: themeId }) });
      updateHealthBanner(result.health);
      pollHealth();
      if (!quiet) toast("Checking enabled channels and their alternatives…");
    } catch (error) {
      if (!quiet || !String(error.message).includes("already running")) toast(error.message, true);
    }
  }

  function pollHealth() {
    window.clearTimeout(state.healthTimer);
    const poll = async () => {
      try {
        const health = await api("/my-tv/api/health");
        updateHealthBanner(health);
        if (health.state === "running") state.healthTimer = window.setTimeout(poll, 1500);
        else {
          toast(health.state === "complete" ? `Health check complete · ${number(health.online)} online · ${number(health.offline)} unavailable` : health.error || health.message, health.state === "error");
          await loadBootstrap({ quiet: true });
        }
      } catch (error) { toast(error.message, true); }
    };
    state.healthTimer = window.setTimeout(poll, 900);
  }

  function stopPlayback() {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
    elements.videoPlayer.onloadeddata = null;
    elements.videoPlayer.oncanplay = null;
    elements.videoPlayer.onplaying = null;
    elements.videoPlayer.onerror = null;
    elements.videoPlayer.pause();
    elements.videoPlayer.removeAttribute("src");
    elements.videoPlayer.load();
  }

  function showPlaybackStatus(message, error = false) {
    elements.playerLoadingText.textContent = message;
    elements.playerSpinner.hidden = error;
    elements.retryPlayback.hidden = !error;
    elements.playerLoading.classList.toggle("is-error", error);
    elements.playerLoading.hidden = false;
  }

  function playbackReady() {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
    elements.playerLoading.hidden = true;
    elements.playerLoading.classList.remove("is-error");
    elements.retryPlayback.hidden = true;
    elements.videoPlayer.play().catch(() => {});
  }

  function playbackFailed(message) {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
    elements.videoPlayer.onloadeddata = null;
    elements.videoPlayer.oncanplay = null;
    elements.videoPlayer.onplaying = null;
    elements.videoPlayer.onerror = null;
    elements.videoPlayer.pause();
    elements.videoPlayer.removeAttribute("src");
    elements.videoPlayer.load();
    showPlaybackStatus(message, true);
  }

  async function playChannel(id) {
    const item = state.channels.find((channel) => channel.id === id);
    if (!item) return;
    stopPlayback();
    state.activeChannel = item;
    showPlaybackStatus("Opening live stream…");
    try {
      const playback = await api(`/my-tv/api/channels/${id}/playback`);
      elements.playerEmpty.hidden = true;
      elements.videoPlayer.hidden = false;
      elements.nowPlayingTitle.textContent = playback.name;
      elements.nowPlayingMeta.textContent = item.group_name;
      elements.liveBadge.hidden = false;
      elements.nowLogo.innerHTML = playback.logo_url ? `<img src="${escapeHtml(playback.logo_url)}" alt="" referrerpolicy="no-referrer" data-tv-fallback="TV">` : escapeHtml(playback.name.slice(0, 2).toUpperCase());
      elements.videoPlayer.onloadeddata = playbackReady;
      elements.videoPlayer.oncanplay = playbackReady;
      elements.videoPlayer.onplaying = playbackReady;
      elements.videoPlayer.onerror = () => playbackFailed("This channel is offline or its stream has expired.");
      state.playbackTimer = window.setTimeout(() => {
        if (elements.videoPlayer.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) playbackReady();
        else playbackFailed("This channel did not respond within 15 seconds. Try it again or choose another channel.");
      }, 15000);
      elements.videoPlayer.src = playback.url;
      elements.videoPlayer.load();
      elements.videoPlayer.play().catch(() => {});
      renderChannels();
    } catch (error) { playbackFailed(error.message || "This channel could not be opened."); }
  }

  function debounce(callback, wait = 300) {
    let timer;
    return (...args) => { window.clearTimeout(timer); timer = window.setTimeout(() => callback(...args), wait); };
  }

  document.addEventListener("click", async (event) => {
    const tab = event.target.closest("[data-view]");
    if (tab) {
      document.querySelectorAll("[data-view]").forEach((item) => item.setAttribute("aria-selected", String(item === tab)));
      document.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== tab.dataset.view; });
      if (tab.dataset.view === "manage") await loadManageGroups();
      return;
    }
    const play = event.target.closest("[data-play-channel]");
    if (play) return playChannel(Number(play.dataset.playChannel));
    const favorite = event.target.closest("[data-favorite-channel]");
    if (favorite) {
      const item = state.channels.find((channel) => channel.id === Number(favorite.dataset.favoriteChannel));
      try { await api(`/my-tv/api/channels/${item.id}/favorite`, { method: "PATCH", body: JSON.stringify({ favorite: !item.favorite }) }); toast(item.favorite ? "Removed from favorites" : "Saved to favorites"); await loadChannels(); } catch (error) { toast(error.message, true); }
      return;
    }
    const channelToggle = event.target.closest("[data-toggle-channel]");
    if (channelToggle) {
      const item = state.channels.find((channel) => channel.id === Number(channelToggle.dataset.toggleChannel));
      try { await api(`/my-tv/api/channels/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled }) }); await loadBootstrap({ quiet: true }); } catch (error) { toast(error.message, true); }
      return;
    }
    const groupToggle = event.target.closest("[data-toggle-group]");
    if (groupToggle) {
      const item = state.manageGroups.find((group) => group.id === Number(groupToggle.dataset.toggleGroup));
      const enabling = !item.enabled;
      try { await api(`/my-tv/api/groups/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: enabling }) }); await loadBootstrap({ quiet: true }); await loadManageGroups(); if (enabling) startHealthCheck({ quiet: true, themeId: item.id }); } catch (error) { toast(error.message, true); }
      return;
    }
    const groupAction = event.target.closest("[data-group-action]");
    if (groupAction) {
      try { await api(`/my-tv/api/groups/${groupAction.dataset.groupId}/channels`, { method: "POST", body: JSON.stringify({ action: groupAction.dataset.groupAction }) }); toast(groupAction.dataset.groupAction === "inherit" ? "Overrides cleared" : `All channels set ${groupAction.dataset.groupAction === "enable" ? "on" : "off"}`); await loadBootstrap({ quiet: true }); await loadManageGroups(); } catch (error) { toast(error.message, true); }
      return;
    }
    if (event.target.closest("[data-empty-sync]")) startSync("fetch");
  });

  document.addEventListener("change", async (event) => {
    if (event.target === elements.groupFilter || event.target === elements.stateFilter) { state.page = 1; await loadChannels(); }
    if (event.target === elements.bouquetVisibility) await loadManageGroups();
  });

  elements.channelSearch.addEventListener("input", debounce(() => { state.page = 1; loadChannels().catch((error) => toast(error.message, true)); }));
  elements.groupSearch.addEventListener("input", debounce(() => loadManageGroups().catch((error) => toast(error.message, true))));
  elements.refreshCatalog.addEventListener("click", () => startSync("fetch"));
  elements.healthCheck.addEventListener("click", () => startHealthCheck());
  elements.retryPlayback.addEventListener("click", () => { if (state.activeChannel) playChannel(state.activeChannel.id); });
  elements.previousPage.addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadChannels().catch((error) => toast(error.message, true)); } });
  elements.nextPage.addEventListener("click", () => { if (state.page < state.pages) { state.page += 1; loadChannels().catch((error) => toast(error.message, true)); } });
  document.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.dataset.tvFallback) event.target.parentElement.textContent = event.target.dataset.tvFallback;
  }, true);
  loadBootstrap();
})();
