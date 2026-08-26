(async () => {
  let syncEngine;
  try {
    syncEngine = await import("./subtitle-sync.mjs");
  } catch (error) {
    console.error("Dragon subtitle sync could not load.", error);
    return;
  }
  const {
    adjustSubtitleSync,
    calibrateOnePoint,
    calibrateTwoPoints,
    defaultSubtitleSyncProfile,
    nearestSubtitleCueIndexAt,
    normalizeSubtitleSyncProfile,
    resyncSubtitleFromHere,
    subtitleSyncStorageKey,
    subtitleSyncSummary,
    transformSubtitleCue,
  } = syncEngine;
  const player = document.querySelector("[data-movie-player]");
  if (!player) return;

  const playerTitle = player.querySelector("#movie-player-title");
  const selectedEpisodeSummary = document.querySelector("[data-player-selected-episode]");
  const source = player.querySelector("[data-player-source]");
  const sourceFacts = player.querySelector("[data-player-source-facts]");
  const sourceFactName = player.querySelector("[data-player-source-name]");
  const sourceFactType = player.querySelector("[data-player-source-type]");
  const sourceFactHealth = player.querySelector("[data-player-source-health]");
  const sourceFactPriority = player.querySelector("[data-player-source-priority]");
  const launch = player.querySelector("[data-player-launch]");
  const launchTitle = player.querySelector("[data-player-launch-title]");
  const launchHint = player.querySelector("[data-player-launch-hint]");
  const recovery = player.querySelector("[data-player-recovery]");
  const recoveryMessage = player.querySelector("[data-player-recovery-message]");
  const inlineRetry = player.querySelector("[data-player-retry-inline]");
  const inlineFallback = player.querySelector("[data-player-fallback-inline]");
  const findRelease = player.querySelector("[data-player-find-release]");
  const externalToolbar = player.querySelector("[data-player-external-toolbar]");
  const externalCaption = player.querySelector("[data-player-external-caption]");
  const externalBack = player.querySelector("[data-player-external-back]");
  const externalFullscreen = player.querySelector("[data-player-external-fullscreen]");
  const externalReload = player.querySelector("[data-player-external-reload]");
  const externalOpen = player.querySelector("[data-player-external-open]");
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
  const retry = player.querySelector("[data-player-retry]");
  const fallback = player.querySelector("[data-player-fallback]");
  const markIntro = player.querySelector("[data-player-mark-intro]");
  const markRecap = player.querySelector("[data-player-mark-recap]");
  const quickToggles = Array.from(player.querySelectorAll("[data-player-quick-toggle]"));
  const quickBack = player.querySelector("[data-player-quick-back]");
  const quickForward = player.querySelector("[data-player-quick-forward]");
  const skipIntro = player.querySelector("[data-player-skip-intro]");
  const skipRecap = player.querySelector("[data-player-skip-recap]");
  const bookmark = player.querySelector("[data-player-bookmark]");
  const bookmarksList = player.querySelector("[data-player-bookmarks]");
  const quickMute = player.querySelector("[data-player-quick-mute]");
  const quickPip = player.querySelector("[data-player-quick-pip]");
  const quickRate = player.querySelector("[data-player-quick-rate]");
  const audioSelect = player.querySelector("[data-player-audio]");
  const audioWrap = player.querySelector("[data-player-audio-wrap]");
  const quickShortcuts = player.querySelector("[data-player-shortcuts]");
  const quickFullscreen = player.querySelector("[data-player-quick-fullscreen]");
  const playerBack = player.querySelector("[data-player-back]");
  const sourceReturn = player.querySelector("[data-player-source-return]");
  const playIcon = player.querySelector("[data-player-play-icon]");
  const centerIcon = player.querySelector("[data-player-center-icon]");
  const muteIcon = player.querySelector("[data-player-mute-icon]");
  const timeline = player.querySelector("[data-player-timeline]");
  const volume = player.querySelector("[data-player-volume]");
  const volumeFeedback = player.querySelector("[data-player-volume-feedback]");
  const volumeFeedbackValue = player.querySelector("[data-player-volume-value]");
  const timeLabel = player.querySelector("[data-player-time]");
  const captionToggle = player.querySelector("[data-player-caption-toggle]");
  const dragonEpisode = player.querySelector("[data-player-dragon-episode]");
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
  const subtitleSync = player.querySelector("[data-player-subtitle-sync]");
  const subtitleSyncStatus = player.querySelector("[data-player-subtitle-sync-status]");
  const subtitleSyncReference = player.querySelector("[data-player-subtitle-sync-reference]");
  const subtitleSyncNow = player.querySelector("[data-player-subtitle-sync-now]");
  const subtitleSyncAdjustments = Array.from(player.querySelectorAll("[data-player-subtitle-sync-adjust]"));
  const subtitleSyncSearch = player.querySelector("[data-player-subtitle-sync-search]");
  const subtitleSyncResults = player.querySelector("[data-player-subtitle-sync-results]");
  const subtitleSyncSecond = player.querySelector("[data-player-subtitle-sync-second]");
  const subtitleSyncResync = player.querySelector("[data-player-subtitle-sync-resync]");
  const subtitleSyncReset = player.querySelector("[data-player-subtitle-sync-reset]");
  const subtitleSyncControls = Array.from(player.querySelectorAll(
    "[data-player-subtitle-sync-now], [data-player-subtitle-sync-adjust], [data-player-subtitle-sync-search], [data-player-subtitle-sync-second], [data-player-subtitle-sync-resync], [data-player-subtitle-sync-reset]",
  ));
  const packBrowser = player.querySelector("[data-player-pack-browser]");
  const packHeading = player.querySelector("[data-player-pack-heading]");
  const packEpisode = player.querySelector("[data-player-pack-episode]");
  const packStatus = player.querySelector("[data-player-pack-status]");
  const nextEpisode = player.querySelector("[data-player-next]");
  const nextCountdown = player.querySelector("[data-player-next-countdown]");
  const nextPlay = player.querySelector("[data-player-next-play]");
  const nextCancel = player.querySelector("[data-player-next-cancel]");
  const nextReplay = player.querySelector("[data-player-next-replay]");
  const autoNextToggle = player.querySelector("[data-player-auto-next]");
  const startOver = player.querySelector("[data-player-start-over]");
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
      color: "#ffffff",
      font: "tajawal",
    },
  };
  let sourceUrl = "";
  let sourceSandbox = "";
  let resolvedSourceId = "";
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
  let embedCinemaMode = false;
  let embedCinemaUsesBrowserFullscreen = false;
  let volumeFeedbackTimer = 0;
  let subtitlePanelOpen = false;
  let selectedSubtitleIndex = -1;
  let subtitleEntries = [];
  let subtitlePreferencesLanguage = "default";
  let subtitlePreferences = null;
  let subtitleSyncSearchTerm = "";
  let captionFitSize = null;
  let captionFitSignature = "";
  let savedProgress = null;
  let progressLoaded = false;
  let progressSaveTimer = 0;
  let lastProgressSentAt = 0;
  let progressRequestToken = 0;
  let nextEpisodeTimer = 0;
  const autoNextPreferenceKey = "dragon:player-auto-next:v1";
  let autoNextEnabled = true;
  const playerMarkersKey = `dragon:player-markers:v1:${player.dataset.mediaId || "unknown"}`;
  let playerMarkers = { intro: null, recap: null, bookmarks: [] };
  let subtitleOpener = null;
  const playbackTransitions = {
    idle: ["preparing", "stopped"],
    preparing: ["buffering", "failed", "stopped"],
    buffering: ["playing", "stalled", "failed", "stopped"],
    playing: ["buffering", "stalled", "failed", "stopped"],
    stalled: ["buffering", "failed", "stopped"],
    failed: ["preparing", "stopped"],
    stopped: ["preparing", "idle"],
  };
  const effectiveCurrentTime = () => {
    const playbackOffset = Number(localSession?.playbackOffset || 0);
    return playbackOffset + Number(video.currentTime || 0);
  };
  const renderBookmarks = () => {
    if (!bookmarksList) return;
    const items = playerMarkers.bookmarks.slice(-5).reverse();
    bookmarksList.hidden = !items.length;
    bookmarksList.replaceChildren();
    items.forEach((entry) => {
      const item = document.createElement("div");
      item.className = "movie-player__bookmark";
      const jump = document.createElement("button");
      jump.type = "button";
      jump.textContent = `${formatTime(entry.seconds)}${entry.note ? ` · ${entry.note}` : ""}`;
      jump.addEventListener("click", () => seekRelative(Number(entry.seconds || 0) - effectiveCurrentTime()));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "movie-player__bookmark-remove";
      remove.setAttribute("aria-label", `Remove bookmark at ${formatTime(entry.seconds)}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        playerMarkers.bookmarks = playerMarkers.bookmarks.filter((candidate) => candidate.createdAt !== entry.createdAt);
        savePlayerMarkers();
      });
      item.append(jump, remove);
      bookmarksList.append(item);
    });
  };
  const loadPlayerMarkers = () => {
    try {
      const stored = JSON.parse(window.localStorage.getItem(playerMarkersKey) || "{}");
      playerMarkers = {
        intro: Number(stored.intro) || null,
        recap: Number(stored.recap) || null,
        bookmarks: Array.isArray(stored.bookmarks) ? stored.bookmarks.slice(-30) : [],
      };
    } catch (_error) {
      playerMarkers = { intro: null, recap: null, bookmarks: [] };
    }
    skipIntro.hidden = !playerMarkers.intro;
    skipRecap.hidden = !playerMarkers.recap;
    renderBookmarks();
  };
  const savePlayerMarkers = () => {
    window.localStorage.setItem(playerMarkersKey, JSON.stringify(playerMarkers));
    loadPlayerMarkers();
  };
  const clearNextEpisode = () => {
    window.clearInterval(nextEpisodeTimer);
    nextEpisodeTimer = 0;
    if (nextEpisode) nextEpisode.hidden = true;
  };
  const saveAutoNextPreference = () => {
    try {
      window.localStorage.setItem(autoNextPreferenceKey, autoNextEnabled ? "true" : "false");
    } catch (_error) {
      // A blocked storage area should not prevent an explicit player choice.
    }
    if (autoNextToggle) autoNextToggle.checked = autoNextEnabled;
  };
  const openNextEpisode = () => {
    const url = String(player.dataset.nextEpisodeUrl || "").trim();
    if (!url) return;
    clearNextEpisode();
    window.location.assign(url);
  };
  const queueNextEpisode = () => {
    const url = String(player.dataset.nextEpisodeUrl || "").trim();
    if (!nextEpisode || !url || !autoNextEnabled) return;
    clearNextEpisode();
    let seconds = 10;
    nextEpisode.hidden = false;
    if (nextCountdown) nextCountdown.textContent = String(seconds);
    nextEpisodeTimer = window.setInterval(() => {
      seconds -= 1;
      if (nextCountdown) nextCountdown.textContent = String(Math.max(0, seconds));
      if (seconds <= 0) {
        openNextEpisode();
      }
    }, 1000);
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

  const optionalNonNegativeNumber = (value) => {
    if (value === null || value === undefined || String(value).trim() === "") return null;
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
  };
  const selectedKind = () => source.selectedOptions[0]?.dataset.kind || "embed";
  const selectedOption = () => source.selectedOptions[0] || null;
  const selectedProvider = () => selectedOption()?.dataset.provider || "local";
  const selectedProviderLabel = () => selectedOption()?.dataset.providerLabel || "Local";
  const selectedEmbedEndpoint = () => selectedOption()?.dataset.embedEndpoint || "";
  const syncSourceFacts = () => {
    const option = selectedOption();
    if (!sourceFacts || !option) return;
    const kind = selectedKind();
    const health = String(option.dataset.sourceHealth || "UNKNOWN").toUpperCase();
    const checked = option.dataset.sourceHealthChecked === "true";
    const priority = String(option.dataset.sourcePriority || "").trim();
    if (sourceFactName) sourceFactName.textContent = option.textContent?.trim() || "Selected source";
    if (sourceFactType) {
      sourceFactType.textContent = option.dataset.sourceType
        || (kind === "local" ? "Local runtime source" : "Configured embed provider");
    }
    if (sourceFactHealth) {
      sourceFactHealth.textContent = health === "UNKNOWN"
        ? (checked ? "Last health check expired" : "Health not checked")
        : `Health: ${health.toLowerCase()}`;
      sourceFactHealth.dataset.health = health.toLowerCase();
    }
    if (sourceFactPriority) {
      sourceFactPriority.textContent = priority ? `Priority ${priority}` : "Default priority";
    }
  };
  const selectedSourceMeta = () => {
    const option = selectedOption();
    if (!option || option.dataset.kind !== "local") return null;
    const season = optionalNonNegativeNumber(option.dataset.sourceSeason);
    const episode = optionalNonNegativeNumber(option.dataset.sourceEpisode);
    return {
      sourceId: option.value,
      seasonPack: option.dataset.sourceSeasonPack === "true",
      season,
      episode,
      releaseMode: String(option.dataset.sourceReleaseMode || ""),
      label: option.textContent?.trim() || "Local source",
      quality: String(option.dataset.sourceQuality || ""),
      codec: String(option.dataset.sourceCodec || ""),
      playback: String(option.dataset.sourcePlayback || ""),
      size: String(option.dataset.sourceSize || ""),
      hdr: option.dataset.sourceHdr === "true",
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
    const previous = player.dataset.playbackState || "idle";
    if (!playbackTransitions[previous]?.includes(state) && previous !== state) {
      player.dataset.playbackState = "idle";
    }
    player.dataset.playbackState = state;
    if (activeKind === "local") {
      badge.textContent = `Local · ${state.charAt(0).toUpperCase()}${state.slice(1)}`;
    }
    if (message) setStatus(message);
  };
  const setWatchMode = (enabled) => {
    player.classList.toggle("is-watch-mode", Boolean(enabled));
  };
  const setSubtitleStatus = (message) => {
    if (!subtitleStatus) return;
    subtitleStatus.textContent = message;
    subtitleStatus.hidden = !message;
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
    const legacyPreset = merged.preset === "dragon-standard"
      ? "netflix"
      : merged.preset === "compact"
        ? "youtube"
        : merged.preset;
    const preset = legacyPreset === "custom" || subtitlePresetValues[legacyPreset]
      ? legacyPreset
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
    if (subtitlePanelOpen && !subtitleOpener) subtitleOpener = document.activeElement;
    subtitlePanel.hidden = !subtitlePanelOpen;
    subtitlePanel.setAttribute("aria-hidden", subtitlePanelOpen ? "false" : "true");
    captionToggle?.setAttribute("aria-pressed", subtitlePanelOpen ? "true" : "false");
    if (subtitlePanelOpen) {
      mediaShell?.setAttribute("data-controls-visible", "true");
      setSubtitleScreen("list");
      const entry = activeSubtitleEntry();
      if (entry?.ready) {
        entry.syncReferencePinned = false;
        refreshSubtitleSync();
      }
      window.requestAnimationFrame(() => subtitleClose?.focus());
    } else if (subtitleOpener instanceof HTMLElement) {
      const opener = subtitleOpener;
      subtitleOpener = null;
      window.requestAnimationFrame(() => opener.focus());
    }
  };

  const trapSubtitlePanelFocus = (event) => {
    if (!subtitlePanelOpen || event.key !== "Tab" || !subtitlePanel) return;
    const focusable = Array.from(subtitlePanel.querySelectorAll(
      "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
    )).filter((element) => !element.hidden);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
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
  const cleanCaptionText = (value) => String(value || "")
    .replace(/\\N/gu, "\n")
    .replace(/\\h/gu, " ")
    .replace(/\{\\[^}]*\}/gu, "")
    .replace(/<br\s*\/?\s*>/giu, "\n")
    .replace(/<\/?[^>]+>/gu, "")
    .replace(/[\u200E\u200F\u2066-\u2069]/gu, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
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
      const cueText = cleanCaptionText(cueLines.join("\n"));
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
  const subtitleContentFingerprint = async (text, fallback) => {
    try {
      if (!window.crypto?.subtle) throw new Error("Web Crypto is unavailable");
      const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(text || "")));
      return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    } catch (_error) {
      // The VTT hash is preferred. This stable signed track URL fallback keeps sync
      // isolated if an older browser does not expose Web Crypto.
      return `track-${String(fallback || "unknown").replace(/[^a-z0-9]+/giu, "-").slice(-180)}`;
    }
  };
  const activeSubtitleEntry = () => subtitleEntries[selectedSubtitleIndex] || null;
  const subtitleSyncKeyFor = (entry) => {
    const sourceId = selectedSourceMeta()?.sourceId || "";
    if (!entry?.subtitleId || !sourceId) return "";
    return subtitleSyncStorageKey({
      movieId: player.dataset.mediaId || "unknown",
      sourceId,
      subtitleId: entry.subtitleId,
    });
  };
  const transformedSubtitleCues = (entry) => {
    const profile = normalizeSubtitleSyncProfile(entry?.syncProfile);
    return (entry?.cues || []).map((cue, originalIndex) => {
      const timing = transformSubtitleCue({ start_ms: Math.round(cue.startTime * 1000), end_ms: Math.round(cue.endTime * 1000) }, profile);
      return {
        ...cue,
        originalIndex,
        originalStartMs: Math.round(cue.startTime * 1000),
        originalEndMs: Math.round(cue.endTime * 1000),
        start_ms: timing.start_ms,
        end_ms: timing.end_ms,
        startTime: timing.start_ms / 1000,
        endTime: timing.end_ms / 1000,
      };
    });
  };
  const saveSubtitleSync = (entry) => {
    const key = subtitleSyncKeyFor(entry);
    if (!key || !entry?.syncProfile) return;
    try {
      window.localStorage.setItem(key, JSON.stringify(entry.syncProfile));
    } catch (_error) {
      setSubtitleStatus("Subtitle sync changed for this session, but could not be saved.");
    }
  };
  const loadSubtitleSync = (entry) => {
    const key = subtitleSyncKeyFor(entry);
    let profile = defaultSubtitleSyncProfile();
    try {
      const stored = key ? window.localStorage.getItem(key) : "";
      profile = stored ? normalizeSubtitleSyncProfile(JSON.parse(stored)) : defaultSubtitleSyncProfile();
      // Migrate the previous per-language presentation delay once, into this exact
      // source + subtitle profile. Later resets therefore restore original timing.
      const legacyOffsetMs = Math.round(Number(subtitlePreferences?.offset || 0) * 1000);
      if (!stored && legacyOffsetMs) {
        profile = adjustSubtitleSync(profile, legacyOffsetMs);
        subtitlePreferences.offset = 0;
        saveSubtitlePreferences();
        entry.syncProfile = profile;
        saveSubtitleSync(entry);
      }
    } catch (_error) {
      profile = defaultSubtitleSyncProfile();
    }
    entry.syncProfile = profile;
    entry.transformedCues = transformedSubtitleCues(entry);
  };
  const selectedSyncCue = (entry = activeSubtitleEntry()) => {
    const index = Number(entry?.syncReferenceIndex);
    return Number.isInteger(index) && entry?.cues?.[index] ? entry.cues[index] : null;
  };
  const chooseSyncCue = (entry, index) => {
    if (!entry?.cues?.[index]) return;
    entry.syncReferenceIndex = index;
    entry.syncReferencePinned = true;
    refreshSubtitleSync();
  };
  const nearestSubtitleCueIndex = (entry) => {
    if (!entry?.transformedCues?.length) return -1;
    const currentMs = Math.round(effectiveCurrentTime() * 1000);
    return nearestSubtitleCueIndexAt(entry.transformedCues, currentMs);
  };
  const syncCueForAction = (entry) => {
    if (!entry) return null;
    if (!entry.syncReferencePinned) {
      const nearestIndex = nearestSubtitleCueIndex(entry);
      if (nearestIndex >= 0) entry.syncReferenceIndex = nearestIndex;
    }
    return selectedSyncCue(entry);
  };
  const formatSyncTime = (milliseconds) => {
    const total = Math.max(0, Math.round(Number(milliseconds || 0)));
    const hours = Math.floor(total / 3_600_000);
    const minutes = Math.floor((total % 3_600_000) / 60_000);
    const seconds = ((total % 60_000) / 1000).toFixed(1).padStart(4, "0");
    return `${hours ? `${hours}:` : ""}${String(minutes).padStart(hours ? 2 : 1, "0")}:${seconds}`;
  };
  const refreshSubtitleSync = (notice = "") => {
    const entry = activeSubtitleEntry();
    const ready = Boolean(entry?.ready && entry?.syncProfile && entry.cues?.length);
    subtitleSyncControls.forEach((control) => {
      control.disabled = !ready;
      control.setAttribute("aria-disabled", ready ? "false" : "true");
    });
    if (!ready) {
      if (subtitleSyncStatus) subtitleSyncStatus.textContent = "Choose a subtitle track";
      if (subtitleSyncReference) subtitleSyncReference.textContent = "Choose a subtitle track to unlock the repair controls.";
      subtitleSyncResults?.replaceChildren();
      return;
    }
    if (!selectedSyncCue(entry) || !entry.syncReferencePinned) entry.syncReferenceIndex = nearestSubtitleCueIndex(entry);
    const reference = selectedSyncCue(entry);
    const referenceTiming = entry.transformedCues?.[Number(entry.syncReferenceIndex)] || reference;
    if (subtitleSyncStatus) subtitleSyncStatus.textContent = notice ? `${notice} · ${subtitleSyncSummary(entry.syncProfile)}` : subtitleSyncSummary(entry.syncProfile);
    if (subtitleSyncReference) {
      subtitleSyncReference.textContent = reference
        ? `Selected · video ${formatSyncTime(referenceTiming.startTime * 1000)} · original ${formatSyncTime(reference.startTime * 1000)} · ${reference.text.replace(/\s+/gu, " ").slice(0, 76)}`
        : "Find and select the subtitle line that belongs here.";
    }
    if (!subtitleSyncResults) return;
    subtitleSyncResults.replaceChildren();
    const term = subtitleSyncSearchTerm.trim().toLocaleLowerCase();
    const referenceIndex = Number(entry.syncReferenceIndex || 0);
    const candidates = term.length >= 2
      ? entry.cues.map((cue, index) => ({ cue, index })).filter(({ cue }) => cue.text.toLocaleLowerCase().includes(term)).slice(0, 12)
      : entry.cues.slice(Math.max(0, referenceIndex - 3), referenceIndex + 4).map((cue, offset) => ({ cue, index: Math.max(0, referenceIndex - 3) + offset }));
    if (!candidates.length) {
      subtitleSyncResults.textContent = term ? "No matching subtitle lines." : "Type dialogue to find another subtitle line.";
      return;
    }
    candidates.forEach(({ cue, index }) => {
      const button = document.createElement("button");
      const correctedCue = entry.transformedCues?.[index] || cue;
      button.type = "button";
      button.className = index === entry.syncReferenceIndex ? "is-active" : "";
      button.dataset.playerSubtitleSyncCue = String(index);
      button.textContent = `Video ${formatSyncTime(correctedCue.startTime * 1000)} · original ${formatSyncTime(cue.startTime * 1000)} · ${cue.text.replace(/\s+/gu, " ").slice(0, 92)}`;
      subtitleSyncResults.append(button);
    });
  };
  const applySubtitleSyncProfile = (entry, profile, message) => {
    if (!entry) return;
    try {
      entry.syncProfile = normalizeSubtitleSyncProfile(profile);
      entry.transformedCues = transformedSubtitleCues(entry);
      saveSubtitleSync(entry);
      resetCaptionFit();
      renderActiveCaption();
      refreshSubtitleSync(message);
      if (message) setSubtitleStatus(`${message} ${subtitleSyncSummary(entry.syncProfile)}.`);
    } catch (error) {
      setSubtitleStatus(String(error?.message || "Subtitle sync could not be applied. Playback is unchanged."));
    }
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
  const configuredSelectedSeason = () => optionalNonNegativeNumber(player.dataset.selectedSeason);
  const configuredSelectedEpisode = () => optionalNonNegativeNumber(player.dataset.selectedEpisode);
  const configuredSelectedEpisodeTitle = () => String(player.dataset.selectedEpisodeTitle || "").trim();
  const syncPlayerTitle = () => {
    if (!playerTitle || player.dataset.mediaType !== "tv") return;
    const meta = selectedSourceMeta();
    const season = activeSelection.season ?? meta?.season ?? configuredSelectedSeason();
    const episode = activeSelection.episode
      ?? optionalNonNegativeNumber(packEpisode?.value)
      ?? meta?.episode
      ?? configuredSelectedEpisode();
    const episodeTitle = activeSelection.episodeTitle
      || selectedEpisodeTitle()
      || configuredSelectedEpisodeTitle();
    if (season === null || episode === null || !episodeTitle) return;
    const episodeCode = `S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")}`;
    playerTitle.textContent = `Watch ${episodeCode} · ${episodeTitle}`;
    if (selectedEpisodeSummary) {
      selectedEpisodeSummary.textContent = `Player episode selected: S${season}E${String(episode).padStart(2, "0")}`;
    }
  };
  const requestedEpisodeFromUrl = (season) => {
    const querySeason = optionalNonNegativeNumber(initialParams.get("season"));
    const queryEpisode = optionalNonNegativeNumber(initialParams.get("episode"));
    return querySeason === season && queryEpisode !== null ? queryEpisode : null;
  };
  const selectedEpisodeScope = () => {
    if (player.dataset.mediaType !== "tv") {
      return { season: null, episode: null };
    }
    const meta = selectedSourceMeta();
    const season = activeSelection.season ?? configuredSelectedSeason() ?? meta?.season ?? null;
    const episode = activeSelection.episode
      ?? optionalNonNegativeNumber(packEpisode?.value)
      ?? configuredSelectedEpisode()
      ?? requestedEpisodeFromUrl(season)
      ?? meta?.episode
      ?? null;
    return { season, episode };
  };
  const syncEpisodeUrl = ({ replace = false } = {}) => {
    if (player.dataset.mediaType !== "tv" || !window.history) return;
    const { season, episode } = selectedEpisodeScope();
    const url = new URL(window.location.href);
    if (season !== null && episode !== null) {
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
    if (dragonEpisode) {
      dragonEpisode.textContent = activeSelection.season !== null && activeSelection.episode !== null
        ? `S${String(activeSelection.season).padStart(2, "0")}E${String(activeSelection.episode).padStart(2, "0")}`
        : "";
    }
  };
  const showControlsBriefly = () => {
    if (!mediaShell) return;
    mediaShell.dataset.controlsVisible = "true";
    mediaShell.classList.add("is-controls-active");
    window.clearTimeout(controlsHideTimer);
    controlsHideTimer = window.setTimeout(() => {
      if (!video.paused) {
        mediaShell.dataset.controlsVisible = "false";
        mediaShell.classList.remove("is-controls-active");
      }
    }, 2200);
  };
  const syncFullscreenChrome = () => {
    if (!mediaShell) return;
    mediaShell.dataset.fullscreen = document.fullscreenElement === mediaShell ? "true" : "false";
    showControlsBriefly();
    window.requestAnimationFrame(() => renderActiveCaption());
  };
  const syncEmbedCinemaControls = () => {
    if (!externalFullscreen) return;
    const active = embedCinemaMode || document.fullscreenElement === player;
    externalFullscreen.textContent = active ? "Exit full screen" : "Full screen";
    externalFullscreen.setAttribute("aria-pressed", String(active));
    externalFullscreen.setAttribute("aria-label", active ? "Exit full screen" : "Enter full screen");
  };
  const setEmbedCinemaMode = (active) => {
    embedCinemaMode = active;
    player.classList.toggle("is-embed-fullscreen", active);
    document.documentElement.classList.toggle("is-player-embed-fullscreen", active);
    document.body.classList.toggle("is-player-embed-fullscreen", active);
    syncEmbedCinemaControls();
  };
  const exitEmbedCinemaMode = async () => {
    if (document.fullscreenElement === player) {
      await document.exitFullscreen?.();
    }
    embedCinemaUsesBrowserFullscreen = false;
    setEmbedCinemaMode(false);
  };
  const enterEmbedCinemaMode = () => {
    setEmbedCinemaMode(true);
    if (!player.requestFullscreen) return;
    player.requestFullscreen().then(() => {
      embedCinemaUsesBrowserFullscreen = document.fullscreenElement === player;
    }).catch(() => {
      // iPhone Safari does not expose element fullscreen for cross-origin frames.
      // The viewport-sized cinema mode remains available in that case.
      embedCinemaUsesBrowserFullscreen = false;
    });
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
  const showVolumeFeedback = () => {
    if (!volumeFeedback || !volumeFeedbackValue) return;
    window.clearTimeout(volumeFeedbackTimer);
    volumeFeedbackValue.textContent = `${Math.round(video.volume * 100)}%`;
    volumeFeedback.classList.remove("is-visible");
    void volumeFeedback.offsetWidth;
    volumeFeedback.classList.add("is-visible");
    volumeFeedbackTimer = window.setTimeout(() => volumeFeedback.classList.remove("is-visible"), 850);
  };
  const syncAudioTracks = () => {
    const tracks = Array.from(video.audioTracks || []);
    if (!audioSelect || !audioWrap) return;
    audioSelect.replaceChildren();
    tracks.forEach((track, index) => {
      const option = new Option(track.label || track.language || `Audio ${index + 1}`, String(index), track.enabled);
      audioSelect.add(option);
    });
    audioWrap.hidden = tracks.length < 2;
  };
  const currentSubtitleSelection = () => {
    const endpoint = player.dataset.subtitleEndpoint;
    if (!endpoint || selectedKind() !== "local") return { key: "", url: "", season: null, episode: null };
    const meta = selectedSourceMeta();
    const season = activeSelection.season ?? configuredSelectedSeason() ?? meta?.season ?? null;
    const episode = activeSelection.episode
      ?? optionalNonNegativeNumber(packEpisode?.value)
      ?? configuredSelectedEpisode()
      ?? meta?.episode
      ?? null;
    const episodeTitle = activeSelection.episodeTitle || selectedEpisodeTitle() || configuredSelectedEpisodeTitle();
    const url = new URL(endpoint, window.location.origin);
    if (player.dataset.mediaType === "tv") {
      if (season !== null) url.searchParams.set("season", String(season));
      if (episode !== null) url.searchParams.set("episode", String(episode));
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
      if (season === null || episode === null) return { url: "", season: null, episode: null };
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
  const saveMovieProgress = async ({ force = false, keepalive = false, ended = false } = {}) => {
    const target = progressTarget();
    const duration = Math.round(displayDurationSeconds());
    const current = Math.round(effectiveCurrentTime());
    if (!target.url || activeKind !== "local" || !duration || current < 5) return false;
    const now = Date.now();
    if (!force && now - lastProgressSentAt < 10000) return false;
    lastProgressSentAt = now;
    const completed = ended || (duration > 0 && current / duration >= 0.92);
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
      return completed;
    } catch (_error) {
      // Progress save should never interrupt playback.
      lastProgressSentAt = 0;
      return false;
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
    const lines = cleanCaptionText(value)
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
    const season = optionalNonNegativeNumber(meta.season);
    const episode = optionalNonNegativeNumber(packEpisode?.value) ?? meta.episode ?? null;
    launchTitle.textContent = "Play selected episode from pack";
    if (season === null) {
      launch.disabled = true;
      setStatus("This season pack has no season metadata yet.");
      setPackStatus("Re-add this pack from the season picker so Dragon can bind it to the right season.");
      return true;
    }
    if (episode === null) {
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
    // An embed provider has no season metadata of its own. Retain the episode
    // context picked from Local while its source option is selected.
    const season = activeSelection.season ?? configuredSelectedSeason() ?? meta?.season ?? null;
    if (
      !packBrowser
      || !packEpisode
      || player.dataset.mediaType !== "tv"
      || season === null
    ) {
      hidePackBrowser();
      return;
    }
    const requestToken = ++packRequestToken;
    const tmdbId = player.dataset.tmdbId;
    const template = player.dataset.episodesTemplate;
    packBrowser.hidden = false;
    packHeading.textContent = "Episode";
    if (season === null || !tmdbId || !template) {
      packEpisode.disabled = true;
      setPackStatus("This pack cannot be mapped to TMDB episodes yet.");
      launch.disabled = Boolean(meta?.seasonPack);
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
        || currentMeta?.sourceId !== meta?.sourceId
        || (currentMeta?.season !== null && Number(currentMeta.season) !== season)
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
      const preferredEpisode = queryEpisode
        || Number(activeSelection.episode || 0)
        || routeEpisode
        || meta?.episode
        || null;
      if (preferredEpisode) packEpisode.value = String(preferredEpisode);
      syncPlayerTitle();
      syncEpisodeUrl({ replace: true });
      void loadSavedProgress();
      if (meta?.seasonPack) syncPackLaunchState();
      else launch.disabled = false;
    } catch (error) {
      packEpisode.disabled = true;
      setPackStatus(String(error?.message || "Episode lookup is unavailable."));
      launch.disabled = Boolean(meta?.seasonPack);
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
    const moment = effectiveCurrentTime();
    const active = (entry.transformedCues || []).filter((cue) => cue.startTime <= moment && cue.endTime >= moment);
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
        entry.subtitleId = await subtitleContentFingerprint(body, entry.item.track_url);
        loadSubtitleSync(entry);
        entry.ready = true;
        if (selectedSubtitleIndex === subtitleEntries.indexOf(entry)) {
          renderActiveCaption();
          refreshSubtitleSync();
          setSubtitleStatus(`${entry.label} is selected. Use Sync to repair timing or Appearance to change its look.`);
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
      refreshSubtitleSync();
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
    refreshSubtitleSync();
    setSubtitleStatus(`${entry.label} is selected. Use Sync to repair timing or Appearance to change its look.`);
  };

  const selectFirstUsableSubtitle = () => {
    const preferredLanguage = String(player.dataset.defaultSubtitleLanguage || "").trim().toLowerCase();
    const findUsableIndex = (predicate) => subtitleEntries.findIndex((entry) => (
      predicate(entry) && !entry.error
    ));
    const readyIndex = findUsableIndex((entry) => (
      entry.ready
      && (!preferredLanguage || String(entry.item?.language || "").toLowerCase() === preferredLanguage)
    ));
    if (readyIndex >= 0) {
      setActiveSubtitleIndex(readyIndex);
      return;
    }
    const pendingIndex = findUsableIndex((entry) => (
      !entry.ready
      && (!preferredLanguage || String(entry.item?.language || "").toLowerCase() === preferredLanguage)
    ));
    if (pendingIndex >= 0) {
      setActiveSubtitleIndex(pendingIndex);
      return;
    }
    if (preferredLanguage) {
      const fallbackReadyIndex = findUsableIndex((entry) => entry.ready);
      if (fallbackReadyIndex >= 0) {
        setActiveSubtitleIndex(fallbackReadyIndex);
        return;
      }
      const fallbackPendingIndex = findUsableIndex((entry) => !entry.ready);
      if (fallbackPendingIndex >= 0) {
        setActiveSubtitleIndex(fallbackPendingIndex);
        return;
      }
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
    refreshSubtitleSync();
    renderActiveCaption();
  };

  const mountSubtitleTracks = (items) => {
    clearSubtitleTracks();
    if (!items.length) {
      setSubtitleStatus("No Arabic or English subtitles were found.");
      return;
    }
    subtitleEntries = items.map((item, index) => {
      const trackLabel = item.label || `Track ${index + 1}`;
      const label = `${item.language_name || "Subtitle"} · ${trackLabel}${item.hearing_impaired ? " · HI" : ""}`;
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
      target.season !== null && target.episode !== null
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
    if (embedCinemaMode || document.fullscreenElement === player) {
      void document.exitFullscreen?.();
      embedCinemaUsesBrowserFullscreen = false;
      setEmbedCinemaMode(false);
    }
    clearVideoPaintCheck();
    clearNextEpisode();
    setWatchMode(false);
    activeKind = "";
    sourceUrl = "";
    sourceSandbox = "";
    resolvedSourceId = "";
    frame.removeAttribute("sandbox");
    frame.src = "about:blank";
    frame.hidden = true;
    if (externalToolbar) externalToolbar.hidden = true;
    if (mediaShell) mediaShell.hidden = true;
    if (captionLayer) captionLayer.hidden = true;
    video.hidden = true;
    video.controls = false;
    launch.hidden = false;
    launch.disabled = false;
    if (recovery) recovery.hidden = true;
    if (launchHint) launchHint.textContent = "Loads only after you press play.";
    controls.hidden = true;
    if (retry) retry.hidden = true;
    if (fallback) fallback.hidden = true;
    open.hidden = true;
    stop.hidden = true;
    setSubtitlePanelOpen(false);
  };

  const syncSourceUi = () => {
    const kind = selectedKind();
    const meta = selectedSourceMeta();
    syncSourceFacts();
    badge.textContent = kind === "embed" ? selectedProviderLabel() : "Local";
    launchTitle.textContent = kind === "embed" ? `Play with ${selectedProviderLabel()}` : "Start local player";
    if (launchHint) launchHint.textContent = kind === "embed"
      ? "Loads only after you press play."
      : "The magnet starts only after you press play.";
    if (startOver) startOver.hidden = kind !== "local" || !savedProgress?.seconds;
    if (kind === "embed") {
      void loadPackEpisodes();
      launch.disabled = false;
      frame.title = `${selectedProviderLabel()} player`;
      if (externalToolbar) {
        externalToolbar.setAttribute("aria-label", `${selectedProviderLabel()} player options`);
      }
      if (externalCaption) {
        externalCaption.textContent = `${selectedProviderLabel()} uses its own controls. Dragon timeline works with Local.`;
      }
      setStatus("Ready. No external connection has been made.");
    } else if (meta?.seasonPack) {
      void loadPackEpisodes();
    } else {
      if (player.dataset.mediaType === "tv") void loadPackEpisodes();
      else hidePackBrowser();
      launch.disabled = false;
      if (savedProgress?.seconds) {
        launchTitle.textContent = `Resume from ${formatTime(savedProgress.seconds)}`;
        setStatus(`Ready to resume local playback from ${formatTime(savedProgress.seconds)}. The magnet starts only after you press play.`);
      } else {
        setStatus("Ready. The magnet will start only after you press play.");
      }
    }
    if (subtitleStatus) {
      if (kind === "embed") {
        clearSubtitleTracks();
        setSubtitleStatus("");
      } else if (subtitleOptions === null) {
        setSubtitleStatus("Arabic will be selected first. Open Sub after Local starts to tune font, color, blur, or timing.");
      }
    }
  };

  const showError = (message, { keepViewport = false } = {}) => {
    clearPoll();
    clearVideoPaintCheck();
    setWatchMode(false);
    setPlayerState("failed", message);
    launch.disabled = false;
    launch.hidden = true;
    launchTitle.textContent = activeKind === "embed" ? `Try ${selectedProviderLabel()} again` : "Retry local player";
    if (launchHint) launchHint.textContent = "Choose another release below if this source is no longer available.";
    frame.hidden = true;
    if (externalToolbar) externalToolbar.hidden = true;
    if (mediaShell) mediaShell.hidden = !keepViewport;
    video.hidden = !keepViewport;
    controls.hidden = false;
    if (recovery) recovery.hidden = false;
    if (recoveryMessage) recoveryMessage.textContent = message;
    if (inlineFallback) inlineFallback.hidden = activeKind !== "local" || !fallbackEmbedOption();
    if (retry) retry.hidden = false;
    if (fallback) fallback.hidden = activeKind !== "local" || !fallbackEmbedOption();
    if (stop) stop.hidden = activeKind !== "local" || !localSession;
    setStatus(message);
  };

  const classifyLocalFailure = (message) => {
    const normalized = String(message || "").toLowerCase();
    if (normalized.includes("peer") || normalized.includes("torrent stalled")) {
      return "The torrent has no usable peers right now. Retry, or choose another release.";
    }
    if (normalized.includes("decode") || normalized.includes("codec")) {
      return "This release cannot play in the browser. Dragon will try local transcoding once; otherwise choose another release.";
    }
    if (normalized.includes("transcod") || normalized.includes("ffmpeg")) {
      return "Local transcoding could not start. Choose another release or switch source.";
    }
    if (normalized.includes("subtitle")) {
      return "Playback is still available, but this subtitle track failed. Pick another subtitle or turn subtitles off.";
    }
    return "Local playback could not start. Retry, choose another release, or switch source.";
  };

  const fallbackEmbedOption = () => Array.from(source.querySelectorAll('option[data-kind="embed"]'))
    .find((option) => option.value !== source.value) || null;
  const switchToFallbackEmbed = async () => {
    const embed = fallbackEmbedOption();
    if (!embed) return;
    await stopLocal({ silent: true, persistProgress: false });
    source.value = embed.value;
    source.dispatchEvent(new Event("change", { bubbles: true }));
    launch.focus();
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
    video.controls = false;
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
  const scheduleVideoPaintCheck = () => {
    // A zero-sized video frame is not a playback failure: hardware decoding,
    // remote streams, and browser privacy constraints can all report it while
    // the video is visibly playing. Real failures still arrive through the
    // native `error` and `stalled` events below.
    clearVideoPaintCheck();
  };

  const loadEmbed = () => {
    setWatchMode(true);
    frame.hidden = false;
    if (externalToolbar) externalToolbar.hidden = false;
    if (mediaShell) mediaShell.hidden = true;
    if (sourceSandbox) frame.setAttribute("sandbox", sourceSandbox);
    else frame.removeAttribute("sandbox");
    frame.src = sourceUrl;
    launch.hidden = true;
    controls.hidden = false;
    if (retry) retry.hidden = true;
    if (fallback) fallback.hidden = true;
    reload.hidden = false;
    open.hidden = false;
    open.href = sourceUrl;
    if (externalOpen) externalOpen.href = sourceUrl;
    stop.hidden = true;
    setStatus(`${selectedProviderLabel()} is loading…`);
  };

  const rememberSelectedEmbedSource = () => {
    const template = String(player.dataset.sourceSelectedTemplate || "");
    if (!template || !resolvedSourceId) return;
    const endpoint = template.replace("source-id", encodeURIComponent(resolvedSourceId));
    void fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "X-CSRFToken": csrf },
    });
  };

  const renderLocalStatus = (session) => {
    const details = [];
    const sourceMeta = selectedSourceMeta();
    [sourceMeta?.quality, sourceMeta?.codec, sourceMeta?.playback, sourceMeta?.size].filter(Boolean).forEach((item) => details.push(item));
    if (sourceMeta?.hdr) details.push("HDR");
    if (session.stream_kind) details.push(session.stream_kind === "transcode" ? "local transcode" : "direct stream");
    if (session.file_name) details.push(session.file_name);
    if (session.peers) details.push(`${session.peers} peer${session.peers === 1 ? "" : "s"}`);
    if (session.download_speed) details.push(formatSpeed(session.download_speed));
    if (session.downloaded_bytes) details.push(`${formatBytes(session.downloaded_bytes)} cached`);
    if (session.cache_hit) details.push("cache hit");
    const progress = session.buffer_percent ? ` ${session.buffer_percent}% startup buffer.` : "";
    setStatus(`${session.message || "Preparing local stream…"}${progress}${details.length ? ` · ${details.join(" · ")}` : ""}`);
    if (!video.hasAttribute("src")) {
      const runtimeState = session.state === "metadata" ? "preparing" : session.state;
      setPlayerState(runtimeState === "ready" ? "buffering" : (runtimeState || "preparing"));
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
      const message = classifyLocalFailure(String(error?.message || "Local player unavailable"));
      await stopLocal({ silent: true, persistProgress: false });
      showError(message);
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
    video.controls = false;
    controls.hidden = false;
    if (retry) retry.hidden = true;
    if (fallback) fallback.hidden = true;
    reload.hidden = true;
    open.hidden = true;
    stop.hidden = false;
    renderLocalStatus(payload.session || {});
    setPlayerState("preparing", "Reading torrent metadata…");
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

  source.addEventListener("change", () => {
    const previousSelection = selectedEpisodeScope();
    // Stop the old runtime without making the next source wait on its network shutdown.
    // `stopLocal` clears its local state synchronously before its cleanup request awaits.
    void stopLocal({ silent: true, persistProgress: false });
    subtitleOptions = null;
    subtitleOptionsKey = "";
    savedProgress = null;
    progressLoaded = false;
    lastProgressSentAt = 0;
    activeSelection.season = previousSelection.season
      ?? configuredSelectedSeason()
      ?? selectedSourceMeta()?.season
      ?? null;
    activeSelection.episode = previousSelection.episode
      ?? configuredSelectedEpisode()
      ?? selectedSourceMeta()?.episode
      ?? null;
    activeSelection.runtimeSeconds = configuredRuntimeSeconds();
    activeSelection.episodeTitle = configuredSelectedEpisodeTitle();
    resetViewport();
    syncEpisodeUrl();
    syncSourceUi();
    window.dispatchEvent(new CustomEvent("dragon:movies:toast", {
      detail: { message: `${selectedProviderLabel()} selected. Playback starts only when you press play.` },
    }));
    void loadSavedProgress();
  });
  packEpisode?.addEventListener("change", async () => {
    const localWasActive = activeKind === "local" && (Boolean(localSession) || !video.hidden || video.hasAttribute("src"));
    if (localWasActive) {
      await stopLocal({ silent: true });
      resetViewport();
    } else if (activeKind === "embed" && !frame.hidden) {
      resetViewport();
    }
    subtitleOptions = null;
    subtitleOptionsKey = "";
    savedProgress = null;
    progressLoaded = false;
    lastProgressSentAt = 0;
    activeSelection.season = configuredSelectedSeason() ?? selectedSourceMeta()?.season ?? null;
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
        const selection = scope.season !== null || scope.episode !== null
          ? {
            season: scope.season,
            episode: scope.episode,
            episodeTitle: activeSelection.episodeTitle || configuredSelectedEpisodeTitle() || selectedEpisodeTitle(),
          }
          : {};
        if (savedProgress?.seconds && player.dataset.automaticResume !== "false") {
          selection.resumeSeconds = savedProgress.seconds;
        }
        if (meta?.seasonPack && !selection.episode) {
          syncPackLaunchState();
          return;
        }
        setPlayerState("preparing", "Starting the local WebTorrent runtime…");
        await startLocal(selection);
        return;
      }
      setStatus(`Preparing ${selectedProviderLabel()}…`);
      const embedEndpoint = selectedEmbedEndpoint();
      if (!embedEndpoint) throw new Error("The selected embed provider is unavailable.");
      const endpoint = new URL(embedEndpoint, window.location.origin);
      const scope = selectedEpisodeScope();
      if (scope.season !== null && scope.episode !== null) {
        endpoint.searchParams.set("season", String(scope.season));
        endpoint.searchParams.set("episode", String(scope.episode));
      }
      const response = await fetch(endpoint, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || "source unavailable");
      sourceUrl = String(payload?.source?.url || "").trim();
      if (!sourceUrl) throw new Error("source unavailable");
      sourceSandbox = String(payload?.source?.sandbox || "").trim();
      resolvedSourceId = String(payload?.source?.source_id || "").trim();
      loadEmbed();
    } catch (error) {
      showError(String(error?.message || "Playback is unavailable for this movie."));
    }
  });

  frame.addEventListener("load", () => {
    if (activeKind === "embed" && frame.src !== "about:blank") {
      setStatus(`${selectedProviderLabel()} loaded. Playback controls are inside the player.`);
      rememberSelectedEmbedSource();
      void reportWatchStarted();
    }
  });

  reload.addEventListener("click", () => {
    if (!sourceUrl) return;
    frame.src = "about:blank";
    window.setTimeout(loadEmbed, 0);
  });
  externalReload?.addEventListener("click", () => reload.click());
  externalBack?.addEventListener("click", () => { void exitWatchMode(); });
  externalFullscreen?.addEventListener("click", () => {
    if (embedCinemaMode || document.fullscreenElement === player) {
      void exitEmbedCinemaMode();
    } else {
      enterEmbedCinemaMode();
    }
  });
  stop.addEventListener("click", async () => {
    await stopLocal();
    resetViewport();
    syncSourceUi();
  });
  const defaultAutoNext = player.dataset.autoNextDefault !== "false";
  try {
    const savedAutoNext = window.localStorage.getItem(autoNextPreferenceKey);
    autoNextEnabled = savedAutoNext === null ? defaultAutoNext : savedAutoNext !== "false";
  } catch (_error) {
    autoNextEnabled = defaultAutoNext;
  }
  if (autoNextToggle) {
    autoNextToggle.checked = autoNextEnabled;
    autoNextToggle.addEventListener("change", () => {
      autoNextEnabled = autoNextToggle.checked;
      saveAutoNextPreference();
      if (!autoNextEnabled) clearNextEpisode();
      window.dispatchEvent(new CustomEvent("dragon:movies:toast", {
        detail: { message: `Auto-next ${autoNextEnabled ? "enabled" : "disabled"} for this browser.` },
      }));
    });
  }
  nextPlay?.addEventListener("click", openNextEpisode);
  nextCancel?.addEventListener("click", () => {
    autoNextEnabled = false;
    saveAutoNextPreference();
    clearNextEpisode();
  });
  nextReplay?.addEventListener("click", () => {
    clearNextEpisode();
    video.currentTime = 0;
    void video.play();
  });
  startOver?.addEventListener("click", () => {
    savedProgress = null;
    syncSourceUi();
    launch.click();
  });
  const retryLocalPlayer = async () => {
    await stopLocal({ silent: true, persistProgress: false });
    resetViewport();
    syncSourceUi();
    launch.click();
  };
  retry?.addEventListener("click", retryLocalPlayer);
  inlineRetry?.addEventListener("click", retryLocalPlayer);
  fallback?.addEventListener("click", () => { void switchToFallbackEmbed(); });
  inlineFallback?.addEventListener("click", () => { void switchToFallbackEmbed(); });
  findRelease?.addEventListener("click", () => {
    const browser = document.querySelector("[data-inline-release-browser]");
    if (!browser) return;
    if (browser instanceof HTMLDetailsElement) browser.open = true;
    browser.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => (browser.querySelector("[data-release-load]") || browser.querySelector("button"))?.focus(), 260);
  });
  playerBack?.addEventListener("click", () => { void exitWatchMode(); });
  sourceReturn?.addEventListener("click", () => { void exitWatchMode(); });
  quickToggles.forEach((button) => button.addEventListener("click", togglePlayback));
  quickBack?.addEventListener("click", () => seekRelative(-10));
  quickForward?.addEventListener("click", () => seekRelative(10));
  skipIntro?.addEventListener("click", () => {
    if (playerMarkers.intro) seekRelative(playerMarkers.intro - effectiveCurrentTime());
  });
  skipRecap?.addEventListener("click", () => {
    if (playerMarkers.recap) seekRelative(playerMarkers.recap - effectiveCurrentTime());
  });
  markIntro?.addEventListener("click", () => {
    playerMarkers.intro = Math.round(effectiveCurrentTime());
    savePlayerMarkers();
    setStatus(`Intro point saved at ${formatTime(playerMarkers.intro)}.`);
  });
  markRecap?.addEventListener("click", () => {
    playerMarkers.recap = Math.round(effectiveCurrentTime());
    savePlayerMarkers();
    setStatus(`Recap point saved at ${formatTime(playerMarkers.recap)}.`);
  });
  bookmark?.addEventListener("click", () => {
    const seconds = Math.round(effectiveCurrentTime());
    const note = window.prompt("Bookmark note (optional)", "") || "";
    playerMarkers.bookmarks.push({ seconds, note: note.slice(0, 180), createdAt: Date.now() });
    savePlayerMarkers();
    setStatus(`Bookmark saved at ${formatTime(seconds)}${note ? ` · ${note}` : ""}.`);
    showControlsBriefly();
  });
  quickMute?.addEventListener("click", () => {
    video.muted = !video.muted;
    syncQuickControls();
    showControlsBriefly();
  });
  quickRate?.addEventListener("change", () => {
    const rate = Number(quickRate.value || 1);
    if (Number.isFinite(rate) && rate > 0) video.playbackRate = rate;
    showControlsBriefly();
  });
  audioSelect?.addEventListener("change", () => {
    const tracks = Array.from(video.audioTracks || []);
    const selected = Number(audioSelect.value);
    tracks.forEach((track, index) => { track.enabled = index === selected; });
    showControlsBriefly();
  });
  quickPip?.addEventListener("click", async () => {
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture?.();
      else if (document.pictureInPictureEnabled && !video.disablePictureInPicture) {
        await video.requestPictureInPicture?.();
      } else {
        setStatus("Picture-in-Picture is not available in this browser or source.");
      }
    } catch (_error) {
      setStatus("Picture-in-Picture could not start for this source.");
    }
    showControlsBriefly();
  });
  quickShortcuts?.addEventListener("click", () => {
    setStatus("Shortcuts: Space play/pause · ←/→ seek 10s · M mute · F fullscreen · C subtitles · Esc exit player.");
    showControlsBriefly();
  });
  volume?.addEventListener("input", () => {
    video.volume = Number(volume.value || 0);
    video.muted = video.volume === 0;
    syncQuickControls();
    showVolumeFeedback();
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
  subtitleSyncSearch?.addEventListener("input", () => {
    subtitleSyncSearchTerm = subtitleSyncSearch.value || "";
    refreshSubtitleSync();
  });
  subtitleSyncResults?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-player-subtitle-sync-cue]");
    const entry = activeSubtitleEntry();
    const index = Number(button?.dataset.playerSubtitleSyncCue);
    if (!entry || !Number.isInteger(index)) return;
    chooseSyncCue(entry, index);
    showControlsBriefly();
  });
  subtitleSyncNow?.addEventListener("click", () => {
    const entry = activeSubtitleEntry();
    const cue = syncCueForAction(entry);
    if (!entry || !cue) return;
    try {
      applySubtitleSyncProfile(
        entry,
        calibrateOnePoint(Math.round(cue.startTime * 1000), Math.round(effectiveCurrentTime() * 1000), entry.syncProfile),
        "Subtitle synchronized.",
      );
    } catch (error) {
      setSubtitleStatus(String(error?.message || "Subtitle sync could not be calculated."));
    }
    showControlsBriefly();
  });
  subtitleSyncAdjustments.forEach((button) => button.addEventListener("click", () => {
    const entry = activeSubtitleEntry();
    if (!entry) return;
    try {
      applySubtitleSyncProfile(entry, adjustSubtitleSync(entry.syncProfile, Number(button.dataset.playerSubtitleSyncAdjust)), "Fine tune saved.");
    } catch (error) {
      setSubtitleStatus(String(error?.message || "Subtitle timing could not be adjusted."));
    }
    showControlsBriefly();
  }));
  subtitleSyncSecond?.addEventListener("click", () => {
    const entry = activeSubtitleEntry();
    const cue = syncCueForAction(entry);
    const first = entry?.syncProfile?.anchors?.[0];
    if (!entry || !cue || !first) {
      setSubtitleStatus("First synchronize one subtitle line, then add a later second point.");
      return;
    }
    try {
      applySubtitleSyncProfile(
        entry,
        calibrateTwoPoints(first, {
          subtitle_ms: Math.round(cue.startTime * 1000),
          video_ms: Math.round(effectiveCurrentTime() * 1000),
        }, entry.syncProfile),
        "Drift correction saved.",
      );
    } catch (error) {
      setSubtitleStatus(String(error?.message || "The second sync point is not valid."));
    }
    showControlsBriefly();
  });
  subtitleSyncResync?.addEventListener("click", () => {
    const entry = activeSubtitleEntry();
    const cue = syncCueForAction(entry);
    if (!entry || !cue) return;
    try {
      applySubtitleSyncProfile(
        entry,
        resyncSubtitleFromHere(Math.round(cue.startTime * 1000), Math.round(effectiveCurrentTime() * 1000), entry.syncProfile),
        "Later subtitles resynchronized.",
      );
    } catch (error) {
      setSubtitleStatus(String(error?.message || "Subtitle segment could not be created."));
    }
    showControlsBriefly();
  });
  subtitleSyncReset?.addEventListener("click", () => {
    const entry = activeSubtitleEntry();
    if (!entry) return;
    const key = subtitleSyncKeyFor(entry);
    try {
      if (key) window.localStorage.removeItem(key);
      applySubtitleSyncProfile(entry, defaultSubtitleSyncProfile(), "Original subtitle timing restored.");
    } catch (_error) {
      setSubtitleStatus("Original subtitle timing restored for this session.");
    }
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
  document.addEventListener("fullscreenchange", () => {
    syncFullscreenChrome();
    if (document.fullscreenElement === player) {
      embedCinemaUsesBrowserFullscreen = true;
      setEmbedCinemaMode(true);
    } else if (embedCinemaUsesBrowserFullscreen) {
      embedCinemaUsesBrowserFullscreen = false;
      setEmbedCinemaMode(false);
    }
  });
  mediaShell?.addEventListener("pointerenter", showControlsBriefly);
  mediaShell?.addEventListener("pointermove", showControlsBriefly);
  mediaShell?.addEventListener("touchstart", showControlsBriefly, { passive: true });
  mediaShell?.addEventListener("focusin", showControlsBriefly);
  mediaShell?.addEventListener("wheel", (event) => {
    if (mediaShell.hidden || video.hidden) return;
    event.preventDefault();
    const currentStep = Math.round(video.volume * 20);
    const nextStep = Math.min(20, Math.max(0, currentStep + (event.deltaY < 0 ? 1 : -1)));
    video.volume = nextStep / 20;
    video.muted = video.volume === 0;
    syncQuickControls();
    showVolumeFeedback();
    showControlsBriefly();
  }, { passive: false });
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
    syncAudioTracks();
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
    if (activeKind !== "local") return;
    // `stalled` is advisory and is frequently emitted between buffered ranges.
    // Do not replace a visible, recoverable video with an error screen; a real
    // runtime failure is reported by the native `error` event or the session poll.
    setPlayerState("buffering", "The stream paused briefly while more torrent pieces arrive.");
  });
  video.addEventListener("playing", () => {
    if (activeKind === "local") {
      const selectionText = activeSelection.season !== null && activeSelection.episode !== null
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
  video.addEventListener("ended", async () => {
    if (await saveMovieProgress({ force: true, ended: true })) queueNextEpisode();
  });
  video.addEventListener("volumechange", syncQuickControls);
  video.addEventListener("error", () => {
    if (activeKind !== "local") return;
    const codecFailure = video.error?.code === window.MediaError?.MEDIA_ERR_DECODE;
    if (localSession?.streamKind !== "transcode" && switchLocalToTranscode()) return;
    const message = classifyLocalFailure(
      codecFailure ? "browser codec decode failure" : "video frames did not arrive",
    );
    showError(message, { keepViewport: true });
  });
  document.addEventListener("keydown", (event) => {
    trapSubtitlePanelFocus(event);
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
    } else if (event.key.toLowerCase() === "c") {
      event.preventDefault();
      captionToggle?.click();
    } else if (event.key === "Escape") {
      event.preventDefault();
      void exitWatchMode();
    }
  });
  loadSubtitlePreferences();
  loadPlayerMarkers();
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
