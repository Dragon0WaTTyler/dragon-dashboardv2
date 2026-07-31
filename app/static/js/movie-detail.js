(() => {
  const player = document.querySelector("[data-movie-player]");
  if (!player) return;

  const playerTitle = player.querySelector("#movie-player-title");
  const selectedEpisodeSummary = document.querySelector("[data-player-selected-episode]");
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
  const subtitlePreset = player.querySelector("[data-player-subtitle-preset]");
  const subtitleSize = player.querySelector("[data-player-subtitle-size]");
  const subtitleSizeLabel = player.querySelector("[data-player-subtitle-size-label]");
  const subtitlePosition = player.querySelector("[data-player-subtitle-position]");
  const subtitlePositionLabel = player.querySelector("[data-player-subtitle-position-label]");
  const subtitleBackground = player.querySelector("[data-player-subtitle-background]");
  const subtitleOpacity = player.querySelector("[data-player-subtitle-opacity]");
  const subtitleOpacityLabel = player.querySelector("[data-player-subtitle-opacity-label]");
  const subtitleBlur = player.querySelector("[data-player-subtitle-blur]");
  const subtitleBlurLabel = player.querySelector("[data-player-subtitle-blur-label]");
  const subtitleShadow = player.querySelector("[data-player-subtitle-shadow]");
  const subtitleShadowLabel = player.querySelector("[data-player-subtitle-shadow-label]");
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
  const initialParams = new URLSearchParams(window.location.search);
  const subtitlePrefsLegacyKey = "dragon:subtitle-style:v1";
  const subtitlePrefsKey = "dragon:subtitle-style:v2";
  const subtitlePresetValues = {
    netflix: {
      size: 32,
      position: 13,
      background: "shadow",
      backgroundOpacity: 25,
      blur: 0,
      shadow: 90,
      offset: 0,
      color: "#ffffff",
      font: "noto-arabic",
    },
    youtube: {
      size: 30,
      position: 11,
      background: "box",
      backgroundOpacity: 60,
      blur: 0,
      shadow: 65,
      offset: 0,
      color: "#ffffff",
      font: "noto-arabic",
    },
    "arabic-clear": {
      size: 38,
      position: 13,
      background: "shadow",
      backgroundOpacity: 18,
      blur: 0,
      shadow: 100,
      offset: 0,
      color: "#ffffff",
      font: "cairo",
    },
    "high-contrast": {
      size: 34,
      position: 12,
      background: "box",
      backgroundOpacity: 82,
      blur: 0,
      shadow: 100,
      offset: 0,
      color: "#ffffff",
      font: "cairo",
    },
    minimal: {
      size: 30,
      position: 12,
      background: "off",
      backgroundOpacity: 0,
      blur: 0,
      shadow: 55,
      offset: 0,
      color: "#ffffff",
      font: "tajawal",
    },
  };
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
  let subtitlePreferencesLanguage = "default";
  let subtitlePreferences = null;
  let captionFitSize = null;
  let captionFitSignature = "";
  let savedProgress = null;
  let progressLoaded = false;
  let progressSaveTimer = 0;
  let lastProgressSentAt = 0;
  let progressRequestToken = 0;
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
  const clamp = (value, min, max) => Math.max(min, Math.min(max, Number(value)));
  const subtitleFontFamily = (value) => ({
    "noto-arabic": "var(--font-arabic-clear)",
    cairo: "\"Cairo\", \"Noto Sans Arabic\", \"Segoe UI\", Tahoma, sans-serif",
    tajawal: "\"Tajawal\", \"Noto Sans Arabic\", \"Segoe UI\", Tahoma, sans-serif",
    plex: "\"IBM Plex Sans\", var(--font-arabic-clear)",
    inter: "Inter, \"IBM Plex Sans\", var(--font-arabic-clear)",
    mono: "\"IBM Plex Mono\", \"Cascadia Mono\", monospace",
  }[value] || "var(--font-arabic-clear)");
  const defaultSubtitlePreferences = (language = "default") => ({
    preset: language === "ar" ? "arabic-clear" : "netflix",
    ...(language === "ar" ? subtitlePresetValues["arabic-clear"] : subtitlePresetValues.netflix),
    font: language === "ar" ? "cairo" : "plex",
  });
  const sanitizeSubtitlePreferences = (raw, language = "default") => {
    const defaults = defaultSubtitlePreferences(language);
    const merged = { ...defaults, ...(raw && typeof raw === "object" ? raw : {}) };
    const preset = merged.preset === "custom" || subtitlePresetValues[merged.preset]
      ? merged.preset
      : defaults.preset;
    const font = ["noto-arabic", "cairo", "tajawal", "plex", "inter", "mono"].includes(merged.font)
      ? merged.font
      : defaults.font;
    const background = ["off", "shadow", "box", "blur"].includes(merged.background)
      ? merged.background
      : defaults.background;
    const color = /^#[0-9a-f]{6}$/i.test(String(merged.color || "")) ? merged.color : defaults.color;
    return {
      preset,
      size: clamp(merged.size, 20, 96),
      position: clamp(merged.position, 8, 62),
      background,
      backgroundOpacity: clamp(merged.backgroundOpacity, 0, 90),
      blur: clamp(merged.blur, 0, 24),
      shadow: clamp(merged.shadow, 0, 100),
      offset: clamp(merged.offset, -5, 5),
      color,
      font,
    };
  };
  const subtitlePrefsStorageKey = (language = "default") => `${subtitlePrefsKey}:${language || "default"}`;
  const loadSubtitlePreferences = (language = "default") => {
    subtitlePreferencesLanguage = language || "default";
    try {
      const raw = window.localStorage.getItem(subtitlePrefsStorageKey(subtitlePreferencesLanguage))
        || (subtitlePreferencesLanguage === "default" ? window.localStorage.getItem(subtitlePrefsLegacyKey) : "");
      subtitlePreferences = sanitizeSubtitlePreferences(raw ? JSON.parse(raw) : null, subtitlePreferencesLanguage);
    } catch (_error) {
      subtitlePreferences = sanitizeSubtitlePreferences(null, subtitlePreferencesLanguage);
    }
  };
  const saveSubtitlePreferences = () => {
    if (!subtitlePreferences) return;
    try {
      window.localStorage.setItem(
        subtitlePrefsStorageKey(subtitlePreferencesLanguage),
        JSON.stringify({ ...subtitlePreferences, version: 2 }),
      );
    } catch (_error) {
      // Local storage is a nice-to-have only.
    }
  };
  const applySubtitlePreset = (preset) => {
    if (!subtitlePreferences || !subtitlePresetValues[preset]) return;
    subtitlePreferences = sanitizeSubtitlePreferences({
      ...subtitlePreferences,
      ...subtitlePresetValues[preset],
      preset,
    }, subtitlePreferencesLanguage);
    resetCaptionFit();
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  };
  const updateSubtitleSizeLabel = () => {
    if (!subtitleSizeLabel || !subtitlePreferences) return;
    const requested = Number(subtitlePreferences.size || 0);
    subtitleSizeLabel.textContent = `${requested}px`;
    subtitleSizeLabel.removeAttribute("title");
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
    if (!subtitlePreferences) loadSubtitlePreferences(subtitlePreferencesLanguage);
    if (subtitlePreset) subtitlePreset.value = subtitlePreferences.preset;
    if (subtitleSize && Number(subtitleSize.value) !== Number(subtitlePreferences.size)) subtitleSize.value = String(subtitlePreferences.size);
    if (subtitlePosition && Number(subtitlePosition.value) !== Number(subtitlePreferences.position)) subtitlePosition.value = String(subtitlePreferences.position);
    if (subtitleBackground) subtitleBackground.value = subtitlePreferences.background;
    if (subtitleOpacity && Number(subtitleOpacity.value) !== Number(subtitlePreferences.backgroundOpacity)) subtitleOpacity.value = String(subtitlePreferences.backgroundOpacity);
    if (subtitleBlur && Number(subtitleBlur.value) !== Number(subtitlePreferences.blur)) subtitleBlur.value = String(subtitlePreferences.blur);
    if (subtitleShadow && Number(subtitleShadow.value) !== Number(subtitlePreferences.shadow)) subtitleShadow.value = String(subtitlePreferences.shadow);
    if (subtitleOffset && Number(subtitleOffset.value) !== Number(subtitlePreferences.offset)) subtitleOffset.value = String(subtitlePreferences.offset);
    if (subtitleFont) subtitleFont.value = subtitlePreferences.font;
    updateSubtitleSizeLabel();
    if (subtitlePositionLabel) subtitlePositionLabel.textContent = `${subtitlePreferences.position}%`;
    if (subtitleOpacityLabel) subtitleOpacityLabel.textContent = `${subtitlePreferences.backgroundOpacity}%`;
    if (subtitleBlurLabel) subtitleBlurLabel.textContent = `${Math.round((subtitlePreferences.blur / 24) * 100)}%`;
    if (subtitleShadowLabel) subtitleShadowLabel.textContent = `${subtitlePreferences.shadow}%`;
    if (subtitleOffsetLabel) {
      const offset = Number(subtitlePreferences.offset || 0);
      subtitleOffsetLabel.textContent = `${offset > 0 ? "+" : ""}${offset.toFixed(1)}s`;
    }
    subtitleColors.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.color === subtitlePreferences.color);
    });
    player.style.setProperty("--caption-size", `${subtitlePreferences.size}px`);
    player.style.setProperty("--caption-position", `${subtitlePreferences.position}%`);
    player.style.setProperty("--caption-bg-opacity", `${subtitlePreferences.backgroundOpacity}%`);
    player.style.setProperty("--caption-blur", `${subtitlePreferences.blur}px`);
    player.style.setProperty("--caption-shadow-alpha", `${subtitlePreferences.shadow}%`);
    player.style.setProperty("--caption-shadow-blur", `${Math.round(4 + subtitlePreferences.shadow / 5)}px`);
    player.style.setProperty("--caption-color", subtitlePreferences.color);
    player.style.setProperty("--caption-font-family", subtitleFontFamily(subtitlePreferences.font));
    player.style.setProperty("--caption-weight", subtitlePreferences.font === "mono" ? "600" : "700");
    player.dataset.captionBackground = subtitlePreferences.background;
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
  const configuredSelectedSeason = () => Number(player.dataset.selectedSeason || 0) || null;
  const configuredSelectedEpisode = () => Number(player.dataset.selectedEpisode || 0) || null;
  const configuredSelectedEpisodeTitle = () => String(player.dataset.selectedEpisodeTitle || "").trim();
  const syncPlayerTitle = () => {
    if (!playerTitle || player.dataset.mediaType !== "tv") return;
    const meta = selectedSourceMeta();
    const season = activeSelection.season || meta?.season || configuredSelectedSeason();
    const episode = activeSelection.episode
      || (meta?.seasonPack ? Number(packEpisode?.value || 0) || null : meta?.episode)
      || configuredSelectedEpisode();
    const episodeTitle = activeSelection.episodeTitle
      || (meta?.seasonPack ? selectedEpisodeTitle() : "")
      || configuredSelectedEpisodeTitle();
    if (!season || !episode || !episodeTitle) return;
    const episodeCode = `S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")}`;
    playerTitle.textContent = `Watch ${episodeCode} · ${episodeTitle}`;
    if (selectedEpisodeSummary) {
      selectedEpisodeSummary.textContent = `Player episode selected: S${season}E${String(episode).padStart(2, "0")}`;
    }
  };
  const requestedEpisodeFromUrl = (season) => {
    const querySeason = Number(initialParams.get("season") || 0) || null;
    const queryEpisode = Number(initialParams.get("episode") || 0) || null;
    return querySeason === Number(season || 0) && queryEpisode ? queryEpisode : null;
  };
  const selectedEpisodeScope = () => {
    if (player.dataset.mediaType !== "tv" || selectedKind() !== "local") {
      return { season: null, episode: null };
    }
    const meta = selectedSourceMeta();
    if (!meta) return { season: null, episode: null };
    const season = activeSelection.season || configuredSelectedSeason() || meta.season || null;
    const episode = activeSelection.episode
      || (meta.seasonPack
        ? (
          Number(packEpisode?.value || 0)
          || configuredSelectedEpisode()
          || requestedEpisodeFromUrl(season)
          || meta.episode
          || null
        )
        : (configuredSelectedEpisode() || meta.episode || null));
    return { season, episode };
  };
  const syncEpisodeUrl = ({ replace = false } = {}) => {
    if (player.dataset.mediaType !== "tv" || !window.history) return;
    const { season, episode } = selectedEpisodeScope();
    const url = new URL(window.location.href);
    if (season && episode) {
      url.searchParams.set("season", String(season));
      url.searchParams.set("episode", String(episode));
    } else {
      url.searchParams.delete("season");
      url.searchParams.delete("episode");
    }
    if (url.toString() === window.location.href) return;
    window.history[replace ? "replaceState" : "pushState"]({}, "", url);
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
    window.requestAnimationFrame(() => renderActiveCaption());
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
      || (meta?.seasonPack
        ? (Number(packEpisode?.value || 0) || configuredSelectedEpisode() || null)
        : (configuredSelectedEpisode() || meta?.episode || null));
    const episodeTitle = activeSelection.episodeTitle || selectedEpisodeTitle() || configuredSelectedEpisodeTitle();
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
  const progressTarget = () => {
    const endpoint = String(player.dataset.progressEndpoint || "").trim();
    if (!endpoint) return { url: "", season: null, episode: null };
    const { season, episode } = selectedEpisodeScope();
    const url = new URL(endpoint, window.location.origin);
    if (player.dataset.mediaType === "tv") {
      if (!season || !episode) return { url: "", season: null, episode: null };
      url.searchParams.set("season", String(season));
      url.searchParams.set("episode", String(episode));
    }
    return { url: url.toString(), season, episode };
  };
  const progressTargetsMatch = (left, right) => {
    const leftUrl = String(left?.url || "").trim();
    const rightUrl = String(right?.url || "").trim();
    return Boolean(leftUrl) && leftUrl === rightUrl;
  };
  const loadSavedProgress = async () => {
    const target = progressTarget();
    const requestToken = ++progressRequestToken;
    savedProgress = null;
    if (!target.url) {
      progressLoaded = true;
      syncSourceUi();
      return;
    }
    try {
      const response = await fetch(target.url, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.error?.message || "Progress unavailable");
      if (requestToken !== progressRequestToken) return;
      const progress = payload?.item?.progress || null;
      const seconds = Number(progress?.current_seconds || 0);
      const duration = Number(progress?.duration_seconds || 0);
      const percent = Number(progress?.percent || 0);
      if (!progress?.completed && seconds >= 30 && percent < 92) {
        savedProgress = { seconds, duration, season: target.season, episode: target.episode };
      }
    } catch (_error) {
      savedProgress = null;
    } finally {
      if (requestToken !== progressRequestToken) return;
      progressLoaded = true;
      syncSourceUi();
    }
  };
  const saveMovieProgress = async ({ force = false, keepalive = false } = {}) => {
    const target = progressTarget();
    const duration = Math.round(displayDurationSeconds());
    const current = Math.round(effectiveCurrentTime());
    if (!target.url || activeKind !== "local" || !duration || current < 5) return;
    const now = Date.now();
    if (!force && now - lastProgressSentAt < 10000) return;
    lastProgressSentAt = now;
    const completed = duration > 0 && current / duration >= 0.92;
    try {
      const response = await fetch(target.url, {
        method: "PUT",
        credentials: "same-origin",
        keepalive: Boolean(keepalive),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
        },
        body: JSON.stringify({
          season: target.season,
          episode: target.episode,
          current_seconds: current,
          duration_seconds: duration,
          completed,
          client_updated_at: new Date().toISOString(),
        }),
      });
      if (!response.ok) throw new Error("Progress save failed.");
      const activeTarget = progressTarget();
      if (progressTargetsMatch(target, activeTarget)) {
        savedProgress = completed
          ? null
          : { seconds: current, duration, season: target.season, episode: target.episode };
        progressLoaded = true;
        syncSourceUi();
      }
    } catch (_error) {
      // Progress save should never interrupt playback.
      lastProgressSentAt = 0;
    }
  };
  const scheduleProgressSave = () => {
    window.clearTimeout(progressSaveTimer);
    progressSaveTimer = window.setTimeout(() => {
      progressSaveTimer = 0;
      void saveMovieProgress();
    }, 800);
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
  const resetCaptionDirection = () => {
    player.dataset.captionLanguage = "";
    captionChip?.removeAttribute("dir");
    captionText?.removeAttribute("dir");
  };
  const balanceCaptionLines = (
    text,
    {
      maxLines = 2,
      targetLength = 28,
      maxWidth = Number.POSITIVE_INFINITY,
      measureLine = null,
    } = {},
  ) => {
    const compact = String(text || "").replace(/\s+/g, " ").trim();
    if (!compact) return [];
    if (maxLines <= 1 || compact.length <= targetLength || !compact.includes(" ")) return [compact];
    const words = compact.split(" ").filter(Boolean);
    if (words.length < 4) return [compact];
    const memo = new Map();
    const scoreLine = (line) => {
      const length = line.replace(/[\u200E\u200F\u2066-\u2069]/gu, "").length;
      const measuredWidth = typeof measureLine === "function" ? measureLine(line) : 0;
      const overflow = Number.isFinite(maxWidth) ? Math.max(0, measuredWidth - maxWidth) : 0;
      return (Math.abs(length - targetLength) * 0.7)
        + (Math.max(0, length - targetLength) ** 2 * 1.5)
        + (length < 10 ? (10 - length) * 2.5 : 0)
        + (overflow * overflow * 4);
    };
    const solve = (startIndex, linesRemaining) => {
      const key = `${startIndex}:${linesRemaining}`;
      if (memo.has(key)) return memo.get(key);
      if (startIndex >= words.length) {
        const empty = { score: 0, lines: [] };
        memo.set(key, empty);
        return empty;
      }
      const wordsLeft = words.length - startIndex;
      if (linesRemaining <= 1 || wordsLeft <= 1) {
        const line = words.slice(startIndex).join(" ").trim();
        const terminal = { score: scoreLine(line), lines: [line] };
        memo.set(key, terminal);
        return terminal;
      }
      let best = null;
      const maxBreak = words.length - (linesRemaining - 1);
      for (let breakIndex = startIndex + 1; breakIndex <= maxBreak; breakIndex += 1) {
        const current = words.slice(startIndex, breakIndex).join(" ").trim();
        if (!current) continue;
        const rest = solve(breakIndex, linesRemaining - 1);
        const totalScore = scoreLine(current) + rest.score;
        if (!best || totalScore < best.score) {
          best = {
            score: totalScore,
            lines: [current, ...rest.lines],
          };
        }
      }
      const fallback = best || { score: scoreLine(compact), lines: [compact] };
      memo.set(key, fallback);
      return fallback;
    };
    const desiredLines = clamp(Math.ceil(compact.length / targetLength), 2, maxLines);
    let best = null;
    for (let lineCount = desiredLines; lineCount <= Math.min(maxLines, words.length); lineCount += 1) {
      const candidate = solve(0, lineCount);
      const fits = candidate.lines.every((line) => (
        typeof measureLine !== "function" || measureLine(line) <= maxWidth
      ));
      if (fits) return candidate.lines.filter(Boolean);
      if (!best || candidate.score < best.score) best = candidate;
    }
    return (best?.lines || [compact]).filter(Boolean);
  };
  const captionLayoutMetrics = () => {
    const shellWidth = Math.max(
      320,
      Number(mediaShell?.getBoundingClientRect().width || player.getBoundingClientRect().width || 1280),
    );
    const horizontalInset = clamp(shellWidth * 0.03, 18, 34) * 2;
    const boxedCaption = !["off", "shadow"].includes(subtitlePreferences?.background || "shadow");
    return {
      shellWidth,
      availableWidth: Math.max(240, shellWidth - horizontalInset - (boxedCaption ? 40 : 0)),
    };
  };
  const captionLineMeasurer = (fontSize) => {
    const measurementCanvas = document.createElement("canvas");
    const context = measurementCanvas.getContext("2d");
    if (!context || !captionText) return null;
    const computedTextStyle = window.getComputedStyle(captionText);
    context.font = `${computedTextStyle.fontWeight} ${fontSize}px ${computedTextStyle.fontFamily}`;
    return (line) => context.measureText(
      String(line || "").replace(/[\u200E\u200F\u2066-\u2069]/gu, "").trim(),
    ).width + 4;
  };
  const captionLines = (value, language) => {
    const lines = String(value || "")
      .trim()
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (language !== "ar") return lines;
    const normalizedLines = lines.map((line) => {
      const normalized = line
        .replace(/^[\s\u200E\u200F\u2066-\u2069]*[-–]\s*/u, "")
        .replace(/\s*[-–][\s\u200E\u200F\u2066-\u2069]*$/u, "")
        .trim();
      return normalized === line ? line : `\u2067-\u00A0${normalized}\u2069`;
    });
    const dialogueLines = normalizedLines.filter((line) => (
      line.replace(/[\u200E\u200F\u2066-\u2069]/gu, "").trim().startsWith("-")
    ));
    if (dialogueLines.length === 2 && normalizedLines.length === 2) return normalizedLines;
    const collapsed = normalizedLines.join(" ").replace(/\s+/g, " ").trim();
    const requestedSize = Number(subtitlePreferences?.size || 36);
    const { availableWidth } = captionLayoutMetrics();
    const targetLength = clamp(
      Math.floor(availableWidth / Math.max(1, requestedSize * 0.54)),
      18,
      30,
    );
    return balanceCaptionLines(collapsed, {
      maxLines: 2,
      targetLength,
      maxWidth: availableWidth,
      measureLine: captionLineMeasurer(requestedSize),
    });
  };
  const clearCaptionText = () => {
    captionText.replaceChildren();
    captionText.textContent = "";
    captionText.removeAttribute("lang");
  };
  const resetCaptionFit = () => {
    captionFitSize = null;
    captionFitSignature = "";
    captionText?.style.removeProperty("--caption-effective-size");
  };
  const computeCaptionFit = (entry, language = "default", { force = false } = {}) => {
    if (!captionChip || !captionText || language !== "ar") {
      resetCaptionFit();
      return;
    }
    if (!entry?.cues?.length) return;
    const preferredSize = Math.min(Number(subtitlePreferences?.size || 34), 118);
    const { availableWidth } = captionLayoutMetrics();
    const widthBucket = Math.round(availableWidth / 24);
    const signature = [
      selectedSubtitleIndex,
      subtitlePreferencesLanguage,
      subtitlePreferences?.font || "",
      subtitlePreferences?.size || "",
      entry.cues.length,
      widthBucket,
    ].join(":");
    if (!force && signature === captionFitSignature && captionFitSize) {
      captionText.style.setProperty("--caption-effective-size", `${captionFitSize}px`);
      updateSubtitleSizeLabel();
      return;
    }
    captionFitSignature = signature;
    captionFitSize = preferredSize;
    captionText.style.setProperty("--caption-effective-size", `${captionFitSize}px`);
    updateSubtitleSizeLabel();
  };
  const fitCaptionText = (entry, language = "default") => {
    if (!captionText) return;
    computeCaptionFit(entry, language);
    if (captionFitSize) {
      captionText.style.setProperty("--caption-effective-size", `${captionFitSize}px`);
    } else {
      captionText.style.removeProperty("--caption-effective-size");
    }
  };
  const renderCaptionLines = (lines = [], language = "default") => {
    const normalized = lines
      .map((line) => String(line || "").trim())
      .filter(Boolean);
    if (!normalized.length) {
      clearCaptionText();
      return;
    }
    const fragment = document.createDocumentFragment();
    normalized.forEach((line) => {
      const lineElement = document.createElement("span");
      lineElement.className = "movie-player__caption-line";
      lineElement.dir = language === "ar" ? "rtl" : "auto";
      lineElement.textContent = line;
      fragment.append(lineElement);
    });
    captionText.replaceChildren(fragment);
    if (language) captionText.lang = language;
    else captionText.removeAttribute("lang");
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
    const episode = Number(packEpisode?.value || 0) || meta.episode || null;
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
    if (savedProgress?.seconds) {
      launchTitle.textContent = `Resume selected episode from ${formatTime(savedProgress.seconds)}`;
      setStatus(`Ready to resume S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")} from ${formatTime(savedProgress.seconds)}.`);
    } else {
      setStatus(`Ready to play S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")} from the selected season pack.`);
    }
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
      const queryEpisode = requestedEpisodeFromUrl(season);
      const routeEpisode = configuredSelectedEpisode();
      const preferredEpisode = queryEpisode || routeEpisode || meta.episode || null;
      if (preferredEpisode) packEpisode.value = String(preferredEpisode);
      syncPlayerTitle();
      syncEpisodeUrl({ replace: true });
      void loadSavedProgress();
      syncPackLaunchState();
    } catch (error) {
      packEpisode.disabled = true;
      setPackStatus(String(error?.message || "Episode lookup is unavailable."));
      launch.disabled = true;
    }
  };

  const renderActiveCaption = () => {
    if (!captionLayer || !captionChip || !captionText) return;
    if (!subtitlePreferences) loadSubtitlePreferences(subtitlePreferencesLanguage);
    const entry = subtitleEntries[selectedSubtitleIndex] || null;
    if (!entry?.ready || !entry.cues?.length) {
      captionLayer.hidden = true;
      captionChip.hidden = true;
      clearCaptionText();
      resetCaptionDirection();
      return;
    }
    const moment = effectiveCurrentTime() + Number(subtitlePreferences.offset || 0);
    const active = entry.cues.filter((cue) => cue.startTime <= moment && cue.endTime >= moment);
    if (!active.length) {
      captionLayer.hidden = true;
      captionChip.hidden = true;
      clearCaptionText();
      resetCaptionDirection();
      return;
    }
    const language = String(entry.item?.language || "").toLowerCase();
    const isArabic = language === "ar";
    player.dataset.captionLanguage = isArabic ? "ar" : "default";
    captionChip.dir = isArabic ? "rtl" : "auto";
    captionText.dir = isArabic ? "rtl" : "auto";
    renderCaptionLines(
      active.flatMap((cue) => captionLines(cue.text, language)),
      language,
    );
    captionLayer.hidden = false;
    captionChip.hidden = false;
    fitCaptionText(entry, language);
    window.requestAnimationFrame(() => fitCaptionText(entry, language));
    document.fonts?.ready.then(() => computeCaptionFit(entry, language, { force: true })).catch(() => {});
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
    resetCaptionFit();
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
    const language = String(entry.item?.language || "default").toLowerCase();
    if (language !== subtitlePreferencesLanguage) {
      loadSubtitlePreferences(language);
      updateSubtitlePreferenceLabels();
    }
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

  const stopLocal = async ({ silent = false, persistProgress = true } = {}) => {
    if (persistProgress) await saveMovieProgress({ force: true });
    clearPoll();
    clearVideoPaintCheck();
    window.clearTimeout(progressSaveTimer);
    progressSaveTimer = 0;
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
    activeKind = "";
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
      if (savedProgress?.seconds) {
        launchTitle.textContent = `Resume from ${formatTime(savedProgress.seconds)}`;
        setStatus(`Ready to resume local playback from ${formatTime(savedProgress.seconds)}. The magnet starts only after you press play.`);
      } else {
        setStatus("Ready. The magnet will start only after you press play.");
      }
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
    const session = localSession;
    if (!session) return;
    try {
      const response = await fetch(session.statusUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (localSession !== session) return;
      if (!response.ok) throw new Error(payload?.error?.message || "Local player unavailable");
      renderLocalStatus(payload.session || {});
      if (payload.session?.state === "failed") {
        throw new Error(payload.session.message || "Local player failed");
      }
      if (payload.session?.state === "ready") {
        session.streamUrl = payload.session.stream_url || session.streamUrl;
        session.transcodeUrl = payload.session.transcode_url || session.transcodeUrl;
        session.streamKind = payload.session.stream_kind || session.streamKind || "direct";
        if (!video.hasAttribute("src")) {
          const playbackUrl = localPlaybackUrl();
          if (!playbackUrl) {
            throw new Error(
              session.streamKind === "transcode"
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
            session.streamKind === "transcode"
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
      if (localSession !== session) return;
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
      episodeTitle: selection.episodeTitle || selectedEpisodeTitle() || configuredSelectedEpisodeTitle(),
      runtimeSeconds: selectedEpisodeRuntimeSeconds() || configuredRuntimeSeconds(),
    };
    localSession = {
      statusUrl: payload.status_url,
      streamUrl: payload.stream_url,
      transcodeUrl: payload.transcode_url,
      streamKind: payload.session?.stream_kind || "direct",
      stopUrl: payload.stop_url,
      playbackOffset: Number(selection.resumeSeconds || 0) || 0,
      pendingDirectSeek: Number(selection.resumeSeconds || 0) || 0,
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
    savedProgress = null;
    progressLoaded = false;
    lastProgressSentAt = 0;
    activeSelection.season = configuredSelectedSeason() || selectedSourceMeta()?.season || null;
    activeSelection.episode = configuredSelectedEpisode() || selectedSourceMeta()?.episode || null;
    activeSelection.runtimeSeconds = configuredRuntimeSeconds();
    activeSelection.episodeTitle = configuredSelectedEpisodeTitle();
    resetViewport();
    syncEpisodeUrl();
    syncSourceUi();
    void loadSavedProgress();
  });
  packEpisode?.addEventListener("change", async () => {
    const localWasActive = activeKind === "local" && (Boolean(localSession) || !video.hidden || video.hasAttribute("src"));
    if (localWasActive) {
      await stopLocal({ silent: true });
      resetViewport();
    }
    subtitleOptions = null;
    subtitleOptionsKey = "";
    savedProgress = null;
    progressLoaded = false;
    lastProgressSentAt = 0;
    activeSelection.season = selectedSourceMeta()?.season || null;
    activeSelection.episode = Number(packEpisode.value || 0) || null;
    activeSelection.runtimeSeconds = selectedEpisodeRuntimeSeconds();
    activeSelection.episodeTitle = selectedEpisodeTitle();
    syncPlayerTitle();
    syncEpisodeUrl();
    syncSourceUi();
    syncTimeline();
    void loadSavedProgress();
  });

  launch.addEventListener("click", async () => {
    launch.disabled = true;
    activeKind = selectedKind();
    try {
      if (activeKind === "local") {
        const meta = selectedSourceMeta();
        const scope = selectedEpisodeScope();
        const selection = scope.season || scope.episode
          ? {
            season: scope.season,
            episode: scope.episode,
            episodeTitle: activeSelection.episodeTitle || configuredSelectedEpisodeTitle() || selectedEpisodeTitle(),
          }
          : {};
        if (savedProgress?.seconds) selection.resumeSeconds = savedProgress.seconds;
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
  subtitlePreset?.addEventListener("change", () => {
    applySubtitlePreset(subtitlePreset.value || "netflix");
    showControlsBriefly();
  });
  subtitleSize?.addEventListener("input", () => {
    subtitlePreferences.size = Number(subtitleSize.value || 30);
    subtitlePreferences.preset = "custom";
    resetCaptionFit();
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  });
  subtitlePosition?.addEventListener("input", () => {
    subtitlePreferences.position = Number(subtitlePosition.value || 12);
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  });
  subtitleBackground?.addEventListener("change", () => {
    subtitlePreferences.background = subtitleBackground.value || "shadow";
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleOpacity?.addEventListener("input", () => {
    subtitlePreferences.backgroundOpacity = Number(subtitleOpacity.value || 35);
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleBlur?.addEventListener("input", () => {
    subtitlePreferences.blur = Number(subtitleBlur.value || 0);
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleShadow?.addEventListener("input", () => {
    subtitlePreferences.shadow = Number(subtitleShadow.value || 80);
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  });
  subtitleOffset?.addEventListener("input", () => {
    subtitlePreferences.offset = Number(subtitleOffset.value || 0);
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  });
  subtitleFont?.addEventListener("change", () => {
    subtitlePreferences.font = subtitleFont.value || "noto-arabic";
    subtitlePreferences.preset = "custom";
    resetCaptionFit();
    updateSubtitlePreferenceLabels();
    renderActiveCaption();
    saveSubtitlePreferences();
  });
  subtitleColors.forEach((button) => button.addEventListener("click", () => {
    subtitlePreferences.color = button.dataset.color || "#ffffff";
    subtitlePreferences.preset = "custom";
    updateSubtitlePreferenceLabels();
    saveSubtitlePreferences();
  }));
  subtitleReset?.addEventListener("click", () => {
    subtitlePreferences = sanitizeSubtitlePreferences(null, subtitlePreferencesLanguage);
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
    if (
      activeKind === "local"
      && localSession?.streamKind !== "transcode"
      && Number(localSession?.pendingDirectSeek || 0) > 0
    ) {
      const target = Number(localSession.pendingDirectSeek || 0);
      const duration = displayDurationSeconds() || target;
      video.currentTime = Math.max(0, Math.min(duration, target));
      localSession.playbackOffset = 0;
      localSession.pendingDirectSeek = 0;
      setPlayerState("buffering", `Resuming from ${formatTime(target)}…`);
    }
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
    scheduleProgressSave();
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
    void saveMovieProgress({ force: true });
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
  syncEpisodeUrl({ replace: true });
  const persistProgressBeforeHide = () => {
    void saveMovieProgress({ force: true, keepalive: true });
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") persistProgressBeforeHide();
  });
  window.addEventListener("pagehide", () => {
    persistProgressBeforeHide();
    // Do not await another request before starting the shutdown fetch. During
    // page unload, that delay can leave the WebTorrent session running.
    void stopLocal({ silent: true, persistProgress: false });
  });
  void loadSavedProgress();
  syncSourceUi();
})();
