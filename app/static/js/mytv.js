(() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const elements = Object.fromEntries(
    [...document.querySelectorAll("[id]")].map((element) => [element.id, element])
  );
  const state = {
    bootstrap: null,
    manageGroups: [],
    manageChannels: [],
    channels: [],
    page: 1,
    pages: 1,
    total: 0,
    manageChannelPage: 1,
    manageChannelPages: 1,
    manageChannelTotal: 0,
    loadingChannels: false,
    loadingManageChannels: false,
    activeChannel: null,
    requestedChannel: null,
    retryChannel: null,
    pendingBulk: null,
    savingGroups: new Set(),
    savingFavorites: new Set(),
    syncTimer: null,
    healthTimer: null,
    epgTimer: null,
    playbackTimer: null,
    requestTokens: {
      bootstrap: 0,
      manageGroups: 0,
      manageChannels: 0,
      channels: 0,
    },
    requestControllers: {
      manageGroups: null,
      manageChannels: null,
      channels: null,
    },
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
  function relativeTime(value) {
    if (!value) return "not updated yet";
    const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
    const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    if (Math.abs(seconds) < 90) return formatter.format(seconds, "second");
    const minutes = Math.round(seconds / 60);
    if (Math.abs(minutes) < 90) return formatter.format(minutes, "minute");
    const hours = Math.round(minutes / 60);
    if (Math.abs(hours) < 36) return formatter.format(hours, "hour");
    return formatter.format(Math.round(hours / 24), "day");
  }
  function clock(value) {
    return value ? new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value)) : "";
  }
  function isAbortError(error) { return error?.name === "AbortError"; }
  function beginAbortableRequest(key) {
    state.requestTokens[key] += 1;
    state.requestControllers[key]?.abort();
    const controller = new AbortController();
    state.requestControllers[key] = controller;
    return { token: state.requestTokens[key], signal: controller.signal };
  }
  function isCurrentRequest(key, token) { return state.requestTokens[key] === token; }
  function channelOverrideValue(item) {
    return item.enabled_override === null ? "default" : item.enabled_override ? "on" : "off";
  }
  function mergeChannels(current, incoming) {
    const byId = new Map(current.map((item) => [item.id, item]));
    incoming.forEach((item) => byId.set(item.id, item));
    return [...byId.values()];
  }
  function setNowLogo(name = "TV", logoUrl = "") {
    const fallback = escapeHtml((name || "TV").slice(0, 2).toUpperCase());
    elements.nowLogo.innerHTML = logoUrl ? `<img src="${escapeHtml(logoUrl)}" alt="" referrerpolicy="no-referrer" data-tv-fallback="${fallback}">` : fallback;
  }
  function setNowPlaying(channel, message, { live = false } = {}) {
    if (channel) {
      elements.nowPlayingTitle.textContent = channel.name;
      elements.nowPlayingMeta.textContent = message;
      setNowLogo(channel.name, channel.logo_url || "");
      const current = channel.epg?.now;
      const upcoming = channel.epg?.next;
      elements.nowPlayingGuide.textContent = current
        ? `Now · ${current.title}${upcoming ? `  ·  Next ${clock(upcoming.starts_at)} · ${upcoming.title}` : ""}`
        : "Schedule unavailable";
      elements.nowPlayingGuide.hidden = false;
    }
    else {
      elements.nowPlayingTitle.textContent = "Nothing selected";
      elements.nowPlayingMeta.textContent = message;
      setNowLogo();
      elements.nowPlayingGuide.hidden = true;
    }
    elements.liveBadge.hidden = !live;
    elements.pictureInPicture.hidden = !live || !document.pictureInPictureEnabled;
  }
  function toast(message, error = false, action = null) {
    const item = document.createElement("div");
    item.className = `tv-toast${error ? " is-error" : ""}`;
    const copy = document.createElement("span");
    copy.textContent = message;
    item.append(copy);
    if (action) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await action.run(); item.remove(); }
        catch (caught) { toast(caught.message, true); button.disabled = false; }
      });
      item.append(button);
    }
    elements.toastRegion.append(item);
    window.setTimeout(() => item.remove(), action ? 18000 : 5200);
  }

  function syncChannelViewControls() {
    document.querySelectorAll("[data-channel-view]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.channelView === elements.stateFilter.value));
    });
  }

  function updateChannelViewContext(view, total) {
    const labels = {
      enabled: "Ready to watch",
      favorites: "Favorites",
      recent: "Recently watched",
      all: "All channels",
      disabled: "Disabled channels",
    };
    elements.channelViewTitle.textContent = labels[view] || "Channels";
    elements.channelViewCount.textContent = total === null
      ? "Loading…"
      : `${number(total)} ${total === 1 ? "channel" : "channels"}`;
  }

  async function loadBootstrap({ quiet = false } = {}) {
    state.requestTokens.bootstrap += 1;
    const token = state.requestTokens.bootstrap;
    try {
      const data = await api("/my-tv/api/bootstrap");
      if (token !== state.requestTokens.bootstrap) return;
      state.bootstrap = data;
      elements.statEnabled.textContent = number(data.stats.enabled_channels);
      elements.statTotal.textContent = number(data.stats.total_channels);
      elements.statGroups.textContent = number(data.stats.groups);
      elements.statSources.textContent = number(data.stats.repo_files);
      elements.statFavorites.textContent = number(data.stats.favorite_channels);
      elements.sourceRepoFiles.textContent = number(data.stats.repo_files);
      elements.sourceSyncedFiles.textContent = number(data.stats.imported_playlists);
      elements.sourcePendingFiles.textContent = number(data.stats.pending_files);
      updateSyncBanner(data.sync);
      updateHealthBanner(data.health);
      updateEpgStatus(data.epg);
      const guideStatus = data.epg?.last_success_at ? `guide ${relativeTime(data.epg.last_success_at)}` : "guide waiting";
      const healthStatus = data.health?.last_checked_at ? `checked ${relativeTime(data.health.last_checked_at)}` : "not checked yet";
      elements.tvTrustSummary.textContent = `${number(data.stats.enabled_channels)} ready · ${number(data.stats.favorite_channels)} favorites · ${healthStatus} · ${guideStatus}`;
      if (data.last_channel) {
        elements.resumeLastChannel.hidden = false;
        elements.resumeLastChannel.dataset.channelId = data.last_channel.id;
        elements.resumeLastChannel.textContent = `Resume ${data.last_channel.name}`;
        elements.playerEmptyText.textContent = `Last watched ${relativeTime(data.last_channel.last_watched_at)}.`;
      } else {
        elements.resumeLastChannel.hidden = true;
        elements.playerEmptyText.textContent = "Your favorites and recent channels stay close.";
      }
      if (!data.stats.repo_files && data.sync.state !== "running" && elements.tvConfig.dataset.autoCatalog === "true") {
        await startSync("fetch", [], true);
        return;
      }
      await loadChannels();
      if (data.sync.state === "running") pollSync();
      if (data.health.state === "running") pollHealth();
      else if (data.health.needs_check && data.stats.enabled_channels && elements.tvConfig.dataset.autoHealth === "true") startHealthCheck({ quiet: true });
      if (data.epg?.state === "running") pollEpg();
    } catch (error) { if (!quiet && !isAbortError(error)) toast(error.message, true); }
  }

  async function loadManageGroups() {
    const { token, signal } = beginAbortableRequest("manageGroups");
    const params = new URLSearchParams({ visibility: elements.bouquetVisibility.value });
    if (elements.groupSearch.value.trim()) params.set("q", elements.groupSearch.value.trim());
    const data = await api(`/my-tv/api/groups?${params}`, { signal });
    if (!isCurrentRequest("manageGroups", token)) return;
    state.manageGroups = data.groups;
    renderBouquets();
  }

  function renderBouquets() {
    elements.bouquetEmpty.hidden = state.manageGroups.length > 0;
    elements.bouquetList.hidden = state.manageGroups.length === 0;
    if (state.manageGroups.length === 0) {
      const labels = {
        on: ["No active groups", "Switch to All groups or activate one."],
        off: ["No inactive groups", "Switch to All groups or deactivate one."],
        all: ["No groups found", "Try another search."],
      };
      const [title, text] = labels[elements.bouquetVisibility.value];
      elements.bouquetEmptyTitle.textContent = title;
      elements.bouquetEmptyText.textContent = text;
    }
    elements.bouquetList.innerHTML = state.manageGroups.map((item) => {
      const saving = state.savingGroups.has(item.id);
      const confirming = state.pendingBulk?.groupId === item.id;
      const confirmingDeactivate = confirming && state.pendingBulk.action === "deactivate";
      return `<article class="tv-bouquet-row"${saving ? ' aria-busy="true"' : ""}>
      <div class="tv-bouquet-copy"><strong>${escapeHtml(item.name)}</strong><p>${number(item.channel_count)} channels · ${item.enabled_exceptions} forced on · ${item.disabled_exceptions} forced off</p></div>
      <button class="tv-switch" type="button" role="switch" aria-checked="${item.enabled}" aria-label="${item.enabled ? "Deactivate" : "Activate"} group ${escapeHtml(item.name)}" data-toggle-group="${item.id}"${saving ? " disabled" : ""}></button>
      <div class="tv-bouquet-actions" aria-label="Bulk channel actions"><button class="button button--secondary" type="button" data-group-action="enable" data-group-id="${item.id}"${saving ? " disabled" : ""}>Turn all on</button><button class="button button--danger" type="button" data-group-action="disable" data-group-id="${item.id}"${saving ? " disabled" : ""}>Turn all off</button><button class="button button--quiet" type="button" data-group-action="inherit" data-group-id="${item.id}"${saving ? " disabled" : ""}>Clear exceptions</button></div>
      ${confirming ? `<div class="tv-inline-confirm" role="alert"><p><strong>${confirmingDeactivate ? `Deactivate ${escapeHtml(item.name)}` : `Turn off ${number(item.channel_count)} channels`}?</strong><span>${confirmingDeactivate ? `${number(item.channel_count)} channels will leave your lineup.` : "This replaces the group's channel exceptions."} You can undo for 20 seconds.</span></p><div><button class="button button--danger" type="button" ${confirmingDeactivate ? "data-confirm-group-toggle" : 'data-confirm-group-action="disable"'} data-group-id="${item.id}">${confirmingDeactivate ? "Deactivate group" : "Turn all off"}</button><button class="button button--quiet" type="button" data-cancel-group-action>Cancel</button></div></div>` : ""}
    </article>`;
    }).join("");
  }

  async function loadChannels({ append = false } = {}) {
    if (append && (state.loadingChannels || state.page >= state.pages)) return;
    state.loadingChannels = true;
    const targetPage = append ? state.page + 1 : 1;
    elements.channelGrid.setAttribute("aria-busy", "true");
    elements.channelLoadStatus.hidden = !append;
    const { token, signal } = beginAbortableRequest("channels");
    const selectedView = elements.stateFilter.value;
    if (!append) updateChannelViewContext(selectedView, null);
    const selectedSort = selectedView === "recent"
      ? "recent"
      : selectedView === "favorites" || selectedView === "all"
        ? "name"
        : elements.tvConfig.dataset.defaultSort || "name";
    const params = new URLSearchParams({ page: targetPage, per_page: 100, state: selectedView, active_only: selectedView === "enabled" ? "true" : "false", favorites_first: elements.tvConfig.dataset.favoritesFirst || "false", sort: selectedSort });
    const query = elements.channelSearch.value.trim();
    if (query) params.set("q", query);
    try {
      const data = await api(`/my-tv/api/channels?${params}`, { signal });
      if (!isCurrentRequest("channels", token)) return;
      state.channels = append ? mergeChannels(state.channels, data.channels) : data.channels;
      state.page = data.pagination.page;
      state.pages = data.pagination.pages;
      state.total = data.pagination.total;
      syncChannelViewControls();
      updateChannelViewContext(selectedView, state.total);
      elements.loadMoreChannels.hidden = state.page >= state.pages;
      renderChannels();
    } finally {
      if (isCurrentRequest("channels", token)) {
        state.loadingChannels = false;
        elements.channelGrid.removeAttribute("aria-busy");
        elements.channelLoadStatus.hidden = true;
      }
    }
  }

  function guideMarkup(item) {
    if (!item.favorite) return `<small class="tv-channel-group" title="${escapeHtml(item.group_name)}">${escapeHtml(item.group_name)}</small>`;
    if (!item.epg?.now && !item.epg?.next) return `<small class="tv-channel-guide is-missing">Schedule unavailable</small>`;
    const current = item.epg.now ? `<small class="tv-channel-guide"><b>Now</b> ${escapeHtml(item.epg.now.title)}</small>` : "";
    const upcoming = item.epg.next ? `<small class="tv-channel-next"><b>${escapeHtml(clock(item.epg.next.starts_at))}</b> ${escapeHtml(item.epg.next.title)}</small>` : "";
    return `${current}${upcoming}`;
  }

  function logo(item, className = "tv-channel-logo") {
    const sourceName = String(item.name || "TV").trim();
    const initials = sourceName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0] || "")
      .join("")
      .toUpperCase() || "TV";
    const fallback = escapeHtml(initials);
    const fallbackLabel = escapeHtml(sourceName || "TV");
    return item.logo_url
      ? `<span class="${className}"><img src="${escapeHtml(item.logo_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-tv-fallback="${fallback}" data-tv-fallback-label="${fallbackLabel}"></span>`
      : `<span class="${className}" aria-label="${fallbackLabel}" title="${fallbackLabel}">${fallback}</span>`;
  }

  function renderChannels() {
    elements.channelEmpty.hidden = state.channels.length > 0;
    elements.channelGrid.hidden = state.channels.length === 0;
    elements.channelGrid.innerHTML = state.channels.map((item) => `<article class="tv-channel-card${item.enabled ? "" : " is-disabled"}${state.activeChannel?.id === item.id ? " is-playing" : ""}${state.requestedChannel?.id === item.id ? " is-requested" : ""}" role="listitem">
      <button class="tv-channel-main" type="button" aria-label="Play ${escapeHtml(item.name)}" data-play-channel="${item.id}" ${item.enabled ? "" : "disabled"}>${logo(item)}<span class="tv-channel-copy"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>${guideMarkup(item)}</span><span class="tv-row-play" aria-hidden="true"></span></button>
      <button class="tv-favorite-button" type="button" aria-label="${item.favorite ? "Remove" : "Add"} ${escapeHtml(item.name)} ${item.favorite ? "from" : "to"} favorites" aria-pressed="${item.favorite}" data-favorite-channel="${item.id}"${state.savingFavorites.has(item.id) ? ' disabled aria-busy="true"' : ""}>★</button>
    </article>`).join("");
  }

  async function loadManageChannels({ append = false } = {}) {
    if (append && (state.loadingManageChannels || state.manageChannelPage >= state.manageChannelPages)) return;
    state.loadingManageChannels = true;
    const targetPage = append ? state.manageChannelPage + 1 : 1;
    elements.manageChannelList.setAttribute("aria-busy", "true");
    elements.manageChannelLoadStatus.hidden = !append;
    const { token, signal } = beginAbortableRequest("manageChannels");
    const params = new URLSearchParams({ page: targetPage, per_page: 100, state: "all", sort: "name" });
    const query = elements.manageChannelSearch.value.trim();
    if (query) params.set("q", query);
    try {
      const data = await api(`/my-tv/api/channels?${params}`, { signal });
      if (!isCurrentRequest("manageChannels", token)) return;
      state.manageChannels = append ? mergeChannels(state.manageChannels, data.channels) : data.channels;
      state.manageChannelPage = data.pagination.page;
      state.manageChannelPages = data.pagination.pages;
      state.manageChannelTotal = data.pagination.total;
      elements.loadMoreManageChannels.hidden = state.manageChannelPage >= state.manageChannelPages;
      renderManageChannels();
    } finally {
      if (isCurrentRequest("manageChannels", token)) {
        state.loadingManageChannels = false;
        elements.manageChannelList.removeAttribute("aria-busy");
        elements.manageChannelLoadStatus.hidden = true;
      }
    }
  }

  function renderManageChannels() {
    elements.manageChannelEmpty.hidden = state.manageChannels.length > 0;
    elements.manageChannelList.hidden = state.manageChannels.length === 0;
    elements.manageChannelList.innerHTML = state.manageChannels.map((item) => `<article class="tv-manage-channel-row${item.enabled ? "" : " is-disabled"}" role="listitem">
      ${logo(item)}
      <span class="tv-channel-copy"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong><small title="${escapeHtml(item.group_name)}">${escapeHtml(item.group_name)} · ${item.enabled ? "Enabled" : "Disabled"}</small></span>
      <label class="tv-manage-channel-mode"><span class="sr-only">Channel availability for ${escapeHtml(item.name)}</span><select aria-label="Channel availability for ${escapeHtml(item.name)}" data-channel-override="${item.id}"><option value="default"${channelOverrideValue(item) === "default" ? " selected" : ""}>Use group default — currently ${item.resolved_default ? "ON" : "OFF"}</option><option value="on"${channelOverrideValue(item) === "on" ? " selected" : ""}>Always on</option><option value="off"${channelOverrideValue(item) === "off" ? " selected" : ""}>Always off</option></select></label>
    </article>`).join("");
  }

  async function startSync(mode, ids = [], quiet = false) {
    try {
      const result = await api("/my-tv/api/sync", { method: "POST", body: JSON.stringify({ mode, playlist_ids: ids }) });
      updateSyncBanner(result.sync);
      pollSync();
      if (!quiet) toast(mode === "fetch" ? "Updating packages used by your choices…" : mode === "catalog" ? "Refreshing source catalogue…" : "Import started…");
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
    if (status.last_checked_at) elements.healthStatusText.textContent = `Availability last checked ${relativeTime(status.last_checked_at)} · ${number(status.known_online)} online · ${number(status.known_offline)} unavailable.`;
    else elements.healthStatusText.textContent = "Availability has not been checked yet.";
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

  function updateEpgStatus(status) {
    if (!status) return;
    const suffix = status.last_success_at ? ` Last updated ${relativeTime(status.last_success_at)}.` : "";
    elements.epgStatusText.textContent = `${status.message || "Guide status unavailable."}${status.stale ? " Saved guide may be outdated." : ""}${suffix}`;
    elements.refreshEpg.disabled = status.state === "running";
  }

  async function startEpgRefresh({ quiet = false } = {}) {
    try {
      const result = await api("/my-tv/api/epg", { method: "POST", body: "{}" });
      updateEpgStatus(result.epg);
      pollEpg();
      if (!quiet) toast("Refreshing schedules for favorite channels…");
    } catch (error) {
      if (!quiet || !String(error.message).includes("already running")) toast(error.message, true);
    }
  }

  function pollEpg() {
    window.clearTimeout(state.epgTimer);
    const poll = async () => {
      try {
        const status = await api("/my-tv/api/epg");
        updateEpgStatus(status);
        if (status.state === "running") state.epgTimer = window.setTimeout(poll, 1800);
        else {
          if (status.state === "error") toast(status.error || status.message, true);
          await loadBootstrap({ quiet: true });
        }
      } catch (error) { toast(error.message, true); }
    };
    state.epgTimer = window.setTimeout(poll, 1000);
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
    elements.videoPlayer.hidden = true;
  }

  function showPlaybackStatus(message, error = false) {
    elements.playerEmpty.hidden = true;
    elements.playerLoadingText.textContent = message;
    elements.playerSpinner.hidden = error;
    elements.retryPlayback.hidden = !error;
    elements.playerLoading.classList.toggle("is-error", error);
    elements.playerLoading.hidden = false;
  }

  function playbackReady() {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
    state.activeChannel = state.requestedChannel || state.activeChannel;
    state.retryChannel = state.activeChannel || state.retryChannel;
    state.requestedChannel = null;
    elements.playerLoading.hidden = true;
    elements.playerLoading.classList.remove("is-error");
    elements.retryPlayback.hidden = true;
    elements.playerEmpty.hidden = true;
    elements.videoPlayer.hidden = false;
    elements.playerShell.classList.add("has-playback");
    if (state.activeChannel) {
      state.activeChannel.last_watched_at = new Date().toISOString();
      setNowPlaying(state.activeChannel, state.activeChannel.group_name, { live: true });
      elements.resumeLastChannel.hidden = false;
      elements.resumeLastChannel.dataset.channelId = state.activeChannel.id;
      elements.resumeLastChannel.textContent = `Resume ${state.activeChannel.name}`;
    }
    renderChannels();
    elements.videoPlayer.play().catch(() => {});
  }

  function playbackFailed(message) {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
    const retryChannel = state.requestedChannel || state.retryChannel || state.activeChannel;
    state.requestedChannel = null;
    state.activeChannel = null;
    state.retryChannel = retryChannel;
    elements.videoPlayer.onloadeddata = null;
    elements.videoPlayer.oncanplay = null;
    elements.videoPlayer.onplaying = null;
    elements.videoPlayer.onerror = null;
    elements.videoPlayer.pause();
    elements.videoPlayer.removeAttribute("src");
    elements.videoPlayer.load();
    elements.videoPlayer.hidden = true;
    elements.playerShell.classList.remove("has-playback");
    setNowPlaying(retryChannel, message);
    renderChannels();
    showPlaybackStatus(message, true);
  }

  async function playChannel(id) {
    const item = state.channels.find((channel) => channel.id === id)
      || (state.bootstrap?.last_channel?.id === id ? state.bootstrap.last_channel : null);
    if (!item) return;
    stopPlayback();
    state.requestedChannel = item;
    state.activeChannel = null;
    state.retryChannel = item;
    setNowPlaying(item, `${item.group_name} · Connecting…`);
    renderChannels();
    showPlaybackStatus("Opening live stream…");
    try {
      const playback = await api(`/my-tv/api/channels/${id}/playback`);
      elements.playerEmpty.hidden = true;
      const sourceNote = playback.source_count > 1 ? ` · ${playback.source_count} fallback sources` : "";
      setNowPlaying({ ...item, name: playback.name, logo_url: playback.logo_url || item.logo_url }, `${item.group_name} · Opening stream${sourceNote}…`);
      elements.videoPlayer.onloadeddata = playbackReady;
      elements.videoPlayer.oncanplay = playbackReady;
      elements.videoPlayer.onplaying = playbackReady;
      elements.videoPlayer.onerror = () => playbackFailed("No working source is available for this channel.");
      state.playbackTimer = window.setTimeout(() => {
        if (elements.videoPlayer.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) playbackReady();
        else playbackFailed("This channel did not respond within 15 seconds.");
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

  function activateTab(tab, { focus = false } = {}) {
    document.querySelectorAll('[role="tab"]').forEach((item) => {
      const selected = item === tab;
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(item.getAttribute("aria-controls"));
      if (panel) panel.hidden = !selected;
    });
    if (focus) tab.focus();
    if (tab.dataset.view === "manage") {
      Promise.all([loadManageGroups(), loadManageChannels()]).catch((error) => { if (!isAbortError(error)) toast(error.message, true); });
    }
  }

  async function refreshManage({ focusSelector = "" } = {}) {
    await Promise.all([loadBootstrap({ quiet: true }), loadManageGroups(), loadManageChannels()]);
    if (focusSelector) document.querySelector(focusSelector)?.focus();
  }

  async function toggleGroup(item) {
    if (!item || state.savingGroups.has(item.id)) return;
    const previous = item.enabled;
    const enabling = !previous;
    state.savingGroups.add(item.id);
    renderBouquets();
    try {
      const result = await api(`/my-tv/api/groups/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: enabling }) });
      await refreshManage({ focusSelector: `[data-toggle-group="${item.id}"]` });
      toast(`${number(result.affected_channels)} channels ${enabling ? "activated" : "deactivated"}.`, false, {
        label: "Undo",
        run: async () => {
          await api(`/my-tv/api/groups/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: previous }) });
          await refreshManage({ focusSelector: `[data-toggle-group="${item.id}"]` });
        },
      });
      if (enabling) startHealthCheck({ quiet: true, themeId: item.id });
    } finally {
      state.savingGroups.delete(item.id);
      renderBouquets();
    }
  }

  async function performBulkGroupAction(groupId, action) {
    const item = state.manageGroups.find((group) => group.id === groupId);
    if (!item || state.savingGroups.has(groupId)) return;
    state.pendingBulk = null;
    state.savingGroups.add(groupId);
    renderBouquets();
    try {
      const result = await api(`/my-tv/api/groups/${groupId}/channels`, { method: "POST", body: JSON.stringify({ action }) });
      const copy = action === "inherit" ? "Channel exceptions cleared." : `${number(result.affected_channels)} channels turned ${action === "enable" ? "on" : "off"}.`;
      await refreshManage({ focusSelector: `[data-group-action="${action}"][data-group-id="${groupId}"]` });
      toast(copy, false, {
        label: "Undo",
        run: async () => {
          await api(`/my-tv/api/groups/${groupId}/channels/undo`, { method: "POST", body: JSON.stringify({ token: result.undo_token }) });
          await refreshManage({ focusSelector: `[data-group-action="${action}"][data-group-id="${groupId}"]` });
        },
      });
    } finally {
      state.savingGroups.delete(groupId);
      renderBouquets();
    }
  }

  async function toggleFavorite(item, { restoreFocus = false } = {}) {
    if (!item || state.savingFavorites.has(item.id)) return;
    const nextValue = !item.favorite;
    state.savingFavorites.add(item.id);
    renderChannels();
    try {
      await api(`/my-tv/api/channels/${item.id}/favorite`, { method: "PATCH", body: JSON.stringify({ favorite: nextValue }) });
      item.favorite = nextValue;
      toast(nextValue ? "Saved to favorites. Schedule refresh queued." : "Removed from favorites.");
      await loadBootstrap({ quiet: true });
      if (nextValue) pollEpg();
    } finally {
      state.savingFavorites.delete(item.id);
      renderChannels();
      if (restoreFocus) document.querySelector(`[data-favorite-channel="${item.id}"]`)?.focus();
    }
  }

  document.addEventListener("click", async (event) => {
    const tab = event.target.closest('[role="tab"]');
    if (tab) {
      activateTab(tab);
      return;
    }
    const play = event.target.closest("[data-play-channel]");
    if (play) return playChannel(Number(play.dataset.playChannel));
    const channelView = event.target.closest("[data-channel-view]");
    if (channelView) {
      elements.stateFilter.value = channelView.dataset.channelView;
      state.page = 1;
      elements.channelGrid.scrollTop = 0;
      syncChannelViewControls();
      return loadChannels().catch((error) => { if (!isAbortError(error)) toast(error.message, true); });
    }
    const favorite = event.target.closest("[data-favorite-channel]");
    if (favorite) {
      const item = state.channels.find((channel) => channel.id === Number(favorite.dataset.favoriteChannel));
      if (!item) return;
      try {
        await toggleFavorite(item, { restoreFocus: true });
      } catch (error) { toast(error.message, true); }
      return;
    }
    const groupToggle = event.target.closest("[data-toggle-group]");
    if (groupToggle) {
      const item = state.manageGroups.find((group) => group.id === Number(groupToggle.dataset.toggleGroup));
      if (item?.enabled && item.channel_count >= 25) {
        state.pendingBulk = { groupId: item.id, action: "deactivate" };
        renderBouquets();
        document.querySelector(`[data-confirm-group-toggle][data-group-id="${item.id}"]`)?.focus();
        return;
      }
      try { await toggleGroup(item); } catch (error) { toast(error.message, true); }
      return;
    }
    if (event.target.closest("[data-cancel-group-action]")) {
      state.pendingBulk = null;
      renderBouquets();
      return;
    }
    const confirmedGroupAction = event.target.closest("[data-confirm-group-action]");
    if (confirmedGroupAction) {
      try { await performBulkGroupAction(Number(confirmedGroupAction.dataset.groupId), confirmedGroupAction.dataset.confirmGroupAction); }
      catch (error) { toast(error.message, true); }
      return;
    }
    const confirmedGroupToggle = event.target.closest("[data-confirm-group-toggle]");
    if (confirmedGroupToggle) {
      const item = state.manageGroups.find((group) => group.id === Number(confirmedGroupToggle.dataset.groupId));
      state.pendingBulk = null;
      try { await toggleGroup(item); } catch (error) { toast(error.message, true); }
      return;
    }
    const groupAction = event.target.closest("[data-group-action]");
    if (groupAction) {
      const groupId = Number(groupAction.dataset.groupId);
      const item = state.manageGroups.find((group) => group.id === groupId);
      if (groupAction.dataset.groupAction === "disable" && item?.channel_count >= 25) {
        state.pendingBulk = { groupId, action: "disable" };
        renderBouquets();
        document.querySelector(`[data-confirm-group-action][data-group-id="${groupId}"]`)?.focus();
        return;
      }
      try { await performBulkGroupAction(groupId, groupAction.dataset.groupAction); }
      catch (error) { toast(error.message, true); }
      return;
    }
    if (event.target.closest("#resumeLastChannel")) {
      return playChannel(Number(elements.resumeLastChannel.dataset.channelId));
    }
    if (event.target.closest("#loadMoreChannels")) return loadChannels({ append: true });
    if (event.target.closest("#loadMoreManageChannels")) return loadManageChannels({ append: true });
    if (event.target.closest("[data-empty-sync]")) startSync("fetch");
  });

  document.addEventListener("change", async (event) => {
    if (event.target === elements.stateFilter) {
      state.page = 1;
      elements.channelGrid.scrollTop = 0;
      syncChannelViewControls();
      try { await loadChannels(); } catch (error) { if (!isAbortError(error)) toast(error.message, true); }
    }
    if (event.target === elements.bouquetVisibility) {
      try { await loadManageGroups(); } catch (error) { if (!isAbortError(error)) toast(error.message, true); }
    }
    if (event.target.matches("[data-channel-override]")) {
      const item = state.manageChannels.find((channel) => channel.id === Number(event.target.dataset.channelOverride));
      if (!item) return;
      const enabled = ({ default: null, on: true, off: false })[event.target.value];
      const select = event.target;
      select.disabled = true;
      try {
        await api(`/my-tv/api/channels/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled }) });
        item.enabled_override = enabled;
        item.enabled = enabled === null ? item.resolved_default : enabled;
        select.disabled = false;
        select.closest(".tv-manage-channel-row")?.classList.toggle("is-disabled", !item.enabled);
        select.focus();
        toast(enabled === null ? "Channel now follows its group." : enabled ? "Channel is always on." : "Channel is always off.");
        loadBootstrap({ quiet: true });
      } catch (error) {
        toast(error.message, true);
        select.disabled = false;
        renderManageChannels();
        document.querySelector(`[data-channel-override="${item.id}"]`)?.focus();
      }
    }
  });

  elements.refreshCatalog.addEventListener("click", () => startSync("fetch"));
  elements.healthCheck.addEventListener("click", () => startHealthCheck());
  elements.refreshEpg.addEventListener("click", () => startEpgRefresh());
  elements.pictureInPicture.addEventListener("click", async () => {
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else await elements.videoPlayer.requestPictureInPicture();
    } catch (error) { toast(error.message || "Picture in picture is unavailable.", true); }
  });
  elements.retryPlayback.addEventListener("click", () => {
    const retryTarget = state.retryChannel || state.activeChannel;
    if (retryTarget) playChannel(retryTarget.id);
  });
  elements.groupSearch.addEventListener("input", debounce(() => loadManageGroups().catch((error) => { if (!isAbortError(error)) toast(error.message, true); })));
  elements.channelSearch.addEventListener("input", debounce(() => {
    state.page = 1;
    elements.channelGrid.scrollTop = 0;
    loadChannels().catch((error) => { if (!isAbortError(error)) toast(error.message, true); });
  }));
  elements.manageChannelSearch.addEventListener("input", debounce(() => {
    state.manageChannelPage = 1;
    elements.manageChannelList.scrollTop = 0;
    loadManageChannels().catch((error) => { if (!isAbortError(error)) toast(error.message, true); });
  }));
  elements.channelGrid.addEventListener("scroll", () => {
    const nearEnd = elements.channelGrid.scrollTop + elements.channelGrid.clientHeight >= elements.channelGrid.scrollHeight - 180;
    if (nearEnd) loadChannels({ append: true }).catch((error) => { if (!isAbortError(error)) toast(error.message, true); });
  });
  elements.manageChannelList.addEventListener("scroll", () => {
    const nearEnd = elements.manageChannelList.scrollTop + elements.manageChannelList.clientHeight >= elements.manageChannelList.scrollHeight - 180;
    if (nearEnd) loadManageChannels({ append: true }).catch((error) => { if (!isAbortError(error)) toast(error.message, true); });
  });
  elements.channelGrid.addEventListener("keydown", (event) => {
    const current = event.target.closest("[data-play-channel]");
    if (!current || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const buttons = [...elements.channelGrid.querySelectorAll("[data-play-channel]:not(:disabled)")];
    const index = buttons.indexOf(current);
    if (index < 0 || buttons.length === 0) return;
    let nextIndex = index;
    if (event.key === "ArrowDown") nextIndex = Math.min(index + 1, buttons.length - 1);
    if (event.key === "ArrowUp") nextIndex = Math.max(index - 1, 0);
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = buttons.length - 1;
    event.preventDefault();
    buttons[nextIndex].focus();
  });
  document.addEventListener("keydown", (event) => {
    const editable = event.target.matches("input, select, textarea, [contenteditable='true']");
    if (event.key === "/" && !editable) {
      event.preventDefault();
      const manageOpen = !document.getElementById("tv-panel-manage").hidden;
      (manageOpen ? elements.manageChannelSearch : elements.channelSearch).focus();
      return;
    }
    if (editable || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key.toLowerCase() === "f" && state.activeChannel) {
      event.preventDefault();
      toggleFavorite(state.activeChannel).catch((error) => toast(error.message, true));
    }
    if (event.key.toLowerCase() === "m" && !elements.videoPlayer.hidden) {
      event.preventDefault();
      elements.videoPlayer.muted = !elements.videoPlayer.muted;
      toast(elements.videoPlayer.muted ? "Muted." : "Sound on.");
    }
  });
  elements.playerEmpty.hidden = false;
  setNowPlaying(null, "Choose an enabled channel below.");
  const defaultView = elements.tvConfig.dataset.defaultView || "watch";
  if (defaultView === "favorites") elements.stateFilter.value = "favorites";
  if (defaultView === "manage") activateTab(document.getElementById("tv-tab-manage"));
  document.querySelector(".tv-tabs").addEventListener("keydown", (event) => {
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const currentIndex = tabs.findIndex((item) => item === event.target);
    if (currentIndex === -1) return;
    let nextIndex = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (currentIndex + 1) % tabs.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    activateTab(tabs[nextIndex], { focus: true });
  });

  document.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.dataset.tvFallback) {
      event.target.parentElement.textContent = event.target.dataset.tvFallback;
      if (event.target.dataset.tvFallbackLabel) {
        event.target.parentElement.setAttribute("aria-label", event.target.dataset.tvFallbackLabel);
        event.target.parentElement.setAttribute("title", event.target.dataset.tvFallbackLabel);
      }
    }
  }, true);
  loadBootstrap();
})();
