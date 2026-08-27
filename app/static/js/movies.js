const rememberMovieToast = (message, level = "success") => {
  try {
    sessionStorage.setItem("dragon:movies:next-toast", JSON.stringify({ message, level }));
  } catch (_error) {
    // Navigation must not depend on feedback storage.
  }
};

const showMovieToast = (message, level = "success") => {
  window.dispatchEvent(new CustomEvent("dragon:movies:toast", { detail: { message, level } }));
};

(() => {
  const section = document.querySelector("[data-recommendation-card]");
  const open = document.querySelector("[data-recommendation-open]");
  const next = document.querySelector("[data-recommendation-next]");
  const dismiss = document.querySelector("[data-recommendation-dismiss]");
  if (!section) return;
  open?.setAttribute("aria-expanded", "false");

  const reveal = () => {
    section.hidden = false;
    open?.setAttribute("aria-expanded", "true");
    try {
      sessionStorage.removeItem("dragon:recommendation-dismissed");
    } catch {
      // Showing the recommendation must not depend on browser storage.
    }
    section.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  open?.addEventListener("click", reveal);
  if (!dismiss) return;

  let recommendations = [];
  try {
    recommendations = JSON.parse(section.dataset.recommendationItems || "[]");
  } catch {
    return;
  }
  if (!recommendations.length) return;

  const moviesById = new Map(recommendations.map((movie) => [String(movie.id), movie]));
  const movieIds = [...moviesById.keys()];
  const poolKey = movieIds.slice().sort().join("|");
  const deckKey = `dragon:movie-recommendation-deck:${poolKey}`;
  const lastKey = `dragon:movie-recommendation-last:${poolKey}`;
  const shuffle = (ids) => {
    const shuffled = ids.slice();
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const replacement = Math.floor(Math.random() * (index + 1));
      [shuffled[index], shuffled[replacement]] = [shuffled[replacement], shuffled[index]];
    }
    return shuffled;
  };
  const readDeck = () => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(deckKey) || "[]");
      if (!Array.isArray(saved)) return [];
      return saved.filter((id, index) => movieIds.includes(String(id)) && saved.indexOf(id) === index).map(String);
    } catch {
      return [];
    }
  };
  const buildDeck = (excludedId = "") => {
    const available = movieIds.filter((id) => id !== String(excludedId));
    return shuffle(available.length ? available : movieIds);
  };

  let deck = readDeck();
  const lastId = sessionStorage.getItem(lastKey) || "";
  if (!deck.length) deck = buildDeck(lastId);
  if (deck[0] === lastId && deck.length > 1) {
    const differentIndex = deck.findIndex((id) => id !== lastId);
    [deck[0], deck[differentIndex]] = [deck[differentIndex], deck[0]];
  }
  let currentMovie = moviesById.get(deck.shift()) || recommendations[0];
  const poster = section.querySelector("[data-recommendation-poster]");
  const fallback = section.querySelector("[data-recommendation-fallback]");
  const title = section.querySelector("[data-recommendation-title]");
  const meta = section.querySelector("[data-recommendation-meta]");
  let overview = section.querySelector("[data-recommendation-overview]");
  const reason = section.querySelector("[data-recommendation-reason]");
  const controls = section.querySelector(".movie-recommendation__controls");
  const confidence = section.querySelector("[data-recommendation-confidence]");
  const details = section.querySelector("[data-recommendation-details]");
  if (!overview && reason) {
    overview = document.createElement("p");
    overview.className = "movie-recommendation__overview";
    overview.dataset.recommendationOverview = "";
    reason.before(overview);
    controls?.after(reason);
  }
  const detailUrl = (movie) => (section.dataset.recommendationDetailTemplate || "")
    .replace("999999999", encodeURIComponent(movie.id));
  const render = (movie) => {
    const url = detailUrl(movie);
    const labels = [movie.year, movie.category, ...(movie.genres || []).slice(0, 2)].filter(Boolean);
    title.textContent = movie.title;
    title.href = url;
    meta.textContent = labels.join(" · ");
    if (overview) overview.textContent = movie.overview || "No synopsis is available yet.";
    if (reason) {
      if (overview) {
        const reasonLabel = document.createElement("span");
        reasonLabel.textContent = "Why this pick";
        reason.replaceChildren(reasonLabel, movie.recommendation_reason || "A strong fit for your queue.");
      } else {
        // Keep the older server-rendered card functional during a live reload.
        reason.textContent = movie.recommendation_reason || "A strong fit for your queue.";
      }
    }
    confidence.textContent = `A quiet pick for tonight · ${movie.recommendation_explanation?.confidence || "medium"} confidence`;
    details.href = url;
    poster.parentElement.href = url;
    poster.alt = `Poster for ${movie.title}`;
    poster.hidden = !movie.poster_url;
    if (movie.poster_url) poster.src = movie.poster_url;
    fallback.hidden = Boolean(movie.poster_url);
    fallback.textContent = (movie.title || "?").slice(0, 1).toUpperCase();
  };

  const persistSelection = () => {
    sessionStorage.setItem(deckKey, JSON.stringify(deck));
    sessionStorage.setItem(lastKey, String(currentMovie.id));
  };

  render(currentMovie);
  persistSelection();

  next?.addEventListener("click", () => {
    if (!deck.length) deck = buildDeck(currentMovie.id);
    currentMovie = moviesById.get(deck.shift()) || currentMovie;
    render(currentMovie);
    persistSelection();
  });

  dismiss.addEventListener("click", () => {
    section.hidden = true;
    open?.setAttribute("aria-expanded", "false");
    sessionStorage.setItem("dragon:recommendation-dismissed", "1");
  });
  if (sessionStorage.getItem("dragon:recommendation-dismissed") === "1") section.hidden = true;
})();

/* Shared, keyboard-friendly controls for horizontal Movies rails. */
(() => {
  const rails = document.querySelectorAll("[data-movie-rail]");
  if (!rails.length) return;
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  rails.forEach((rail) => {
    if (!(rail instanceof HTMLElement) || rail.dataset.railControls === "true") return;
    rail.dataset.railControls = "true";
    const section = rail.closest("section") || rail.parentElement;
    if (!section) return;
    section.classList.add("movie-rail-section");
    const controls = document.createElement("div");
    controls.className = "movie-rail__controls";
    const previous = document.createElement("button");
    const next = document.createElement("button");
    previous.type = next.type = "button";
    previous.className = next.className = "movie-rail__control";
    previous.setAttribute("aria-label", "Scroll rail backward");
    next.setAttribute("aria-label", "Scroll rail forward");
    previous.innerHTML = "‹";
    next.innerHTML = "›";
    controls.append(previous, next);
    section.append(controls);
    const update = () => {
      const max = rail.scrollWidth - rail.clientWidth - 2;
      previous.disabled = rail.scrollLeft <= 2;
      next.disabled = max <= 0 || rail.scrollLeft >= max;
      controls.hidden = max <= 0;
    };
    const move = (direction) => {
      const amount = Math.max(rail.clientWidth * 0.78, 240) * direction;
      rail.scrollBy({ left: amount, behavior: reduceMotion ? "auto" : "smooth" });
    };
    previous.addEventListener("click", () => move(-1));
    next.addEventListener("click", () => move(1));
    rail.addEventListener("scroll", update, { passive: true });
    rail.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        move(event.key === "ArrowRight" ? 1 : -1);
      }
    });
    if (window.ResizeObserver) new ResizeObserver(update).observe(rail);
    update();
  });
})();

(() => {
  const focus = document.querySelector("[data-home-focus]");
  if (!focus) return;

  const shuffle = focus.querySelector("[data-home-focus-shuffle]");
  if (!shuffle || !focus.dataset.pickEndpoint) return;
  const title = focus.querySelector("[data-home-focus-title]");
  const meta = focus.querySelector("[data-home-focus-meta]");
  const progress = focus.querySelector("[data-home-focus-progress]");
  const label = focus.querySelector("[data-home-focus-label]");
  const primary = focus.querySelector("[data-home-focus-primary]");
  const resumeSignal = focus.querySelector(".movie-personal-hero__signal");
  const detailTemplate = focus.dataset.detailTemplate || "";
  const detailUrl = (item) => detailTemplate.replace("999999999", encodeURIComponent(item.id));

  shuffle.addEventListener("click", async () => {
    shuffle.disabled = true;
    shuffle.setAttribute("aria-busy", "true");
    const originalLabel = shuffle.textContent;
    shuffle.textContent = "Choosing…";
    try {
      const response = await fetch(focus.dataset.pickEndpoint, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.error?.message || "A new pick is unavailable.");
      const item = payload.item;
      if (!item) throw new Error("Your unwatched library is empty.");
      const url = detailUrl(item);
      title.textContent = item.title || "Untitled";
      title.href = url;
      meta.textContent = [
        item.media_type === "tv" ? "TV" : "Movie",
        item.year,
        item.runtime_minutes ? `${item.runtime_minutes} min` : "",
      ].filter(Boolean).join(" · ");
      progress.textContent = item.eligibility_reason || "From your personal unwatched library.";
      label.textContent = "From your personal library";
      primary.textContent = "Open details";
      primary.href = url;
      resumeSignal?.remove();
      showMovieToast(`${item.title || "A new title"} is ready to consider.`);
    } catch (error) {
      progress.textContent = error.message;
    } finally {
      shuffle.disabled = false;
      shuffle.removeAttribute("aria-busy");
      shuffle.textContent = originalLabel;
    }
  });
})();

(() => {
  const trigger = document.querySelector("[data-dialog-open='movie-filter-dialog']");
  const dialog = document.getElementById("movie-filter-dialog");
  if (!trigger || !dialog) return;
  trigger.setAttribute("aria-expanded", "false");
  trigger.addEventListener("click", () => trigger.setAttribute("aria-expanded", "true"));
  dialog.addEventListener("close", () => trigger.setAttribute("aria-expanded", "false"));
})();

(() => {
  const discovery = document.querySelector("[data-media-discovery]");
  if (!discovery) return;

  const form = discovery.querySelector("[data-discovery-form]");
  const queryInput = discovery.querySelector("[data-discovery-query]");
  const typeInput = discovery.querySelector("[data-discovery-type]");
  const submitButton = discovery.querySelector("[data-discovery-submit]");
  const searchStatus = discovery.querySelector("[data-discovery-status]");
  const results = discovery.querySelector("[data-discovery-results]");
  const recent = discovery.querySelector("[data-discovery-recent]");
  const recentItems = discovery.querySelector("[data-discovery-recent-items]");
  const clearRecent = discovery.querySelector("[data-discovery-recent-clear]");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const recentStorageKey = "dragon:movies:recent-searches";
  let searchController = null;
  let debounceTimer = null;
  let searchVersion = 0;

  const element = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  const api = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error?.message || "The request could not be completed.");
    return payload;
  };

  const formatBytes = (bytes) => {
    const value = Number(bytes || 0);
    if (!value) return "Size unknown";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / (1024 ** index)).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
  };

  const fillTemplate = (template, values = []) => {
    if (!template || typeof template !== "string") return null;
    return values.reduce((result, value) => {
      if (value === null || value === undefined || value === "") return result;
      return result.replace("999999999", encodeURIComponent(value));
    }, template);
  };

  const discoverUrl = (item) => {
    if (item.detail_url) return item.detail_url;
    const template = item.media_type === "tv"
      ? discovery.dataset.discoverTvTemplate
      : discovery.dataset.discoverMovieTemplate;
    return fillTemplate(template, [item.tmdb_id]) || "#";
  };

  const addToLibrary = async (item, button) => {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = item.media_type === "tv" ? "Adding S1…" : "Adding…";
    searchStatus.textContent = item.media_type === "tv"
      ? "Saving the series to Notion with season 1 ready inside your library…"
      : "Saving the movie to Notion…";
    try {
      const payload = await api(discovery.dataset.libraryEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({
          media_type: item.media_type,
          tmdb_id: item.tmdb_id,
          season: item.media_type === "tv" ? 1 : null,
        }),
      });
      rememberMovieToast(
        item.media_type === "tv"
          ? `${item.title || "Series"} was added with season 1 ready.`
          : `${item.title || "Movie"} was added to your library.`
      );
      window.location.assign(payload.detail_url);
    } catch (error) {
      searchStatus.textContent = error.message;
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = item.media_type === "tv" ? "+ Add S1 to Notion" : "+ Add to Notion";
    }
  };

  const mediaCard = (item) => {
    const card = element("article", "discovery-card");
    const detailUrl = discoverUrl(item);
    const hasDetailUrl = detailUrl !== "#";
    const poster = element("a", "discovery-card__poster");
    poster.href = detailUrl;
    if (!hasDetailUrl) {
      poster.setAttribute("aria-disabled", "true");
      poster.addEventListener("click", (event) => event.preventDefault());
    }
    if (item.poster_url) {
      const image = element("img");
      image.src = item.poster_url;
      image.alt = `Poster for ${item.title}`;
      image.loading = "lazy";
      image.width = 180;
      image.height = 270;
      poster.append(image);
    } else {
      poster.append(element("span", "media-fallback", item.title?.trim().slice(0, 1).toUpperCase() || "D"));
    }
    const body = element("div", "discovery-card__body");
    body.append(element("span", "eyebrow", `${item.media_type === "tv" ? "Series" : "Movie"} · ${item.year || "Year unknown"}`));
    const heading = element("h3");
    const titleLink = element("a", "", item.title || "Untitled");
    titleLink.href = detailUrl;
    if (!hasDetailUrl) {
      titleLink.setAttribute("aria-disabled", "true");
      titleLink.addEventListener("click", (event) => event.preventDefault());
    }
    heading.append(titleLink);
    body.append(heading);
    if (item.overview) body.append(element("p", "discovery-card__overview", item.overview));
    const actions = element("div", "discovery-card__actions");
    if (item.in_library || item.local_id) {
      const openAction = element("a", "button button--secondary", "Open from Notion");
      openAction.href = item.detail_url || `${discovery.dataset.detailsPrefix}/${encodeURIComponent(item.local_id)}`;
      actions.append(openAction);
    }
    if (!item.in_library) {
      const addAction = element(
        "button",
        "button button--secondary",
        item.media_type === "tv" ? "+ Add S1 to Notion" : "+ Add to Notion",
      );
      addAction.type = "button";
      addAction.addEventListener("click", () => addToLibrary(item, addAction));
      actions.append(addAction);
    }
    const detailAction = element(
      "a",
      "button button--primary",
      item.media_type === "tv" ? "Open series" : (!item.in_library || !item.has_playback ? "Open details" : "Open details"),
    );
    detailAction.href = item.in_library && !item.has_playback ? `${detailUrl}#release-browser` : detailUrl;
    actions.append(detailAction);
    body.append(actions);
    card.append(poster, body);
    return card;
  };

  const searchSkeleton = () => {
    const card = element("article", "movie-skeleton-card");
    card.setAttribute("aria-hidden", "true");
    card.append(element("span", "movie-skeleton-card__poster"));
    const copy = element("div", "movie-skeleton-card__copy");
    copy.append(element("span"), element("span"), element("span"));
    card.append(copy);
    return card;
  };
  const clearSearchBusy = () => {
    results.classList.remove("is-loading");
    results.removeAttribute("aria-busy");
  };
  const describeSearchFailure = (error) => {
    const message = String(error?.message || "Search could not be completed.").trim();
    const normalized = message.toLowerCase();
    if (normalized.includes("tmdb")) {
      return "TMDB search is unavailable. Your local library was not changed; try again later.";
    }
    if (normalized.includes("network") || normalized.includes("fetch") || normalized.includes("offline")) {
      return "Network search is unavailable. Check your connection, then try again.";
    }
    return `Search could not complete: ${message}`;
  };
  const renderSearchResults = (payload) => {
    clearSearchBusy();
    results.replaceChildren();
    const merged = [...(payload.library || []), ...(payload.discovery || [])];
    const seen = new Set();
    merged.forEach((item) => {
      const key = item.local_id ? `local:${item.local_id}` : `${item.media_type}:${item.tmdb_id}`;
      if (seen.has(key)) return;
      seen.add(key);
      results.append(mediaCard(item));
    });
    results.hidden = false;
    if (!seen.size) {
      const empty = element("section", "movie-discovery__empty");
      empty.append(
        element("h3", "", "No local or TMDB title matched"),
        element("p", "", "Try a different title, original title, alias, year, or TMDB ID.")
      );
      results.append(empty);
      searchStatus.textContent = "No local or TMDB title matched that search.";
      return;
    }
    searchStatus.textContent = `${seen.size} result${seen.size === 1 ? "" : "s"}. Local titles open directly; missing titles can be previewed before you add them.`;
  };

  const readRecent = () => {
    try { return JSON.parse(sessionStorage.getItem(recentStorageKey) || "[]"); } catch { return []; }
  };
  const renderRecent = () => {
    const values = readRecent();
    recent.hidden = !values.length;
    recentItems.replaceChildren();
    values.forEach((value) => {
      const button = element("button", "", value);
      button.type = "button";
      button.addEventListener("click", () => { queryInput.value = value; performSearch(); });
      recentItems.append(button);
    });
  };
  const rememberQuery = (query) => {
    const values = [query, ...readRecent().filter((value) => value !== query)].slice(0, 6);
    sessionStorage.setItem(recentStorageKey, JSON.stringify(values));
    renderRecent();
  };
  const performSearch = async () => {
    const query = queryInput.value.trim();
    if (query.length < 2) {
      searchStatus.textContent = "Enter at least two characters.";
      return;
    }
    searchController?.abort();
    searchController = new AbortController();
    const version = ++searchVersion;
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
    searchStatus.textContent = "Searching your library, then TMDB title variants…";
    results.hidden = false;
    results.replaceChildren(...Array.from({ length: 6 }, searchSkeleton));
    results.classList.add("is-loading");
    results.setAttribute("aria-busy", "true");
    const endpoint = new URL(discovery.dataset.searchEndpoint, window.location.origin);
    endpoint.searchParams.set("q", query);
    endpoint.searchParams.set("type", typeInput.value);
    try {
      const payload = await api(endpoint, { signal: searchController.signal });
      if (version !== searchVersion) return;
      renderSearchResults(payload);
      rememberQuery(query);
    } catch (error) {
      if (error.name === "AbortError" || version !== searchVersion) return;
      clearSearchBusy();
      const message = describeSearchFailure(error);
      const failure = element("section", "movie-discovery__error");
      failure.setAttribute("role", "alert");
      failure.append(
        element("h3", "", "Search unavailable"),
        element("p", "", message)
      );
      results.replaceChildren(failure);
      searchStatus.textContent = message;
    } finally {
      if (version !== searchVersion) return;
      submitButton.disabled = false;
      submitButton.removeAttribute("aria-busy");
    }
  };

  form.addEventListener("submit", (event) => { event.preventDefault(); performSearch(); });
  queryInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    if (queryInput.value.trim().length < 2) return;
    debounceTimer = window.setTimeout(performSearch, 320);
  });
  clearRecent?.addEventListener("click", () => { sessionStorage.removeItem(recentStorageKey); renderRecent(); });
  renderRecent();
})();

(() => {
  const browser = document.querySelector("[data-inline-release-browser]");
  if (!browser) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const mediaType = browser.dataset.mediaType;
  const tmdbId = browser.dataset.tmdbId;
  const seasonSelect = browser.querySelector("[data-season-select]");
  const episodeSelect = browser.querySelector("[data-episode-select]");
  const loadButton = browser.querySelector("[data-release-load]");
  const seasonPackButton = browser.querySelector("[data-season-pack-load]");
  const addButtons = [...document.querySelectorAll("[data-library-add]")];
  const addButton = browser.querySelector("[data-library-add]");
  const status = browser.querySelector("[data-release-status]");
  const releaseList = browser.querySelector("[data-release-list]");
  const diagnostics = browser.querySelector("[data-release-diagnostics]");
  const diagnosticsList = browser.querySelector("[data-release-diagnostics-list]");
  const summary = browser.querySelector("[data-release-summary]");
  const fixedSeason = Number(browser.dataset.fixedSeason || 0) || null;

  const api = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error?.message || "The request could not be completed.");
    return payload;
  };

  const formatBytes = (bytes) => {
    const value = Number(bytes || 0);
    if (!value) return "Size unknown";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / (1024 ** index)).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
  };

  const fillTemplate = (template, values = []) => {
    if (!template || typeof template !== "string") return null;
    return values.reduce((result, value) => {
      if (value === null || value === undefined || value === "") return result;
      return result.replace("999999999", encodeURIComponent(value));
    }, template);
  };

  const element = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  const renderDiagnostics = (attempts) => {
    if (!diagnostics || !diagnosticsList) return;
    diagnosticsList.replaceChildren();
    const entries = Array.isArray(attempts) ? attempts : [];
    entries.forEach((attempt) => {
      const label = String(attempt.label || attempt.kind || "Search");
      const query = String(attempt.query || "");
      const outcome = attempt.status === "skipped_unsupported"
        ? "not supported by the configured indexers"
        : `${Number(attempt.result_count || 0)} result${Number(attempt.result_count || 0) === 1 ? "" : "s"}`;
      diagnosticsList.append(element("li", "", query ? `${label}: ${query} — ${outcome}` : `${label}: ${outcome}`));
    });
    diagnostics.hidden = !entries.length;
  };

  const releaseRow = (release, season, episode, releaseMode = "episode") => {
    const row = element("article", "release-item");
    const body = element("div", "release-item__body");
    body.append(element("h3", "", release.title));
    const kindLabel = releaseMode === "season_pack" ? "Season pack" : "Episode";
    const labels = [
      kindLabel,
      release.quality_label,
      release.codec_label,
      release.playback_label,
      release.subtitle_label,
      `${release.seeders} seeders`,
      formatBytes(release.size),
      release.tracker,
    ].filter(Boolean);
    const meta = labels.join(" · ");
    body.append(element("p", "", meta));
    if (Array.isArray(release.release_tags) && release.release_tags.length) {
      const tagRow = element("div", "release-item__tags");
      release.release_tags.slice(0, 5).forEach((tag) => {
        tagRow.append(element("span", "", tag));
      });
      body.append(tagRow);
    }
    const importEpisode = releaseMode === "season_pack" ? null : episode;
    const buttonLabel = releaseMode === "season_pack"
      ? "Add full-season pack"
      : "Add to Notion & play";
    const button = element("button", "button button--primary", buttonLabel);
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.textContent = "Adding to Notion…";
      status.textContent = "Saving TMDB details and the selected magnet to Notion…";
      try {
        const payload = await api(browser.dataset.importEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({
            media_type: mediaType,
            tmdb_id: tmdbId,
            magnet_uri: release.magnet_uri,
            release_title: release.title,
            tracker: release.tracker,
            seeders: release.seeders,
            size: release.size,
            season,
            episode: importEpisode,
            release_mode: releaseMode,
          }),
        });
        const redirectUrl = String(browser.dataset.importRedirectUrl || "").trim();
        rememberMovieToast(`${release.title || "Release"} was added to your local playback library.`);
        window.location.assign(redirectUrl || `${payload.detail_url}${importEpisode ? "#movie-player" : "#release-browser"}`);
      } catch (error) {
        status.textContent = error.message;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.textContent = "Try adding again";
      }
    });
    row.append(body, button);
    return row;
  };

  const loadEpisodes = async () => {
    const season = Number(seasonSelect?.value || 0) || null;
    episodeSelect.replaceChildren(new Option("Choose an episode", ""));
    episodeSelect.disabled = true;
    releaseList.replaceChildren();
    renderDiagnostics([]);
    if (!season) {
      status.textContent = "Choose a season first.";
      return;
    }
    status.textContent = "Loading episodes from TMDB…";
    const endpoint = fillTemplate(browser.dataset.episodesTemplate, [tmdbId, season]);
    if (!endpoint) {
      status.textContent = "Episode lookup is not configured yet. Refresh the page and try again.";
      return;
    }
    try {
      const payload = await api(endpoint);
      payload.items.forEach((episode) => {
        episodeSelect.add(new Option(`E${String(episode.episode_number).padStart(2, "0")} · ${episode.name}`, episode.episode_number));
      });
      episodeSelect.disabled = !payload.items.length;
      status.textContent = payload.items.length
        ? "Choose an episode, then Dragon will try the exact episode before falling back to full-season releases."
        : "No episodes were found for this season.";
    } catch (error) {
      status.textContent = error.message;
    }
  };

  const loadReleases = async (mode = "auto") => {
    const season = mediaType === "tv" ? Number(seasonSelect.value || 0) || null : null;
    const episode = mediaType === "tv" ? Number(episodeSelect.value || 0) || null : null;
    if (mediaType === "tv" && !season) {
      status.textContent = "Choose a season first.";
      return;
    }
    if (mediaType === "tv" && mode !== "season_pack" && !episode) {
      status.textContent = "Choose a season and episode first.";
      return;
    }
    releaseList.replaceChildren();
    const searchButton = mode === "season_pack" ? seasonPackButton : loadButton;
    if (searchButton) {
      searchButton.disabled = true;
      searchButton.setAttribute("aria-busy", "true");
    }
    status.textContent = mode === "season_pack"
      ? "Searching Jackett for full-season packs, strongest seed/size matches first…"
      : mediaType === "tv"
      ? "Searching Jackett for the exact episode first, then smart fallbacks…"
      : "Searching Jackett across your configured indexers…";
    const endpoint = new URL(browser.dataset.releasesEndpoint, window.location.origin);
    endpoint.searchParams.set("type", mediaType);
    endpoint.searchParams.set("tmdb_id", tmdbId);
    endpoint.searchParams.set("mode", mode);
    if (season) endpoint.searchParams.set("season", season);
    if (episode && mode !== "season_pack") endpoint.searchParams.set("episode", episode);
    try {
      const payload = await api(endpoint);
      renderDiagnostics(payload.queries_tried);
      payload.items.forEach((release) => {
        const releaseMode = mode === "season_pack" || release.match_kind === "season_pack"
          ? "season_pack"
          : "episode";
        releaseList.append(releaseRow(release, season, episode, releaseMode));
      });
      if (!payload.items.length) {
        status.textContent = mode === "season_pack"
          ? "No useful season pack was found with enough seeders."
          : "No exact episode or useful season-pack release was found with enough seeders.";
      } else if (mode === "season_pack") {
        status.textContent = `${payload.items.length} season pack${payload.items.length === 1 ? "" : "s"} found. Pick one; Dragon will select the chosen episode from inside the pack when playback starts.`;
      } else if (payload.items[0].match_kind === "season_pack") {
        status.textContent = `${payload.items.length} season-level fallback release${payload.items.length === 1 ? "" : "s"} found because no strong exact episode match was available.`;
      } else {
        status.textContent = `${payload.items.length} seeded release${payload.items.length === 1 ? "" : "s"} found, strongest matches first.`;
      }
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (searchButton) {
        searchButton.disabled = false;
        searchButton.removeAttribute("aria-busy");
      }
    }
  };

  const addToLibrary = async () => {
    addButtons.forEach((button) => {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    });
    status.textContent = mediaType === "tv"
      ? "Saving the series to Notion with season 1 so it appears in your library…"
      : "Saving the movie to Notion…";
    try {
      const payload = await api(browser.dataset.libraryEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({
          media_type: mediaType,
          tmdb_id: tmdbId,
          season: mediaType === "tv" ? 1 : null,
        }),
      });
      window.location.assign(payload.detail_url);
    } catch (error) {
      status.textContent = error.message;
      addButtons.forEach((button) => {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      });
    }
  };

  if (mediaType === "tv" && seasonSelect) {
    if (fixedSeason) {
      seasonSelect.value = String(fixedSeason);
      seasonSelect.disabled = true;
      status.textContent = `Loading episodes for season ${fixedSeason} from TMDB…`;
      void loadEpisodes();
      episodeSelect.addEventListener("change", () => {
        if (!episodeSelect.value) {
          releaseList.replaceChildren();
          return;
        }
        loadReleases();
      });
      seasonPackButton?.addEventListener("click", () => loadReleases("season_pack"));
      return;
    }
    status.textContent = "Loading seasons from TMDB…";
    const endpoint = fillTemplate(browser.dataset.seasonsTemplate, [tmdbId]);
    if (!endpoint) {
      status.textContent = "Season lookup is not configured yet. Refresh the page and try again.";
      return;
    }
    api(endpoint)
      .then((payload) => {
        payload.items.forEach((season) => {
          seasonSelect.add(new Option(`${season.name} · ${season.episode_count} episodes`, season.season_number));
        });
        status.textContent = payload.items.length
          ? "Choose a season and episode. Dragon will open the best release path from there."
          : "No regular seasons were found.";
      })
      .catch((error) => {
        status.textContent = error.message;
      });
    seasonSelect.addEventListener("change", loadEpisodes);
    episodeSelect.addEventListener("change", () => {
      if (!episodeSelect.value) {
        releaseList.replaceChildren();
        return;
      }
      loadReleases();
    });
  } else {
    summary.textContent = "Open a release search only when you want to attach a playable magnet.";
    status.textContent = addButton
      ? "Use + to save the movie to Notion now, or search a release when you are ready to play."
      : "Search a release when you are ready to attach a playable magnet.";
  }
  loadButton?.addEventListener("click", () => {
    if (mediaType === "movie") loadReleases();
  });
  seasonPackButton?.addEventListener("click", () => loadReleases("season_pack"));
  addButtons.forEach((button) => button.addEventListener("click", addToLibrary));
  document.querySelectorAll("[data-release-browser-open]").forEach((button) => {
    button.addEventListener("click", () => {
      browser.open = true;
      browser.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  });
})();

(() => {
  const preview = document.querySelector("[data-discover-player]");
  if (!preview) return;

  const source = preview.querySelector("[data-preview-source]");
  const season = preview.querySelector("[data-preview-season]");
  const episode = preview.querySelector("[data-preview-episode]");
  const launch = preview.querySelector("[data-preview-launch]");
  const status = preview.querySelector("[data-preview-status]");
  const viewport = preview.querySelector("[data-preview-viewport]");
  const frame = preview.querySelector("[data-preview-frame]");
  const mediaType = preview.dataset.mediaType;
  const tmdbId = preview.dataset.tmdbId;
  document.querySelectorAll("[data-preview-open]").forEach((button) => {
    button.addEventListener("click", () => preview.scrollIntoView({ block: "start", behavior: "smooth" }));
  });

  const api = async (url) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error?.message || "Preview playback is unavailable.");
    return payload;
  };

  const fillTemplate = (template, values = []) => {
    if (!template || typeof template !== "string") return null;
    return values.reduce((result, value) => {
      if (value === null || value === undefined || value === "") return result;
      return result.replace("999999999", encodeURIComponent(value));
    }, template);
  };

  const clearPreview = () => {
    frame.src = "about:blank";
    frame.hidden = true;
    viewport.hidden = true;
  };

  const syncLaunchState = () => {
    const ready = mediaType !== "tv" || (season?.value && episode?.value);
    launch.disabled = !ready;
    launch.textContent = ready ? "Play preview" : "Choose an episode";
  };

  const loadEpisodes = async () => {
    clearPreview();
    episode.replaceChildren(new Option("Choose an episode", ""));
    episode.disabled = true;
    syncLaunchState();
    if (!season.value) {
      status.textContent = "Choose a season to load preview episodes from TMDB.";
      return;
    }
    status.textContent = "Loading episodes from TMDB…";
    const endpoint = fillTemplate(preview.dataset.episodesTemplate, [tmdbId, season.value]);
    if (!endpoint) {
      status.textContent = "Episode preview is not configured yet.";
      return;
    }
    try {
      const payload = await api(endpoint);
      (payload.items || []).forEach((item) => {
        episode.add(new Option(`E${String(item.episode_number).padStart(2, "0")} · ${item.name}`, item.episode_number));
      });
      episode.disabled = !(payload.items || []).length;
      status.textContent = payload.items?.length
        ? "Choose an episode, then play a preview. Nothing is added to your library."
        : "No episodes were found for this season.";
    } catch (error) {
      status.textContent = error.message;
    }
    syncLaunchState();
  };

  source.addEventListener("change", () => {
    clearPreview();
    status.textContent = "Source changed. Press Play preview when you are ready.";
    syncLaunchState();
  });
  season?.addEventListener("change", loadEpisodes);
  episode?.addEventListener("change", () => {
    clearPreview();
    syncLaunchState();
  });
  launch.addEventListener("click", async () => {
    const provider = source.value;
    if (!provider || (mediaType === "tv" && (!season.value || !episode.value))) return;
    launch.disabled = true;
    status.textContent = `Preparing ${source.selectedOptions[0]?.textContent || "preview"}…`;
    try {
      const endpoint = (preview.dataset.sourceTemplate || "").replace("provider-key", encodeURIComponent(provider));
      const url = new URL(endpoint, window.location.origin);
      if (mediaType === "tv") {
        url.searchParams.set("season", season.value);
        url.searchParams.set("episode", episode.value);
      }
      const payload = await api(url);
      const sourceUrl = String(payload?.source?.url || "").trim();
      if (!sourceUrl) throw new Error("The selected preview provider returned no player.");
      frame.src = sourceUrl;
      frame.hidden = false;
      viewport.hidden = false;
      status.textContent = `${payload.source.label || "Preview player"} is loading…`;
      syncLaunchState();
    } catch (error) {
      clearPreview();
      status.textContent = error.message;
      syncLaunchState();
    }
  });
  frame.addEventListener("load", () => {
    if (!frame.hidden && frame.src !== "about:blank") {
      status.textContent = "Preview loaded. Nothing was added to your library.";
    }
  });
  syncLaunchState();
})();
