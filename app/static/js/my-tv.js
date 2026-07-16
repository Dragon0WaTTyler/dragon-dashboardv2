const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

const state = {
  bootstrap: null,
  groups: [],
  channels: [],
  selectedSources: new Set(),
  page: 1,
  pages: 1,
  totalChannels: 0,
  activeChannel: null,
  hls: null,
  syncTimer: null,
};

const elements = Object.fromEntries(
  [...document.querySelectorAll('[id]')].map((element) => [element.id, element])
);

async function api(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(url, { ...options, headers });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = payload?.message || payload?.description || payload || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return payload;
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value || 0);
}

function formatBytes(value) {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return 'Never imported';
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Never imported';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function toast(message, isError = false) {
  const item = document.createElement('div');
  item.className = `toast${isError ? ' is-error' : ''}`;
  item.textContent = message;
  elements.toastRegion.append(item);
  window.setTimeout(() => item.remove(), 4200);
}

async function loadBootstrap({ quiet = false } = {}) {
  try {
    const data = await api('/my-tv/api/bootstrap');
    state.bootstrap = data;
    renderStats(data.stats);
    renderSources(data.playlists);
    renderSourceFilter(data.playlists);
    renderSourceHealth(data);
    updateSyncBanner(data.sync);
    if (!data.playlists.length && data.sync.state !== 'running') {
      await startSync('catalog', [], true);
      return;
    }
    await Promise.all([loadGroups(), loadChannels()]);
    if (data.sync.state === 'running') beginSyncPolling();
  } catch (error) {
    renderSourceHealth(null, error.message);
    if (!quiet) toast(error.message, true);
  }
}

function renderStats(stats) {
  elements.statEnabled.textContent = formatNumber(stats.enabled_channels);
  elements.statTotal.textContent = formatNumber(stats.total_channels);
  elements.statGroups.textContent = formatNumber(stats.groups);
  elements.statSources.textContent = formatNumber(stats.imported_playlists);
}

function renderSourceHealth(data, error = null) {
  elements.sourceHealth.classList.toggle('is-good', Boolean(data && !error));
  elements.sourceHealth.classList.toggle('is-error', Boolean(error));
  const label = elements.sourceHealth.querySelector('span:last-child');
  if (error) label.textContent = 'Source unavailable';
  else if (data?.playlists?.length) label.textContent = `${data.playlists.filter((item) => item.available).length} source packages found`;
  else label.textContent = 'Source catalogue is empty';
}

function renderSourceFilter(playlists) {
  const current = elements.sourceFilter.value;
  const imported = playlists.filter((item) => item.imported && item.available);
  elements.sourceFilter.innerHTML = '<option value="">All active sources</option>' + imported.map((item) => (
    `<option value="${item.id}">${escapeHtml(item.name)} · ${formatNumber(item.channel_count)}</option>`
  )).join('');
  if (imported.some((item) => String(item.id) === current)) elements.sourceFilter.value = current;
}

function renderSources(playlists) {
  if (!playlists.length) {
    elements.sourceList.innerHTML = '<div class="empty-state compact-empty"><h3>No source packages found</h3><p>Use “Refresh source” to load the repository catalogue.</p></div>';
    return;
  }
  elements.sourceList.innerHTML = playlists.map((item) => {
    const selected = state.selectedSources.has(item.id);
    const statusClass = item.sync_status === 'ready' ? ' is-ready' : item.sync_status === 'error' ? ' is-error' : '';
    const status = item.imported ? item.sync_status : 'not imported';
    return `
      <article class="source-row${item.available ? '' : ' is-unavailable'}" data-source-id="${item.id}">
        <input class="source-select" type="checkbox" aria-label="Select ${escapeHtml(item.name)}" data-select-source="${item.id}" ${selected ? 'checked' : ''} ${item.available ? '' : 'disabled'}>
        <div class="source-copy">
          <strong title="${escapeHtml(item.filename)}">${escapeHtml(item.name)}</strong>
          <p>${formatBytes(item.size_bytes)} · ${item.imported ? `${formatNumber(item.channel_count)} channels · ${formatDate(item.last_synced_at)}` : 'Ready to import'}</p>
        </div>
        <span class="source-status${statusClass}">${escapeHtml(status)}</span>
        <button class="switch" type="button" role="switch" aria-checked="${item.enabled}" aria-label="${item.enabled ? 'Disable' : 'Enable'} source ${escapeHtml(item.name)}" data-toggle-source="${item.id}" ${item.imported ? '' : 'disabled'}></button>
      </article>`;
  }).join('');
  elements.importSelected.disabled = state.selectedSources.size === 0;
}

async function loadGroups() {
  const params = new URLSearchParams();
  if (elements.sourceFilter.value) params.set('playlist_id', elements.sourceFilter.value);
  if (elements.groupSearch.value) params.set('q', elements.groupSearch.value.trim());
  try {
    const data = await api(`/my-tv/api/groups?${params}`);
    state.groups = data.groups;
    renderGroupFilter(data.groups);
    renderBouquets(data.groups);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderGroupFilter(groups) {
  const current = elements.groupFilter.value;
  elements.groupFilter.innerHTML = '<option value="">All bouquets</option>' + groups.map((item) => (
    `<option value="${item.id}">${escapeHtml(item.name)} · ${formatNumber(item.channel_count)}</option>`
  )).join('');
  if (groups.some((item) => String(item.id) === current)) elements.groupFilter.value = current;
  else elements.groupFilter.value = '';
}

function renderBouquets(groups) {
  elements.bouquetEmpty.hidden = groups.length > 0;
  elements.bouquetList.hidden = groups.length === 0;
  elements.bouquetList.innerHTML = groups.map((item) => `
    <article class="bouquet-row" data-group-id="${item.id}">
      <div class="bouquet-copy">
        <strong>${escapeHtml(item.name)}</strong>
        <p>${escapeHtml(item.playlist_name)} · ${formatNumber(item.channel_count)} channels · ${item.enabled_exceptions} on / ${item.disabled_exceptions} off overrides</p>
      </div>
      <button class="switch" type="button" role="switch" aria-checked="${item.enabled}" aria-label="${item.enabled ? 'Disable' : 'Enable'} bouquet ${escapeHtml(item.name)}" data-toggle-group="${item.id}"></button>
      <div class="bouquet-actions" aria-label="Bulk channel actions">
        <button class="button button-secondary button-small" type="button" data-group-action="enable" data-group-id="${item.id}">All on</button>
        <button class="button button-danger button-small" type="button" data-group-action="disable" data-group-id="${item.id}">All off</button>
        <button class="button button-quiet button-small" type="button" data-group-action="inherit" data-group-id="${item.id}">Use default</button>
      </div>
    </article>
  `).join('');
}

async function loadChannels() {
  elements.channelGrid.setAttribute('aria-busy', 'true');
  const params = new URLSearchParams({ page: state.page, per_page: 36, state: elements.stateFilter.value });
  if (elements.sourceFilter.value) params.set('playlist_id', elements.sourceFilter.value);
  if (elements.groupFilter.value) params.set('group_id', elements.groupFilter.value);
  if (elements.channelSearch.value.trim()) params.set('q', elements.channelSearch.value.trim());
  try {
    const data = await api(`/my-tv/api/channels?${params}`);
    state.channels = data.channels;
    state.page = data.pagination.page;
    state.pages = data.pagination.pages;
    state.totalChannels = data.pagination.total;
    renderChannels();
    renderPagination();
  } catch (error) {
    elements.channelGrid.innerHTML = '';
    toast(error.message, true);
  } finally {
    elements.channelGrid.removeAttribute('aria-busy');
  }
}

function logoMarkup(item, className = 'channel-logo') {
  const initials = escapeHtml((item.name || 'TV').slice(0, 2).toUpperCase());
  if (!item.logo_url) return `<span class="${className}">${initials}</span>`;
  return `<span class="${className}"><img src="${escapeHtml(item.logo_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="${initials}"></span>`;
}

function renderChannels() {
  elements.channelEmpty.hidden = state.channels.length > 0;
  elements.channelGrid.hidden = state.channels.length === 0;
  elements.channelGrid.innerHTML = state.channels.map((item) => `
    <article class="channel-card${item.enabled ? '' : ' is-disabled'}${state.activeChannel?.id === item.id ? ' is-playing' : ''}" data-channel-id="${item.id}">
      ${logoMarkup(item)}
      <div class="channel-copy">
        <h3 title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</h3>
        <p title="${escapeHtml(item.group_name)}">${escapeHtml(item.group_name)}</p>
        <small>${item.enabled_override === null ? 'Bouquet default' : item.enabled_override ? 'Always on' : 'Always off'} · ${escapeHtml(item.stream_kind)}</small>
      </div>
      <button class="play-button" type="button" aria-label="Play ${escapeHtml(item.name)}" data-play-channel="${item.id}" ${item.enabled ? '' : 'disabled'}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/></svg>
      </button>
      <button class="switch channel-switch" type="button" role="switch" aria-checked="${item.enabled}" aria-label="${item.enabled ? 'Disable' : 'Enable'} ${escapeHtml(item.name)}" data-toggle-channel="${item.id}"></button>
    </article>
  `).join('');
}

function renderPagination() {
  elements.pagination.hidden = state.totalChannels === 0 || state.pages <= 1;
  elements.previousPage.disabled = state.page <= 1;
  elements.nextPage.disabled = state.page >= state.pages;
  elements.pageStatus.textContent = `Page ${formatNumber(state.page)} of ${formatNumber(state.pages)} · ${formatNumber(state.totalChannels)} channels`;
}

async function startSync(mode, playlistIds = [], quiet = false) {
  try {
    const result = await api('/my-tv/api/sync', {
      method: 'POST',
      body: JSON.stringify({ mode, playlist_ids: playlistIds }),
    });
    updateSyncBanner(result.sync);
    beginSyncPolling();
    if (!quiet) toast(mode === 'catalog' ? 'Refreshing source catalogue…' : 'Import started…');
  } catch (error) {
    if (!quiet) toast(error.message, true);
  }
}

function beginSyncPolling() {
  window.clearTimeout(state.syncTimer);
  const poll = async () => {
    try {
      const status = await api('/my-tv/api/sync');
      updateSyncBanner(status);
      if (status.state === 'running') state.syncTimer = window.setTimeout(poll, 1200);
      else {
        toast(status.state === 'complete' ? status.message : status.error || status.message, status.state === 'error');
        state.selectedSources.clear();
        await loadBootstrap({ quiet: true });
      }
    } catch (error) {
      toast(error.message, true);
    }
  };
  state.syncTimer = window.setTimeout(poll, 700);
}

function updateSyncBanner(status) {
  const running = status?.state === 'running';
  elements.syncBanner.hidden = !running;
  if (!status) return;
  elements.syncTitle.textContent = running ? 'Synchronising catalogue' : status.message;
  elements.syncMessage.textContent = status.error || status.message || 'Working…';
  elements.syncCount.textContent = status.total
    ? `${formatNumber(status.current)}/${formatNumber(status.total)} · ${formatNumber(status.channels)} channels`
    : '';
  for (const button of [elements.refreshCatalog, elements.syncLatest, elements.importSelected, elements.importAll]) {
    button.disabled = running || (button === elements.importSelected && state.selectedSources.size === 0);
  }
}

async function playChannel(channelId) {
  const item = state.channels.find((channel) => channel.id === channelId);
  if (!item) return;
  elements.playerLoading.hidden = false;
  stopPlayback();
  try {
    const playback = await api(`/my-tv/api/channels/${channelId}/playback`);
    state.activeChannel = item;
    elements.playerEmpty.hidden = true;
    elements.videoPlayer.style.display = 'block';
    elements.nowPlayingTitle.textContent = playback.name;
    elements.nowPlayingMeta.textContent = `${item.group_name} · ${item.playlist_name}`;
    elements.livePill.hidden = false;
    elements.nowLogo.innerHTML = playback.logo_url
      ? `<img src="${escapeHtml(playback.logo_url)}" alt="" referrerpolicy="no-referrer" data-fallback="TV">`
      : escapeHtml(playback.name.slice(0, 2).toUpperCase());

    if (playback.mode === 'hls' && window.Hls?.isSupported()) {
      state.hls = new window.Hls({ enableWorker: true, lowLatencyMode: true });
      state.hls.loadSource(playback.url);
      state.hls.attachMedia(elements.videoPlayer);
      state.hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
        elements.playerLoading.hidden = true;
        elements.videoPlayer.play().catch(() => {});
      });
      state.hls.on(window.Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) handlePlaybackError('This HLS stream could not be opened.');
      });
    } else {
      elements.videoPlayer.src = playback.url;
      elements.videoPlayer.load();
      elements.videoPlayer.addEventListener('canplay', () => {
        elements.playerLoading.hidden = true;
        elements.videoPlayer.play().catch(() => {});
      }, { once: true });
    }
    renderChannels();
  } catch (error) {
    handlePlaybackError(error.message);
  }
}

function stopPlayback() {
  if (state.hls) {
    state.hls.destroy();
    state.hls = null;
  }
  elements.videoPlayer.pause();
  elements.videoPlayer.removeAttribute('src');
  elements.videoPlayer.load();
}

function handlePlaybackError(message) {
  elements.playerLoading.hidden = true;
  toast(message, true);
}

function debounce(callback, wait = 300) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), wait);
  };
}

document.addEventListener('click', async (event) => {
  const tab = event.target.closest('[data-view]');
  if (tab) {
    document.querySelectorAll('[data-view]').forEach((item) => {
      const active = item === tab;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[data-panel]').forEach((panel) => {
      const active = panel.dataset.panel === tab.dataset.view;
      panel.classList.toggle('is-active', active);
      panel.hidden = !active;
    });
    if (tab.dataset.view === 'manage') await loadGroups();
    return;
  }

  const play = event.target.closest('[data-play-channel]');
  if (play) return playChannel(Number(play.dataset.playChannel));

  const toggleChannel = event.target.closest('[data-toggle-channel]');
  if (toggleChannel) {
    const item = state.channels.find((channel) => channel.id === Number(toggleChannel.dataset.toggleChannel));
    if (!item) return;
    try {
      await api(`/my-tv/api/channels/${item.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !item.enabled }) });
      await Promise.all([loadChannels(), loadBootstrap({ quiet: true })]);
    } catch (error) { toast(error.message, true); }
    return;
  }

  const toggleSource = event.target.closest('[data-toggle-source]');
  if (toggleSource) {
    const item = state.bootstrap.playlists.find((source) => source.id === Number(toggleSource.dataset.toggleSource));
    try {
      await api(`/my-tv/api/playlists/${item.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !item.enabled }) });
      toast(`${item.name} ${item.enabled ? 'disabled' : 'enabled'}`);
      await loadBootstrap({ quiet: true });
    } catch (error) { toast(error.message, true); }
    return;
  }

  const toggleGroup = event.target.closest('[data-toggle-group]');
  if (toggleGroup) {
    const item = state.groups.find((group) => group.id === Number(toggleGroup.dataset.toggleGroup));
    try {
      await api(`/my-tv/api/groups/${item.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !item.enabled }) });
      await Promise.all([loadGroups(), loadChannels(), loadBootstrap({ quiet: true })]);
    } catch (error) { toast(error.message, true); }
    return;
  }

  const groupAction = event.target.closest('[data-group-action]');
  if (groupAction) {
    try {
      await api(`/my-tv/api/groups/${groupAction.dataset.groupId}/channels`, {
        method: 'POST',
        body: JSON.stringify({ action: groupAction.dataset.groupAction }),
      });
      toast(groupAction.dataset.groupAction === 'inherit' ? 'Channel overrides cleared' : `All channels set ${groupAction.dataset.groupAction === 'enable' ? 'on' : 'off'}`);
      await Promise.all([loadGroups(), loadChannels(), loadBootstrap({ quiet: true })]);
    } catch (error) { toast(error.message, true); }
    return;
  }

  if (event.target.closest('[data-empty-sync]')) startSync('latest');
});

document.addEventListener('change', async (event) => {
  const sourceSelect = event.target.closest('[data-select-source]');
  if (sourceSelect) {
    const id = Number(sourceSelect.dataset.selectSource);
    if (sourceSelect.checked) state.selectedSources.add(id);
    else state.selectedSources.delete(id);
    elements.importSelected.disabled = state.selectedSources.size === 0;
    return;
  }
  if (event.target === elements.sourceFilter) {
    state.page = 1;
    await loadGroups();
    await loadChannels();
  }
  if (event.target === elements.groupFilter || event.target === elements.stateFilter) {
    state.page = 1;
    await loadChannels();
  }
});

elements.channelSearch.addEventListener('input', debounce(() => { state.page = 1; loadChannels(); }));
elements.groupSearch.addEventListener('input', debounce(loadGroups));
elements.refreshCatalog.addEventListener('click', () => startSync('catalog'));
elements.syncLatest.addEventListener('click', () => startSync('latest'));
elements.importSelected.addEventListener('click', () => startSync('selected', [...state.selectedSources]));
elements.importAll.addEventListener('click', () => {
  if (window.confirm('Import every available playlist? This source is large and the first import can take several minutes.')) startSync('all');
});
elements.previousPage.addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadChannels(); } });
elements.nextPage.addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; loadChannels(); } });

document.addEventListener('error', (event) => {
  if (event.target instanceof HTMLImageElement && event.target.dataset.fallback) {
    const parent = event.target.parentElement;
    parent.textContent = event.target.dataset.fallback;
  }
}, true);

elements.videoPlayer.addEventListener('error', () => {
  if (state.activeChannel) handlePlaybackError('The stream stopped or is no longer available upstream.');
});

loadBootstrap();
