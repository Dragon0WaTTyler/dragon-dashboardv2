(() => {
  const player = document.querySelector("[data-movie-player]");
  if (!player) return;

  const source = player.querySelector("[data-player-source]");
  const launch = player.querySelector("[data-player-launch]");
  const launchTitle = player.querySelector("[data-player-launch-title]");
  const badge = player.querySelector("[data-player-badge]");
  const frame = player.querySelector("[data-player-frame]");
  const mediaShell = player.querySelector("[data-player-shell]");
  const video = player.querySelector("[data-player-video]");
  const status = player.querySelector("[data-player-status]");
  const chromeStatus = player.querySelector("[data-player-chrome-status]");
  const controls = player.querySelector("[data-player-controls]");
  const reload = player.querySelector("[data-player-reload]");
  const open = player.querySelector("[data-player-open]");
  const stop = player.querySelector("[data-player-stop]");
  const quickToggles = Array.from(player.querySelectorAll("[data-player-quick-toggle]"));
  const quickBack = player.querySelector("[data-player-quick-back]");
  const quickForward = player.querySelector("[data-player-quick-forward]");
  const quickMute = player.querySelector("[data-player-quick-mute]");
  const quickFullscreen = player.querySelector("[data-player-quick-fullscreen]");
  const playerBack = player.querySelector("[data-player-back]");
  const sourceReturn = player.querySelector("[data-player-source-return]");
  const playIcon = player.querySelector("[data-player-play-icon]");
  const centerIcon = player.querySelector("[data-player-center-icon]");
  const muteIcon = player.querySelector("[data-player-mute-icon]");
  const timeline = player.querySelector("[data-player-timeline]");
  const volume = player.querySelector("[data-player-volume]");
  const timeLabel = player.querySelector("[data-player-time]");
  const captionToggle = player.querySelector("[data-player-caption-toggle]");
  const netflixEpisode = player.querySelector("[data-player-netflix-episode]");
  const subtitleStatus = player.querySelector("[data-subtitle-status]");
  const subtitlePanel = player.querySelector("[data-player-subtitle-panel]");
  const subtitleClose = player.querySelector("[data-player-subtitle-close]");
  const subtitleBack = player.querySelector("[data-player-subtitle-back]");
  const subtitleOpenAppearance = player.querySelector("[data-player-subtitle-open-appearance]");
  const subtitleList = player.querySelector("[data-player-subtitle-list]");
  const subtitleScreens = Array.from(player.querySelectorAll("[data-player-subtitle-screen]"));
  const subtitleOff = player.querySelector("[data-player-subtitle-off]");
  const captionLayer = player.querySelector("[data-player-captions]");
  const captionChip = player.querySelector("[data-player-caption-chip]");
  const captionText = player.querySelector("[data-player-caption-text]");
  const subtitleSize = player.querySelector("[data-player-subtitle-size]");
  const subtitleSizeLabel = player.querySelector("[data-player-subtitle-size-label]");
  const subtitleBlur = player.querySelector("[data-player-subtitle-blur]");
  const subtitleBlurLabel = player.querySelector("[data-player-subtitle-blur-label]");
  const subtitleOffset = player.querySelector("[data-player-subtitle-offset]");
  const subtitleOffsetLabel = player.querySelector("[data-player-subtitle-offset-label]");
  const subtitleFont = player.querySelector("[data-player-subtitle-font]");
  const subtitleColors = Array.from(player.querySelectorAll("[data-player-subtitle-colors] button"));
  const subtitleReset = player.querySelector("[data-player-subtitle-reset]");
  const packBrowser = player.querySelector("[data-player-pack-browser]");
  const packHeading = player.querySelector("[data-player-pack-heading]");
  const packEpisode = player.querySelector("[data-player-pack-episode]");
  const packStatus = player.querySelector("[data-player-pack-status]");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const subtitlePrefsKey = "dragon:subtitle-style:v1";
  let sourceUrl = "";
  let localSession = null;
  let pollTimer = 0;
  let activeKind = "";
  let subtitleOptions = null;
  let subtitleRequest = null;
  let subtitleOptionsKey = "";
  let subtitleRequestToken = 0;
  let watchReported = false;
  let activeSelection = { season: null, episode: null, episodeTitle: "", runtimeSeconds: null };
  let packRequestToken = 0;
  let videoPaintCheckTimer = 0;
  let controlsHideTimer = 0;
  let subtitlePanelOpen = false;
  let selectedSubtitleIndex = -1;
  let subtitleEntries = [];
  let subtitlePreferences = {
    size: 30,
    blur: 0,
    offset: 0,
    color: "#ffffff",
    font: "plex",
  };
  const effectiveCurrentTime = () => {
    const playbackOffset = Number(localSession?.playbackOffset || 0);
    return playbackOffset + Number(video.currentTime || 0);
  };
  const transcodePlaybackUrl = () => {
    if (!localSession?.transcodeUrl) return "";
    const url = new URL(localSession.transcodeUrl, window.location.origin);
    const start = Number(localSession.playbackOffset || 0);
    const nonce = Number(localSession.transcodeNonce || 0);
    if (start > 0) url.searchParams.set("start", start.toFixed(3));
    if (nonce > 0) url.searchParams.set("v", String(nonce));
    return url.toString();
  };

  const selectedKind = () => source.selectedOptions[0]?.dataset.kind || "vidsrc";
  const selectedOption = () => source.selectedOptions[0] || null;
  const selectedSourceMeta = () => {
    const option = selectedOption();
    if (!option || option.dataset.kind !== "local") return null;
    const season = Number(option.dataset.sourceSeason || 0) || null;
    const episode = Number(option.dataset.sourceEpisode || 0) || null;
    return {
      sourceId: option.value,
      seasonPack: option.dataset.sourceSeasonPack === "true",
      season,
      episode,
      releaseMode: String(option.dataset.sourceReleaseMode || ""),
      label: option.textContent?.trim() || "Local source",
    };
  };
  const fillTemplate = (template, values = []) => {
    if (!template || typeof template !== "string") return null;
    return values.reduce((result, value) => {
      if (value === null || value === undefined || value === "") return result;
      return result.replace("999999999", encodeURIComponent(value));
    }, template);
  };
  const setStatus = (message) => {
    status.textContent = message;
    if (chromeStatus && message) chromeStatus.textContent = message;
  };
  const setPlayerState = (state, message = "") => {
    player.dataset.playbackState = state;
    if (activeKind === "local") {
      badge.textContent = `Local · ${state.charAt(0).toUpperCase()}${state.slice(1)}`;
    }
    if (message) setStatus(message);
  };
  const setWatchMode = (_enabled) => {
    player.classList.remove("is-watch-mode");
  };
  const setSubtitleStatus = (message) => {
    if (!subtitleStatus) return;
    subtitleStatus.textContent = message;
  };
  const subtitleFontFamily = (value) => ({
    plex: "\"IBM Plex Sans\", sans-serif",
    inter: "Inter, \"IBM Plex Sans\", sans-serif",
    serif: "\"Merriweather\", Georgia, serif",
    mono: "\"IBM Plex Mono\", monospace",
  }[value] || "\"IBM Plex Sans\", sans-serif");
  const loadSubtitlePreferences = () => {
    try {
      const raw = window.localStorage.getItem(subtitlePrefsKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (typeof parsed !== "object" || !parsed) return;
      subtitlePreferences = {
        ...subtitlePreferences,
        ...parsed,
      };
    } catch (_error) {
      // Ignore broken local storage and continue with defaults.
    }
  };
  const saveSubtitlePreferences = () => {
    try {
      window.localStorage.setItem(subtitlePrefsKey, JSON.stringify(subtitlePreferences));
    } catch (_error) {
      // Local storage is a nice-to-have only.
    }
  };
  const setSubtitleScreen = (screen) => {
    subtitleScreens.forEach((element) => {
      const active = element.dataset.playerSubtitleScreen === screen;
      element.hidden = !active;
    });
  };
  const setSubtitlePanelOpen = (open) => {
    subtitlePanelOpen = Boolean(open);
    if (!subtitlePanel) return;
    subtitlePanel.hidden = !subtitlePanelOpen;
    subtitlePanel.setAttribute("aria-hidden", subtitlePanelOpen ? "false" : "true");
    captionToggle?.setAttribute("aria-pressed", subtitlePanelOpen ? "true" : "false");
    if (subtitlePanelOpen) {
      mediaShell?.setAttribute("data-controls-visible", "true");
      setSubtitleScreen("list");
    }
  };
  const updateSubtitlePreferenceLabels = () => {
    if (subtitleSize && Number(subtitleSize.value) !== Number(subtitlePreferences.size)) subtitleSize.value = String(subtitlePreferences.size);
    if (subtitleBlur && Number(subtitleBlur.value) !== Number(subtitlePreferences.blur)) subtitleBlur.value = String(subtitlePreferences.blur);
    if (subtitleOffset && Number(subtitleOffset.value) !== Number(subtitlePreferences.offset)) subtitleOffset.value = String(subtitlePreferences.offset);
    if (subtitleFont) subtitleFont.value = subtitlePreferences.font;
    if (subtitleSizeLabel) subtitleSizeLabel.textContent = `${subtitlePreferences.size}px`;
    if (subtitleBlurLabel) subtitleBlurLabel.textContent = `${Math.round((subtitlePreferences.blur / 24) * 100)}%`;
    if (subtitleOffsetLabel) {
      const offset = Number(subtitlePreferences.offset || 0);
      subtitleOffsetLabel.textContent = `${offset > 0 ? "+" : ""}${offset.toFixed(1)}s`;
    }
    subtitleColors.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.color === subtitlePreferences.color);
    });
    player.style.setProperty("--caption-size", `${subtitlePreferences.size}px`);
    player.style.setProperty("--caption-blur", `${subtitlePreferences.blur}px`);
    player.style.setProperty("--caption-color", subtitlePreferences.color);
    player.style.setProperty("--caption-font-family", subtitleFontFamily(subtitlePreferences.font));
  };
  const formatTime = (seconds) => {
    const value = Math.max(0, Number(seconds || 0));
    const minutes = Math.floor(value / 60);
    const remaining = Math.floor(value % 60);
    const hours = Math.floor(minutes / 60);
    const displayMinutes = hours ? String(minutes % 60).padStart(2, "0") : String(minutes);
    return `${hours ? `${hours}:` : ""}${displayMinutes}:${String(remaining).padStart(2, "0")}`;
  };
  const parseTimestamp = (value) => {
    const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})$/);
    if (!match) return 0;
    return (
      Number(match[1]) * 3600
      + Number(match[2]) * 60
      + Number(match[3])
      + Number(match[4]) / 1000
    );
  };
  const parseWebVttCues = (text) => {
    const lines = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
    const cues = [];
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index].trim();
      if (!line.includes("-->")) continue;
      const [startRaw, endAndSettings = ""] = line.split("-->");
      const endRaw = endAndSettings.trim().split(/\s+/, 1)[0];
      const cueLines = [];
      index += 1;
      while (index < lines.length && lines[index].trim()) {
        cueLines.push(lines[index]);
        index += 1;
      }
      const cueText = cueLines.join("\n").trim();
      if (cueText) {
        cues.push({
          startTime: parseTimestamp(startRaw),
          endTime: parseTimestamp(endRaw),
          text: cueText,
        });
      }
    }
    return cues.filter((cue) => cue.endTime > cue.startTime);
  };
  const selectedEpisodeRuntimeSeconds = () => {
    const option = packEpisode?.selectedOptions?.[0];
    const runtime = Number(option?.dataset.runtimeSeconds || 0);
    return Number.isFinite(runtime) && runtime > 0 ? runtime : null;
  };
  const selectedEpisodeTitle = () => {
    const option = packEpisode?.selectedOptions?.[0];
    const text = String(option?.textContent || "").trim();
    if (!option?.value || !text) return "";
    return text.replace(/^E\d+\s*[·:-]\s*/i, "").trim();
  };
  const configuredRuntimeSeconds = () => {
    const runtime = Number(player.dataset.runtimeSeconds || 0);
    return Number.isFinite(runtime) && runtime > 0 ? runtime : null;
  };
  const displayDurationSeconds = () => {
    const runtime = activeSelection.runtimeSeconds || selectedEpisodeRuntimeSeconds() || configuredRuntimeSeconds();
    const browserDuration = Number(video.duration || 0);
    if (!Number.isFinite(browserDuration) || browserDuration <= 0) return runtime || 0;
    if (runtime && browserDuration < Math.max(600, runtime * 0.35)) return runtime;
    return browserDuration;
  };
  const syncTimeline = () => {
    const duration = displayDurationSeconds();
    const current = effectiveCurrentTime();
    if (timeline) {
      const progress = duration ? Math.max(0, Math.min(1000, Math.round((current / duration) * 1000))) : 0;
      timeline.value = String(progress);
    }
    if (timeLabel) {
      timeLabel.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
    }
    if (netflixEpisode) {
      netflixEpisode.textContent = activeSelection.season && activeSelection.episode
        ? `S${String(activeSelection.season).padStart(2, "0")}E${String(activeSelection.episode).padStart(2, "0")}`
        : "";
    }
  };
  const showControlsBriefly = () => {
    if (!mediaShell) return;
    mediaShell.dataset.controlsVisible = "true";
    window.clearTimeout(controlsHideTimer);
    controlsHideTimer = window.setTimeout(() => {
      if (!video.paused) mediaShell.dataset.controlsVisible = "false";
    }, 2200);
  };
  const syncFullscreenChrome = () => {
    if (!mediaShell) return;
    mediaShell.dataset.fullscreen = document.fullscreenElement === mediaShell ? "true" : "false";
    showControlsBriefly();
  };
  const syncQuickControls = () => {
    if (mediaShell) {
      mediaShell.dataset.paused = video.paused ? "true" : "false";
      if (video.paused) mediaShell.dataset.controlsVisible = "true";
    }
    quickToggles.forEach((button) => button.setAttribute("aria-label", video.paused ? "Play" : "Pause"));
    if (playIcon) playIcon.textContent = video.paused ? "▶" : "Ⅱ";
    if (centerIcon) centerIcon.textContent = video.paused ? "▶" : "Ⅱ";
    if (quickMute) {
      if (muteIcon) muteIcon.textContent = video.muted || video.volume === 0 ? "🔇" : "🔊";
      quickMute.setAttribute("aria-label", video.muted || video.volume === 0 ? "Unmute" : "Mute");
    }
    if (volume && Number(volume.value) !== video.volume) volume.value = String(video.volume);
    syncTimeline();
  };
  const currentSubtitleSelection = () => {
    const endpoint = player.dataset.subtitleEndpoint;
    if (!endpoint || selectedKind() !== "local") return { key: "", url: "", season: null, episode: null };
    const meta = selectedSourceMeta();
    const season = activeSelection.season || meta?.season || null;
    const episode = activeSelection.episode
      || (meta?.seasonPack ? (Number(packEpisode?.value || 0) || null) : (meta?.episode || null));
    const episodeTitle = activeSelection.episodeTitle || selectedEpisodeTitle();
    const url = new URL(endpoint, window.location.origin);
    if (player.dataset.mediaType === "tv") {
      if (season) url.searchParams.set("season", String(season));
      if (episode) url.searchParams.set("episode", String(episode));
      if (episodeTitle) url.searchParams.set("episode_title", episodeTitle);
    }
    return {
      key: url.toString(),
      url: url.toString(),
      season,
      episode,
      episodeTitle,
    };
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
  const clearVideoPaintCheck = () => {
    window.clearTimeout(videoPaintCheckTimer);
    videoPaintCheckTimer = 0;
  };
  const setPackStatus = (message = "") => {
    if (!packStatus) return;
    packStatus.textContent = message;
    packStatus.hidden = !message;
  };
  const hidePackBrowser = () => {
    if (!packBrowser) return;
    packRequestToken += 1;
    packBrowser.hidden = true;
    packBrowser.dataset.loadedSeason = "";
    if (packEpisode) {
      packEpisode.replaceChildren(new Option("Choose an episode", ""));
      packEpisode.disabled = true;
      packEpisode.value = "";
    }
    setPackStatus("");
  };
  const syncPackLaunchState = () => {
    const meta = selectedSourceMeta();
    if (!meta?.seasonPack) return false;
    const season = Number(meta.season || 0) || null;
    const episode = Number(packEpisode?.value || 0) || null;
    launchTitle.textContent = "Play selected episode from pack";
    if (!season) {
      launch.disabled = true;
      setStatus("This season pack has no season metadata yet.");
      setPackStatus("Re-add this pack from the season picker so Dragon can bind it to the right season.");
      return true;
    }
    if (!episode) {
      launch.disabled = true;
      setStatus("Choose an episode from this season pack before you press play.");
      setPackStatus("");
      return true;
    }
    launch.disabled = false;
    setStatus(`Ready to play S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")} from the selected season pack.`);
    setPackStatus("");
    return true;
  };
  const loadPackEpisodes = async () => {
    const meta = selectedSourceMeta();
    if (!packBrowser || !packEpisode || !meta?.seasonPack) {
      hidePackBrowser();
      return;
    }
    const requestToken = ++packRequestToken;
    const season = Number(meta.season || 0) || null;
    const tmdbId = player.dataset.tmdbId;
    const template = player.dataset.episodesTemplate;
    packBrowser.hidden = false;
    packHeading.textContent = "Episode";
    if (!season || !tmdbId || !template) {
      packEpisode.disabled = true;
      setPackStatus("This pack cannot be mapped to TMDB episodes yet.");
      launch.disabled = true;
      return;
    }
    if (packBrowser.dataset.loadedSeason === String(season) && packEpisode.options.length > 1) {
      syncPackLaunchState();
      return;
    }
    packEpisode.replaceChildren(new Option("Choose an episode", ""));
    packEpisode.disabled = true;
    packBrowser.dataset.loadedSeason = "";
    setPackStatus(`Loading TMDB episodes for season ${season}…`);
    launch.disabled = true;
    try {
      const endpoint = fillTemplate(template, [tmdbId, season]);
      const response = await fetch(endpoint, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.error?.message || "Episode lookup is unavailable.");
      }
      const currentMeta = selectedSourceMeta();
      if (
        requestToken !== packRequestToken
        || !currentMeta?.seasonPack
        || currentMeta.sourceId !== meta.sourceId
        || Number(currentMeta.season || 0) !== season
      ) {
        return;
      }
      for (const item of payload.items || []) {
        const runtimeMinutes = Number(item.runtime_minutes || item.runtime || 0) || 0;
        const option = new Option(
          `E${String(item.episode_number).padStart(2, "0")} · ${item.name}`,
          item.episode_number,
        );
        if (runtimeMinutes > 0) option.dataset.runtimeSeconds = String(runtimeMinutes * 60);
        packEpisode.add(option);
      }
      packEpisode.disabled = packEpisode.options.length <= 1;
      packBrowser.dataset.loadedSeason = String(season);
      if (meta.episode) {
        packEpisode.value = String(meta.episode);
      }
      syncPackLaunchState();
    } catch (error) {
      packEpisode.disabled = true;
      setPackStatus(String(error?.message || "Episode lookup is unavailable."));
      launch.disabled = true;
    }
  };

  const renderActiveCaption = () => {
    if (!captionLayer || !captionChip || !captionText) return;
    const entry = subtitleEntries[selectedSubtitleIndex] || null;
    if (!entry?.ready || !entry.cues?.length) {
      captionLayer.hidden = true;
      captionChip.hidden = true;
      captionText.textContent = "";
      return;
    }
    const moment = effectiveCurrentTime() + Number(subtitlePreferences.offset || 0);
    const active = entry.cues.filter((cue) => cue.startTime <= moment && cue.endTime >= moment);
    if (!active.length) {
      captionLayer.hidden = true;
      captionChip.hidden = true;
      captionText.textContent = "";
      return;
    }
    captionText.textContent = active.map((cue) => String(cue.text || "").trim()).filter(Boolean).join("\n");
    captionLayer.hidden = false;
    captionChip.hidden = false;
  };

  const refreshSubtitleList = () => {
    if (!subtitleList) return;
    subtitleList.replaceChildren();
    const buildButton = (title, meta, index, { error = "" } = {}) => {
      const button = document.createElement("button");
      const titleSpan = document.createElement("span");
      const metaSmall = document.createElement("small");
      button.type = "button";
      button.dataset.playerSubtitleOption = String(index);
      button.className = [
        "movie-player__subtitle-option",
        selectedSubtitleIndex === index ? "is-active" : "",
        error ? "has-error" : "",
      ].filter(Boolean).join(" ");
      if (error) {
        button.dataset.subtitleError = "true";
        button.title = error;
      }
      titleSpan.textContent = title;
      metaSmall.textContent = meta;
      button.append(titleSpan, metaSmall);
      return button;
    };
    subtitleList.append(buildButton("Off", "No subtitles", -1));
    subtitleEntries.forEach((entry, index) => {
      const state = entry.error
        ? "Unavailable · Select to retry"
        : entry.ready
          ? "Ready"
          : entry.loadingPromise
            ? "Loading…"
            : "Available";
      subtitleList.append(buildButton(
        entry.label,
        `${entry.item.language_name}${entry.item.hearing_impaired ? " · HI" : ""} · ${state}`,
        index,
        { error: entry.error },
      ));
    });
  };

  const loadSubtitleEntry = (entry) => {
    if (!entry || entry.ready || entry.loadingPromise) return entry?.loadingPromise || Promise.resolve();
    entry.error = "";
    refreshSubtitleList();
    entry.loadingPromise = fetch(entry.item.track_url, {
      credentials: "same-origin",
      headers: { Accept: "text/vtt,text/plain" },
    })
      .then(async (response) => {
        const body = await response.text();
        if (!response.ok) throw new Error(body || "Subtitle could not be loaded.");
        entry.cues = parseWebVttCues(body);
        if (!entry.cues.length) throw new Error("Subtitle has no readable cues.");
        entry.ready = true;
        if (selectedSubtitleIndex === subtitleEntries.indexOf(entry)) {
          renderActiveCaption();
          setSubtitleStatus(`${entry.label} is selected. Use Sub to change font, color, blur, or timing.`);
        }
      })
      .catch((error) => {
        entry.error = String(error?.message || "Subtitle could not be loaded.");
        if (selectedSubtitleIndex === subtitleEntries.indexOf(entry)) {
          setSubtitleStatus(entry.error);
          renderActiveCaption();
        }
      })
      .finally(() => {
        entry.loadingPromise = null;
        refreshSubtitleList();
        if (selectedSubtitleIndex === subtitleEntries.indexOf(entry) && entry.error) {
          const nextIndex = subtitleEntries.findIndex((candidate) => (
            candidate !== entry && !candidate.ready && !candidate.error
          ));
          if (nextIndex >= 0) {
            setSubtitleStatus(`${entry.label} failed. Trying another subtitle…`);
            setActiveSubtitleIndex(nextIndex);
            return;
          }
          setSubtitleStatus(entry.error);
        }
      });
    return entry.loadingPromise;
  };

  const setActiveSubtitleIndex = (index) => {
    selectedSubtitleIndex = index;
    refreshSubtitleList();
    if (selectedSubtitleIndex < 0) {
      renderActiveCaption();
      captionLayer.hidden = true;
      captionChip.hidden = true;
      setSubtitleStatus("Subtitles are off. Open Sub to pick another track or adjust timing.");
      return;
    }
    const entry = subtitleEntries[selectedSubtitleIndex];
    if (!entry) return;
    if (!entry.ready) {
      setSubtitleStatus(`Loading ${entry.label}…`);
      void loadSubtitleEntry(entry);
      renderActiveCaption();
      return;
    }
    renderActiveCaption();
    setSubtitleStatus(`${entry.label} is selected. Use Sub to change font, color, blur, or timing.`);
  };

  const selectFirstUsableSubtitle = () => {
    const readyIndex = subtitleEntries.findIndex((entry) => entry.ready && !entry.error);
    if (readyIndex >= 0) {
      setActiveSubtitleIndex(readyIndex);
      return;
    }
    const pendingIndex = subtitleEntries.findIndex((entry) => !entry.error);
    if (pendingIndex >= 0) {
      setActiveSubtitleIndex(pendingIndex);
      return;
    }
    setActiveSubtitleIndex(-1);
    const firstError = subtitleEntries.find((entry) => entry.error)?.error || "";
    setSubtitleStatus(firstError || "No subtitle in the downloaded packs matched this episode.");
  };

  const clearSubtitleTracks = () => {
    video.querySelectorAll("track").forEach((track) => track.remove());
    Array.from(video.textTracks || []).forEach((track) => { track.mode = "disabled"; });
    subtitleEntries = [];
    selectedSubtitleIndex = -1;
    refreshSubtitleList();
    renderActiveCaption();
  };

  const mountSubtitleTracks = (items) => {
    clearSubtitleTracks();
    if (!items.length) {
      setSubtitleStatus("No Arabic or English subtitles were found.");
      return;
    }
    subtitleEntries = items.map((item, index) => {
      const label = `${item.language_name} · ${item.label}${item.hearing_impaired ? " · HI" : ""}`;
      const entry = {
        item,
        label,
        cues: [],
        loadingPromise: null,
        error: "",
        ready: false,
      };
      if (index === 0) window.setTimeout(selectFirstUsableSubtitle, 0);
      return entry;
    });
    refreshSubtitleList();
    setSubtitleStatus(`Checking ${items.length} subtitle option${items.length === 1 ? "" : "s"} and extracting only this episode…`);
  };

  const loadSubtitleOptions = () => {
    if (!subtitleStatus || !player.dataset.subtitleEndpoint) return Promise.resolve();
    const target = currentSubtitleSelection();
    if (!target.url) return Promise.resolve();
    if (subtitleOptions !== null && subtitleOptionsKey === target.key) {
      mountSubtitleTracks(subtitleOptions);
      return Promise.resolve();
    }
    const requestToken = ++subtitleRequestToken;
    subtitleOptions = null;
    subtitleOptionsKey = target.key;
    setSubtitleStatus(
      target.season && target.episode
        ? `Finding subtitles for S${String(target.season).padStart(2, "0")}E${String(target.episode).padStart(2, "0")}…`
        : "Finding Arabic and English subtitles…"
    );
    subtitleRequest = fetch(target.url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.error?.message || "Subtitle search is unavailable");
        }
        const items = Array.isArray(payload.items) ? payload.items : [];
        if (requestToken !== subtitleRequestToken || subtitleOptionsKey !== target.key) return;
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
    clearVideoPaintCheck();
    clearSubtitleTracks();
    activeSelection = { season: null, episode: null, episodeTitle: "", runtimeSeconds: null };
    setSubtitlePanelOpen(false);
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
    clearVideoPaintCheck();
    setWatchMode(false);
    sourceUrl = "";
    frame.src = "about:blank";
    frame.hidden = true;
    if (mediaShell) mediaShell.hidden = true;
    if (captionLayer) captionLayer.hidden = true;
    video.hidden = true;
    launch.hidden = false;
    launch.disabled = false;
    controls.hidden = true;
    open.hidden = true;
    stop.hidden = true;
    setSubtitlePanelOpen(false);
  };

  const syncSourceUi = () => {
    const kind = selectedKind();
    const meta = selectedSourceMeta();
    badge.textContent = kind === "vidsrc" ? "VidSrc" : "Local";
    launchTitle.textContent = kind === "vidsrc" ? "Play with VidSrc" : "Start local player";
    if (kind === "vidsrc") {
      hidePackBrowser();
      launch.disabled = false;
      setStatus("Ready. No external connection has been made.");
    } else if (meta?.seasonPack) {
      void loadPackEpisodes();
    } else {
      hidePackBrowser();
      launch.disabled = false;
      setStatus("Ready. The magnet will start only after you press play.");
    }
    if (subtitleStatus) {
      if (kind === "vidsrc") {
        clearSubtitleTracks();
        setSubtitleStatus("Use VidSrc captions or switch to Local to unlock Dragon subtitle controls.");
      } else if (subtitleOptions === null) {
        setSubtitleStatus("Arabic will be selected first. Open Sub after Local starts to tune font, color, blur, or timing.");
      }
    }
  };

  const showError = (message) => {
    clearPoll();
    clearVideoPaintCheck();
    setWatchMode(false);
    launch.disabled = false;
    launch.hidden = false;
    frame.hidden = true;
    if (mediaShell) mediaShell.hidden = true;
    video.hidden = true;
    controls.hidden = true;
    setStatus(message);
  };

  const localPlaybackUrl = () => {
    if (!localSession) return "";
    if (localSession.streamKind === "transcode") return transcodePlaybackUrl();
    return localSession.streamUrl || "";
  };

  const switchLocalToTranscode = () => {
    if (!localSession?.transcodeUrl) return false;
    clearVideoPaintCheck();
    localSession.playbackOffset = effectiveCurrentTime();
    localSession.transcodeNonce = Number(localSession.transcodeNonce || 0) + 1;
    localSession.streamKind = "transcode";
    video.removeAttribute("src");
    video.load();
    video.src = transcodePlaybackUrl();
    if (mediaShell) mediaShell.hidden = false;
    video.hidden = false;
    video.preload = "auto";
    setPlayerState("buffering", "Direct playback was not supported. Switching to local transcoding…");
    video.load();
    video.play().catch(() => {});
    return true;
  };
  const seekWithinTranscode = (targetSeconds) => {
    if (!localSession?.transcodeUrl) return false;
    const wasPaused = video.paused;
    const duration = displayDurationSeconds();
    const clamped = Math.max(0, Math.min(duration || targetSeconds, Number(targetSeconds || 0)));
    localSession.streamKind = "transcode";
    localSession.playbackOffset = clamped;
    localSession.transcodeNonce = Number(localSession.transcodeNonce || 0) + 1;
    clearVideoPaintCheck();
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.src = transcodePlaybackUrl();
    video.preload = "auto";
    setPlayerState("buffering", `Seeking to ${formatTime(clamped)}…`);
    syncTimeline();
    renderActiveCaption();
    video.load();
    if (!wasPaused) video.play().catch(() => {});
    scheduleVideoPaintCheck();
    return true;
  };
  const videoHasVisibleFrames = () => Number(video.videoWidth || 0) > 0 && Number(video.videoHeight || 0) > 0;
  const scheduleVideoPaintCheck = () => {
    if (activeKind !== "local" || !localSession) return;
    clearVideoPaintCheck();
    videoPaintCheckTimer = window.setTimeout(() => {
      videoPaintCheckTimer = 0;
      if (activeKind !== "local" || !localSession) return;
      if (video.paused || video.ended || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
      if (videoHasVisibleFrames()) return;
      if (localSession.streamKind !== "transcode" && switchLocalToTranscode()) {
        setPlayerState("buffering", "Audio started but the browser could not render video frames. Switching to local transcoding…");
        return;
      }
      setPlayerState("failed", "Audio is playing, but the browser still reports 0×0 video frames from the transcoder. Try another release while I tune this path.");
    }, localSession.streamKind === "transcode" ? 4000 : 1600);
  };

  const loadVidSrc = () => {
    setWatchMode(true);
    frame.hidden = false;
    if (mediaShell) mediaShell.hidden = true;
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
          if (mediaShell) mediaShell.hidden = false;
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
          scheduleVideoPaintCheck();
        }
      }
      pollTimer = window.setTimeout(pollLocal, payload.session?.complete ? 5000 : 1000);
    } catch (error) {
      showError(String(error?.message || "Local player unavailable"));
    }
  };

  const startLocal = async (selection = {}) => {
    const response = await fetch(player.dataset.localEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({ source_id: source.value, ...selection }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error?.message || "Local player unavailable");
    activeSelection = {
      season: Number(selection.season || 0) || null,
      episode: Number(selection.episode || 0) || null,
      episodeTitle: selection.episodeTitle || selectedEpisodeTitle(),
      runtimeSeconds: selectedEpisodeRuntimeSeconds(),
    };
    localSession = {
      statusUrl: payload.status_url,
      streamUrl: payload.stream_url,
      transcodeUrl: payload.transcode_url,
      streamKind: payload.session?.stream_kind || "direct",
      stopUrl: payload.stop_url,
      playbackOffset: 0,
      transcodeNonce: 0,
    };
    launch.hidden = true;
    setWatchMode(true);
    if (mediaShell) {
      mediaShell.hidden = false;
      mediaShell.dataset.paused = "true";
      mediaShell.dataset.controlsVisible = "true";
    }
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

  const togglePlayback = () => {
    if (video.paused) video.play().catch(() => {});
    else video.pause();
    syncQuickControls();
    showControlsBriefly();
  };

  const seekRelative = (seconds) => {
    const duration = displayDurationSeconds() || Infinity;
    const target = Math.max(0, Math.min(duration, effectiveCurrentTime() + seconds));
    if (localSession?.streamKind === "transcode" && seekWithinTranscode(target)) {
      showControlsBriefly();
      return;
    }
    video.currentTime = Math.max(0, Math.min(duration, Number(video.currentTime || 0) + seconds));
    showControlsBriefly();
  };

  const exitWatchMode = async () => {
    await stopLocal({ silent: true });
    resetViewport();
    syncSourceUi();
    player.scrollIntoView({ block: "center", behavior: "smooth" });
  };

  source.addEventListener("change", async () => {
    await stopLocal({ silent: true });
    subtitleOptions = null;
    subtitleOptionsKey = "";
    resetViewport();
    syncSourceUi();
  });
  packEpisode?.addEventListener("change", () => {
    subtitleOptions = null;
    subtitleOptionsKey = "";
    activeSelection.runtimeSeconds = selectedEpisodeRuntimeSeconds();
    activeSelection.episodeTitle = selectedEpisodeTitle();
    syncPackLaunchState();
    syncTimeline();
  });

  launch.addEventListener("click", async () => {
    launch.disabled = true;
    activeKind = selectedKind();
    try {
      if (activeKind === "local") {
        const meta = selectedSourceMeta();
        const selection = meta?.seasonPack
          ? {
            season: Number(meta.season || 0) || null,
            episode: Number(packEpisode?.value || 0) || null,
          }
          : {};
        if (meta?.seasonPack && !selection.episode) {
          syncPackLaunchState();
          return;
        }
        setPlayerState("metadata", "Starting the local WebTorrent runtime…");
        await startLocal(selection);
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
  playerBack?.addEventListener("click", () => { void exitWatchMode(); });
  sourceReturn?.addEventListener("click", () => { void exitWatchMode(); });
  quickToggles.forEach((button) => button.addEventListener("click", togglePlayback));
  quickBack?.addEventListener("click", () => seekRelative(-10));
  quickForward?.addEventListener("click", () => seekRelative(10));
  quickMute?.addEventListener("click", () => {
    video.muted = !video.muted;
    syncQuickControls();
    showControlsBriefly();
  });
  volume?.addEventListener("input", () => {
    video.volume = Number(volume.value || 0);
    video.muted = video.volume === 0;
    syncQuickControls();
    showControlsBriefly();
  });
  timeline?.addEventListener("input", () => {
    const duration = displayDurationSeconds();
    if (duration) {
      const target = (Number(timeline.value || 0) / 1000) * duration;
      if (!(localSession?.streamKind === "transcode" && seekWithinTranscode(target))) {
        video.currentTime = target;
      }
    }
    syncTimeline();
    showControlsBriefly();
  });
  captionToggle?.addEventListener("click", () => {
    if (selectedKind() !== "local" || !player.dataset.subtitleEndpoint) return;
    setSubtitlePanelOpen(!subtitlePanelOpen);
    showControlsBriefly();
  });
  subtitleClose?.addEventListener("click", () => setSubtitlePanelOpen(false));
  subtitleOpenAppearance?.addEventListener("click", () => setSubtitleScreen("appearance"));
  subtitleBack?.addEventListener("click", () => setSubtitleScreen("list"));
  subtitleList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-player-subtitle-option]");
    if (!button) return;
    const index = Number(button.dataset.playerSubtitleOption);
    setActiveSubtitleIndex(Number.isFinite(index) ? index : -1);
    showControlsBriefly();
  });
  subtitleSize?.addEventListener("input", () => {
    subtitlePreferences.size = Number(subtitleSize.value || 30);
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleBlur?.addEventListener("input", () => {
    subtitlePreferences.blur = Number(subtitleBlur.value || 0);
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleOffset?.addEventListener("input", () => {
    subtitlePreferences.offset = Number(subtitleOffset.value || 0);
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  });
  subtitleFont?.addEventListener("change", () => {
    subtitlePreferences.font = subtitleFont.value || "plex";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleColors.forEach((button) => button.addEventListener("click", () => {
    subtitlePreferences.color = button.dataset.color || "#ffffff";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  }));
  subtitleReset?.addEventListener("click", () => {
    subtitlePreferences = { size: 30, blur: 0, offset: 0, color: "#ffffff", font: "plex" };
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  });
  quickFullscreen?.addEventListener("click", () => {
    const target = mediaShell || video;
    if (document.fullscreenElement) {
      document.exitFullscreen?.();
    } else {
      target.requestFullscreen?.();
    }
    showControlsBriefly();
  });
  document.addEventListener("fullscreenchange", syncFullscreenChrome);
  mediaShell?.addEventListener("mousemove", showControlsBriefly);
  mediaShell?.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-player-subtitle-panel]")) return;
    if (event.target.closest?.("button,input,select,a")) return;
    togglePlayback();
  });
  video.addEventListener("loadstart", () => {
    if (activeKind === "local") setPlayerState("buffering", "Opening the direct local stream…");
    syncQuickControls();
  });
  video.addEventListener("loadedmetadata", () => {
    if (activeKind === "local") scheduleVideoPaintCheck();
    syncTimeline();
    renderActiveCaption();
  });
  video.addEventListener("loadeddata", () => {
    if (activeKind === "local") scheduleVideoPaintCheck();
  });
  video.addEventListener("timeupdate", () => {
    syncTimeline();
    renderActiveCaption();
  });
  video.addEventListener("seeked", renderActiveCaption);
  video.addEventListener("durationchange", () => {
    syncTimeline();
    renderActiveCaption();
  });
  video.addEventListener("canplay", () => {
    if (activeKind === "local") scheduleVideoPaintCheck();
  });
  video.addEventListener("waiting", () => {
    if (activeKind === "local") setPlayerState("buffering", "Buffering requested torrent pieces…");
  });
  video.addEventListener("stalled", () => {
    if (activeKind === "local") setPlayerState("stalled", "The torrent stalled. Waiting for peers; VidSrc remains available as fallback.");
  });
  video.addEventListener("playing", () => {
    if (activeKind === "local") {
      const selectionText = activeSelection.season && activeSelection.episode
        ? `Playing S${String(activeSelection.season).padStart(2, "0")}E${String(activeSelection.episode).padStart(2, "0")} from the selected season pack.`
        : "Playing directly from the local WebTorrent runtime.";
      setPlayerState("playing", selectionText);
      void reportWatchStarted();
      scheduleVideoPaintCheck();
      syncQuickControls();
      renderActiveCaption();
      showControlsBriefly();
    }
  });
  video.addEventListener("pause", () => {
    syncQuickControls();
    renderActiveCaption();
  });
  video.addEventListener("volumechange", syncQuickControls);
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
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && subtitlePanelOpen) {
      setSubtitlePanelOpen(false);
      return;
    }
    if (!player.classList.contains("is-watch-mode") || mediaShell?.hidden) return;
    const target = event.target;
    if (target?.closest?.("input,textarea,select,button,[contenteditable='true']")) return;
    if (event.key === " " || event.code === "Space") {
      event.preventDefault();
      togglePlayback();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      seekRelative(-10);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      seekRelative(10);
    } else if (event.key.toLowerCase() === "m") {
      event.preventDefault();
      video.muted = !video.muted;
      syncQuickControls();
      showControlsBriefly();
    } else if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      quickFullscreen?.click();
    } else if (event.key === "Escape") {
      event.preventDefault();
      void exitWatchMode();
    }
  });
  loadSubtitlePreferences();
  updateSubtitlePreferenceLabels();
  window.addEventListener("pagehide", () => { stopLocal({ silent: true }); });
  syncSourceUi();
})();
