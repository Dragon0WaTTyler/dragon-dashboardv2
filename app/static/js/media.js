const config = window.MEDIA_CONFIG || {};

const elements = {
  form: document.querySelector("#mediaSearchForm"),
  query: document.querySelector("#mediaSearch"),
  type: document.querySelector("#mediaType"),
  searchButton: document.querySelector("#searchButton"),
  notice: document.querySelector("#appNotice"),
  searchSection: document.querySelector("#searchSection"),
  searchTitle: document.querySelector("#searchTitle"),
  searchCount: document.querySelector("#searchCount"),
  searchResults: document.querySelector("#searchResults"),
  searchEmpty: document.querySelector("#searchEmpty"),
  libraryGrid: document.querySelector("#libraryGrid"),
  libraryCount: document.querySelector("#libraryCount"),
  libraryEmpty: document.querySelector("#libraryEmpty"),
  dialog: document.querySelector("#releaseDialog"),
  dialogTitle: document.querySelector("#releaseDialogTitle"),
  dialogMeta: document.querySelector("#releaseDialogMeta"),
  closeDialog: document.querySelector("#closeReleaseDialog"),
  episodePicker: document.querySelector("#episodePicker"),
  seasonSelect: document.querySelector("#seasonSelect"),
  episodeSelect: document.querySelector("#episodeSelect"),
  findEpisodeReleases: document.querySelector("#findEpisodeReleases"),
  releaseStatus: document.querySelector("#releaseStatus"),
  releaseList: document.querySelector("#releaseList"),
  playerSection: document.querySelector("#playerSection"),
  playerTitle: document.querySelector("#playerTitle"),
  playerMeta: document.querySelector("#playerMeta"),
  player: document.querySelector("#mediaPlayer"),
  playerState: document.querySelector("#playerState"),
  playerStats: document.querySelector("#playerStats"),
  stopPlayer: document.querySelector("#stopPlayer"),
};

const state = {
  library: [],
  selectedMedia: null,
  torrentClient: null,
  activeTorrent: null,
  activePageId: null,
  watchedReported: false,
};

document.addEventListener("DOMContentLoaded", bootstrap);
elements.form.addEventListener("submit", handleSearch);
elements.closeDialog.addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) elements.dialog.close();
});
elements.seasonSelect.addEventListener("change", loadEpisodes);
elements.findEpisodeReleases.addEventListener("click", loadSelectedEpisodeReleases);
elements.stopPlayer.addEventListener("click", stopPlayback);
elements.player.addEventListener("playing", handleSuccessfulPlayback, { passive: true });

async function bootstrap() {
  elements.libraryGrid.setAttribute("aria-busy", "true");
  try {
    const data = await api("/media/api/bootstrap");
    state.library = data.library || [];
    renderLibrary();
    if (data.error) {
      showNotice(data.error, "error");
    } else if (!data.notion?.configured) {
      showNotice("Add NOTION_TOKEN and NOTION_DATABASE_ID (or NOTION_DATA_SOURCE_ID) to load your library.", "warning");
    } else if (data.notion.missing_properties?.length) {
      showNotice(`Notion is connected. Add these properties for complete write-back: ${data.notion.missing_properties.join(", ")}.`, "warning");
    } else if (!data.tmdb_configured) {
      showNotice("Your Notion library is connected, but TMDB is not configured for discovery and metadata.", "warning");
    } else if (!data.release_provider_configured) {
      showNotice("Your library is ready. Configure Jackett before searching for releases.", "warning");
    } else if (!data.player_configured) {
      showNotice("Your library is ready, but the selected media player is not configured.", "warning");
    }
  } catch (error) {
    showNotice(error.message, "error");
    renderLibrary();
  } finally {
    elements.libraryGrid.setAttribute("aria-busy", "false");
  }
}

async function handleSearch(event) {
  event.preventDefault();
  const query = elements.query.value.trim();
  if (query.length < 2) {
    showNotice("Enter at least two characters.", "warning");
    elements.query.focus();
    return;
  }
  setBusy(elements.searchButton, true, "Searching…");
  elements.searchSection.hidden = false;
  elements.searchTitle.textContent = `Results for “${query}”`;
  elements.searchCount.textContent = "Searching Notion and TMDB…";
  elements.searchResults.replaceChildren(...skeletonCards(5));
  elements.searchEmpty.hidden = true;
  try {
    const params = new URLSearchParams({ q: query, type: elements.type.value });
    const data = await api(`/media/api/search?${params}`);
    renderSearchResults(data);
    if (data.library_error) showNotice(data.library_error, "error");
  } catch (error) {
    elements.searchResults.replaceChildren();
    elements.searchCount.textContent = "Search failed";
    elements.searchEmpty.hidden = false;
    showNotice(error.message, "error");
  } finally {
    setBusy(elements.searchButton, false, "Search");
  }
}

function renderLibrary() {
  elements.libraryGrid.replaceChildren(...state.library.map((item) => mediaCard(item, true)));
  elements.libraryCount.textContent = `${state.library.length} ${state.library.length === 1 ? "title" : "titles"}`;
  elements.libraryEmpty.hidden = state.library.length !== 0;
}

function renderSearchResults(data) {
  const localByKey = new Map(state.library.map((item) => [mediaKey(item), item]));
  const cards = [];
  const shown = new Set();
  for (const item of data.library || []) {
    cards.push(mediaCard(item, true));
    shown.add(mediaKey(item));
  }
  for (const item of data.discovery || []) {
    const local = localByKey.get(mediaKey(item));
    if (local && shown.has(mediaKey(item))) continue;
    cards.push(mediaCard(local || item, Boolean(local)));
    shown.add(mediaKey(item));
  }
  elements.searchResults.replaceChildren(...cards);
  elements.searchCount.textContent = `${cards.length} ${cards.length === 1 ? "result" : "results"}`;
  elements.searchEmpty.hidden = cards.length !== 0;
}

function mediaCard(item, inLibrary) {
  const card = node("article", "media-card");
  const poster = node("div", "poster");
  if (item.poster_url) {
    const image = node("img");
    image.src = item.poster_url;
    image.alt = `${item.title || "Media"} poster`;
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    poster.append(image);
  } else {
    const placeholder = node("div", "poster-placeholder");
    placeholder.append(icon("image"));
    poster.append(placeholder);
  }
  const badge = node("span", "media-badge", item.media_type === "tv" ? "Series" : "Movie");
  poster.append(badge);

  const body = node("div", "media-card-body");
  body.append(node("h3", "", item.title || "Untitled"));
  const meta = [item.year, item.watched ? "Watched" : inLibrary ? "In Notion" : "Not in Notion"].filter(Boolean).join(" · ");
  const metaNode = node("p", `media-meta${item.watched ? " watched-mark" : ""}`, meta);
  body.append(metaNode);
  if (item.overview) body.append(node("p", "media-overview", item.overview));

  const actions = node("div", "card-actions");
  if (inLibrary && item.magnet_uri) {
    const play = button(item.media_type === "tv" && item.episode ? `Play S${pad(item.season)}E${pad(item.episode)}` : "Play saved", "button-primary");
    play.addEventListener("click", () => startPlayback(item, item.playback || { mode: config.playerMode, magnet_uri: item.magnet_uri }));
    actions.append(play);
  }
  const find = button(item.media_type === "tv" ? "Choose episode" : "Find release", inLibrary && item.magnet_uri ? "button-secondary" : "button-primary");
  find.addEventListener("click", () => openReleasePicker(item));
  actions.append(find);
  if (inLibrary && item.notion_page_id && !item.watched) {
    const watched = button("Mark watched", "button-secondary");
    watched.addEventListener("click", () => markWatched(item.notion_page_id, watched));
    actions.append(watched);
  }
  body.append(actions);
  card.append(poster, body);
  return card;
}

async function openReleasePicker(item) {
  state.selectedMedia = item;
  elements.dialogTitle.textContent = item.title || "Release options";
  elements.dialogMeta.textContent = [item.media_type === "tv" ? "Series" : "Movie", item.year].filter(Boolean).join(" · ");
  elements.releaseList.replaceChildren();
  elements.releaseStatus.textContent = "";
  elements.episodePicker.hidden = item.media_type !== "tv";
  if (!elements.dialog.open) elements.dialog.showModal();
  if (item.media_type === "tv") {
    await loadSeasons();
  } else {
    await loadReleases({ type: "movie", tmdb_id: item.tmdb_id });
  }
}

async function loadSeasons() {
  elements.releaseStatus.textContent = "Loading seasons from TMDB…";
  elements.seasonSelect.disabled = true;
  elements.episodeSelect.disabled = true;
  try {
    const data = await api(`/media/api/tv/${state.selectedMedia.tmdb_id}/seasons`);
    const seasons = (data.seasons || []).filter((season) => season.season_number > 0);
    elements.seasonSelect.replaceChildren(...seasons.map((season) => option(season.season_number, `${season.name} · ${season.episode_count} episodes`)));
    const preferred = state.selectedMedia.season;
    if (preferred && seasons.some((season) => season.season_number === preferred)) elements.seasonSelect.value = String(preferred);
    elements.seasonSelect.disabled = seasons.length === 0;
    await loadEpisodes();
  } catch (error) {
    elements.releaseStatus.textContent = error.message;
  }
}

async function loadEpisodes() {
  const season = Number(elements.seasonSelect.value);
  if (!season) return;
  elements.episodeSelect.disabled = true;
  elements.releaseStatus.textContent = `Loading season ${season} episodes…`;
  elements.releaseList.replaceChildren();
  try {
    const data = await api(`/media/api/tv/${state.selectedMedia.tmdb_id}/seasons/${season}/episodes`);
    const episodes = data.episodes || [];
    elements.episodeSelect.replaceChildren(...episodes.map((episode) => option(episode.episode_number, `E${pad(episode.episode_number)} · ${episode.name}`)));
    const preferred = state.selectedMedia.episode;
    if (preferred && episodes.some((episode) => episode.episode_number === preferred)) elements.episodeSelect.value = String(preferred);
    elements.episodeSelect.disabled = episodes.length === 0;
    elements.releaseStatus.textContent = episodes.length ? "Choose an episode, then find its releases." : "No episodes are available for this season.";
  } catch (error) {
    elements.releaseStatus.textContent = error.message;
  }
}

async function loadSelectedEpisodeReleases() {
  const season = Number(elements.seasonSelect.value);
  const episode = Number(elements.episodeSelect.value);
  if (!season || !episode) {
    elements.releaseStatus.textContent = "Choose a season and episode first.";
    return;
  }
  await loadReleases({ type: "tv", tmdb_id: state.selectedMedia.tmdb_id, season, episode });
}

async function loadReleases(params) {
  elements.releaseStatus.textContent = "Searching configured Jackett indexers…";
  elements.releaseList.replaceChildren();
  setBusy(elements.findEpisodeReleases, true, "Searching…");
  try {
    const data = await api(`/media/api/releases?${new URLSearchParams(params)}`);
    const results = data.results || [];
    elements.releaseStatus.textContent = results.length ? `${results.length} releases for ${data.release_query}` : `No releases with enough seeders for ${data.release_query}.`;
    elements.releaseList.replaceChildren(...results.map((release) => releaseRow(release, params)));
  } catch (error) {
    elements.releaseStatus.textContent = error.message;
  } finally {
    setBusy(elements.findEpisodeReleases, false, "Find releases");
  }
}

function releaseRow(release, selection) {
  const row = node("article", "release-row");
  const copy = node("div");
  copy.append(node("strong", "", release.title));
  const meta = node("div", "release-meta");
  meta.append(node("span", "seeders", `${release.seeders.toLocaleString()} seeders`));
  meta.append(node("span", "", formatBytes(release.size)));
  meta.append(node("span", "", release.tracker || "Unknown tracker"));
  copy.append(meta);
  const play = button("Add & play", "button-primary");
  play.addEventListener("click", () => addAndPlay(release, selection, play));
  row.append(copy, play);
  return row;
}

async function addAndPlay(release, selection, control) {
  setBusy(control, true, "Saving…");
  try {
    const data = await api("/media/api/library", {
      method: "POST",
      body: JSON.stringify({
        media_type: selection.type,
        tmdb_id: selection.tmdb_id,
        season: selection.season || null,
        episode: selection.episode || null,
        magnet_uri: release.magnet_uri,
        release_title: release.title,
      }),
    });
    const item = data.item;
    state.library = [item, ...state.library.filter((entry) => mediaKey(entry) !== mediaKey(item))];
    renderLibrary();
    elements.dialog.close();
    await startPlayback(item, item.playback || { mode: config.playerMode, magnet_uri: release.magnet_uri });
  } catch (error) {
    elements.releaseStatus.textContent = error.message;
    setBusy(control, false, "Add & play");
  }
}

async function startPlayback(item, playback) {
  stopPlayback(false);
  state.activePageId = item.notion_page_id;
  state.watchedReported = Boolean(item.watched);
  elements.playerTitle.textContent = item.title || "Now playing";
  elements.playerMeta.textContent = item.media_type === "tv" && item.episode ? `Season ${item.season}, episode ${item.episode}` : item.year || "";
  elements.playerSection.hidden = false;
  elements.playerState.hidden = false;
  elements.playerStats.textContent = "Preparing playback…";
  elements.playerSection.scrollIntoView({ behavior: "smooth", block: "start" });

  if (playback.mode === "external") {
    elements.playerStats.textContent = "Opening your configured external player…";
    window.open(playback.url, "_blank", "noopener,noreferrer");
    return;
  }
  try {
    await startWebTorrent(playback.magnet_uri);
  } catch (error) {
    elements.playerStats.textContent = error.message;
    showNotice(error.message, "error");
  }
}

async function startWebTorrent(magnet) {
  await loadScript(config.webtorrentCdnUrl);
  if (!window.WebTorrent) throw new Error("WebTorrent could not be loaded.");
  if (!window.WebTorrent.WEBRTC_SUPPORT) throw new Error("This browser does not support WebRTC torrent playback.");

  const client = new window.WebTorrent();
  state.torrentClient = client;
  client.on("error", (error) => {
    elements.playerStats.textContent = `Torrent error: ${error.message}`;
  });

  let controller = null;
  if ("serviceWorker" in navigator && typeof client.createServer === "function") {
    await navigator.serviceWorker.register(config.serviceWorkerUrl, { scope: "/media/" });
    const registration = await navigator.serviceWorker.ready;
    controller = registration.active || navigator.serviceWorker.controller;
    if (controller) client.createServer({ controller });
  }

  await new Promise((resolve, reject) => {
    let settled = false;
    client.add(magnet, (torrent) => {
      state.activeTorrent = torrent;
      const files = torrent.files.filter((file) => /\.(mp4|webm|m4v|mov|mkv)$/i.test(file.name));
      const file = files.sort((a, b) => b.length - a.length)[0];
      if (!file) {
        reject(new Error("This release does not contain a browser-playable video file."));
        return;
      }
      torrent.on("download", updateTorrentStats);
      torrent.on("done", updateTorrentStats);
      elements.playerStats.textContent = `Streaming ${file.name}`;
      try {
        const result = typeof file.streamTo === "function" && controller
          ? file.streamTo(elements.player)
          : typeof file.renderTo === "function"
            ? file.renderTo(elements.player)
            : null;
        if (!result && typeof file.streamTo !== "function" && typeof file.renderTo !== "function") {
          reject(new Error("The loaded WebTorrent build cannot attach video playback."));
          return;
        }
        Promise.resolve(result).then(() => {
          if (!settled) {
            settled = true;
            resolve();
          }
        }).catch(reject);
      } catch (error) {
        reject(error);
      }
    });
  });
}

function updateTorrentStats() {
  const torrent = state.activeTorrent;
  if (!torrent) return;
  const progress = Math.round((torrent.progress || 0) * 100);
  elements.playerStats.textContent = `${progress}% buffered · ${formatRate(torrent.downloadSpeed)} · ${torrent.numPeers || 0} peers`;
}

async function handleSuccessfulPlayback() {
  elements.playerState.hidden = true;
  if (state.activePageId && !state.watchedReported) {
    state.watchedReported = true;
    try {
      await markWatched(state.activePageId);
    } catch (error) {
      state.watchedReported = false;
      showNotice(`Playback started, but Notion was not updated: ${error.message}`, "warning");
    }
  }
}

async function markWatched(pageId, control = null) {
  if (control) setBusy(control, true, "Saving…");
  const data = await api(`/media/api/library/${pageId}/watched`, {
    method: "POST",
    body: JSON.stringify({ watched: true }),
  });
  state.library = state.library.map((item) => item.notion_page_id === pageId ? data.item : item);
  renderLibrary();
  return data.item;
}

function stopPlayback(hide = true) {
  elements.player.pause();
  elements.player.removeAttribute("src");
  elements.player.load();
  if (state.torrentClient) {
    try { state.torrentClient.destroy(); } catch (_) { /* already stopped */ }
  }
  state.torrentClient = null;
  state.activeTorrent = null;
  state.activePageId = null;
  state.watchedReported = false;
  if (hide) elements.playerSection.hidden = true;
}

async function api(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (options.method && options.method !== "GET") headers.set("X-CSRF-Token", config.csrfToken);
  const response = await fetch(url, { ...options, headers });
  let data;
  try { data = await response.json(); } catch (_) { data = {}; }
  if (!response.ok) throw new Error(data.error || data.message || `Request failed with HTTP ${response.status}`);
  return data;
}

function showNotice(message, type = "") {
  elements.notice.textContent = message;
  elements.notice.className = `notice${type ? ` is-${type}` : ""}`;
  elements.notice.hidden = false;
}

function setBusy(control, busy, label) {
  if (!control) return;
  control.disabled = busy;
  control.textContent = label;
}

function button(label, variant) {
  const control = node("button", `button ${variant}`, label);
  control.type = "button";
  return control;
}

function option(value, label) {
  const item = node("option", "", label);
  item.value = String(value);
  return item;
}

function node(tag, className = "", text = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== null && text !== undefined) element.textContent = String(text);
  return element;
}

function icon(kind) {
  const wrapper = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  wrapper.setAttribute("viewBox", "0 0 24 24");
  wrapper.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", kind === "image" ? "M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13ZM4 16l4-4 3 3 2-2 7 7M15.5 8.5h.01" : "");
  wrapper.append(path);
  return wrapper;
}

function skeletonCards(count) {
  return Array.from({ length: count }, () => {
    const card = node("div", "media-card");
    const poster = node("div", "poster");
    const body = node("div", "media-card-body");
    body.append(node("p", "media-meta", "Loading…"));
    card.append(poster, body);
    return card;
  });
}

function mediaKey(item) {
  return `${item.media_type}:${item.tmdb_id}`;
}

function pad(value) {
  return String(value || 0).padStart(2, "0");
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "Unknown size";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

function formatRate(bytes) {
  return `${formatBytes(bytes)}/s`;
}

let scriptPromise = null;
function loadScript(url) {
  if (window.WebTorrent) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.onload = resolve;
    script.onerror = () => reject(new Error("Could not load the WebTorrent player bundle."));
    document.head.append(script);
  });
  return scriptPromise;
}
