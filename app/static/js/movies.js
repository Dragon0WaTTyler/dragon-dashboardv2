(() => {
  const section = document.querySelector("[data-movie-recommendation]");
  const loadButton = document.querySelector("[data-recommendation-load]");
  if (!section || !loadButton) return;

  const card = section.querySelector("[data-recommendation-card]");
  const status = section.querySelector("[data-recommendation-status]");
  const nextButton = section.querySelector("[data-recommendation-next]");
  const title = section.querySelector("[data-recommendation-title]");
  const poster = section.querySelector("[data-recommendation-poster]");
  const posterFrame = poster.closest("[data-media-frame]");
  const fallback = section.querySelector("[data-recommendation-fallback]");
  const meta = section.querySelector("[data-recommendation-meta]");
  const reason = section.querySelector("[data-recommendation-reason]");
  const detail = section.querySelector("[data-recommendation-detail]");
  const confidence = section.querySelector("[data-recommendation-confidence]");
  const detailsLinks = [...section.querySelectorAll("[data-recommendation-details]")];
  let queue = [];
  let current = null;

  function randomValue() {
    if (window.crypto?.getRandomValues) {
      const value = new Uint32Array(1);
      window.crypto.getRandomValues(value);
      return value[0] / 4294967296;
    }
    return Math.random();
  }

  function shuffle(items) {
    const shuffled = [...items];
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const target = Math.floor(randomValue() * (index + 1));
      [shuffled[index], shuffled[target]] = [shuffled[target], shuffled[index]];
    }
    return shuffled;
  }

  function buildQueue(items) {
    return [0, 1, 2].flatMap((tier) => shuffle(items.filter((item) => item.tier === tier)));
  }

  function render(movie) {
    current = movie;
    const detailUrl = `${section.dataset.detailsPrefix}/${encodeURIComponent(movie.id)}`;
    detailsLinks.forEach((link) => link.setAttribute("href", detailUrl));
    title.textContent = movie.title;
    fallback.textContent = movie.title.trim().slice(0, 1).toUpperCase() || "D";

    posterFrame.classList.remove("image-failed");
    if (movie.poster_url) {
      poster.src = movie.poster_url;
      poster.alt = `Poster for ${movie.title}`;
      poster.hidden = false;
    } else {
      poster.removeAttribute("src");
      poster.alt = "";
      poster.hidden = true;
    }

    const metadata = [movie.year || "Year unknown", movie.category];
    if (movie.genres?.length) metadata.push(movie.genres.slice(0, 2).join(" · "));
    meta.textContent = metadata.filter(Boolean).join(" · ");
    reason.textContent = movie.recommendation_reason;
    detail.textContent = movie.recommendation_explanation.detail || "";
    detail.hidden = !detail.textContent;
    confidence.textContent = `${movie.recommendation_explanation.confidence} confidence`;
    card.hidden = false;
    status.hidden = true;
    section.classList.remove("is-loading");
  }

  function showNext() {
    if (!queue.length) {
      status.textContent = "You have seen every eligible pick in this session. Start again?";
      status.hidden = false;
      nextButton.textContent = "Start again";
      return;
    }
    const next = queue.shift();
    if (current && next.id === current.id && queue.length) queue.push(next);
    else render(next);
    nextButton.textContent = "Try another";
  }

  async function loadRecommendations() {
    section.hidden = false;
    section.classList.add("is-loading");
    status.hidden = false;
    status.textContent = "Finding a strong match from your watch-next library…";
    card.hidden = true;
    loadButton.disabled = true;
    loadButton.setAttribute("aria-busy", "true");
    loadButton.setAttribute("aria-expanded", "true");

    const endpoint = new URL(section.dataset.endpoint, window.location.origin);
    if (section.dataset.category) endpoint.searchParams.set("category", section.dataset.category);
    if (section.dataset.source) endpoint.searchParams.set("source", section.dataset.source);

    try {
      const response = await fetch(endpoint, {headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error(`Recommendation request failed: ${response.status}`);
      const payload = await response.json();
      queue = buildQueue(payload.item.items || []);
      current = null;
      if (!queue.length) {
        status.textContent = "No eligible unwatched titles match these filters yet.";
        section.classList.remove("is-loading");
        return;
      }
      showNext();
      loadButton.textContent = "Pick ready";
    } catch (error) {
      status.textContent = "The local recommendation could not be loaded. Try again.";
      section.classList.remove("is-loading");
      loadButton.textContent = "Try recommendation again";
      console.error(error);
    } finally {
      loadButton.disabled = false;
      loadButton.removeAttribute("aria-busy");
    }
  }

  loadButton.addEventListener("click", loadRecommendations);
  nextButton.addEventListener("click", () => {
    if (!queue.length && current) {
      loadRecommendations();
      return;
    }
    showNext();
  });
})();

(() => {
  const discovery = document.querySelector("[data-media-discovery]");
  const dialog = document.querySelector("[data-release-dialog]");
  if (!discovery) return;

  const form = discovery.querySelector("[data-discovery-form]");
  const queryInput = discovery.querySelector("[data-discovery-query]");
  const typeInput = discovery.querySelector("[data-discovery-type]");
  const submitButton = discovery.querySelector("[data-discovery-submit]");
  const searchStatus = discovery.querySelector("[data-discovery-status]");
  const results = discovery.querySelector("[data-discovery-results]");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const openButton = document.querySelector("[data-discovery-open]");

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

  const discoverUrl = (item) => {
    if (item.detail_url) return item.detail_url;
    const template = item.media_type === "tv"
      ? discovery.dataset.discoverTvTemplate
      : discovery.dataset.discoverMovieTemplate;
    return template.replace("999999999", encodeURIComponent(item.tmdb_id));
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
    const poster = element("a", "discovery-card__poster");
    poster.href = detailUrl;
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

  const renderSearchResults = (payload) => {
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
      searchStatus.textContent = "No TMDB results matched that search.";
      results.hidden = true;
      return;
    }
    searchStatus.textContent = `${seen.size} result${seen.size === 1 ? "" : "s"}. Notion titles open directly; missing titles can be added through Jackett.`;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = queryInput.value.trim();
    if (query.length < 2) {
      queryInput.focus();
      searchStatus.textContent = "Enter at least two characters.";
      return;
    }
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
    searchStatus.textContent = "Checking Notion, then TMDB…";
    results.hidden = true;
    const endpoint = new URL(discovery.dataset.searchEndpoint, window.location.origin);
    endpoint.searchParams.set("q", query);
    endpoint.searchParams.set("type", typeInput.value);
    try {
      renderSearchResults(await api(endpoint));
    } catch (error) {
      searchStatus.textContent = error.message;
    } finally {
      submitButton.disabled = false;
      submitButton.removeAttribute("aria-busy");
    }
  });
  openButton?.addEventListener("click", () => {
    discovery.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => queryInput.focus(), 200);
  });
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
  const addButton = browser.querySelector("[data-library-add]");
  const status = browser.querySelector("[data-release-status]");
  const releaseList = browser.querySelector("[data-release-list]");
  const summary = browser.querySelector("[data-release-summary]");

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

  const element = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  const releaseRow = (release, season, episode) => {
    const row = element("article", "release-item");
    const body = element("div", "release-item__body");
    body.append(element("h3", "", release.title));
    const meta = `${release.seeders} seeders · ${formatBytes(release.size)} · ${release.tracker}`;
    body.append(element("p", "", meta));
    const button = element("button", "button button--primary", "Add to Notion & play");
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
            episode,
          }),
        });
        window.location.assign(`${payload.detail_url}#movie-player`);
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
    if (!season) {
      status.textContent = "Choose a season first.";
      return;
    }
    status.textContent = "Loading episodes from TMDB…";
    const endpoint = browser.dataset.episodesTemplate
      .replace("999999999", encodeURIComponent(tmdbId))
      .replace("999999999", encodeURIComponent(season));
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

  const loadReleases = async () => {
    const season = mediaType === "tv" ? Number(seasonSelect.value || 0) || null : null;
    const episode = mediaType === "tv" ? Number(episodeSelect.value || 0) || null : null;
    if (mediaType === "tv" && (!season || !episode)) {
      status.textContent = "Choose a season and episode first.";
      return;
    }
    releaseList.replaceChildren();
    if (loadButton) {
      loadButton.disabled = true;
      loadButton.setAttribute("aria-busy", "true");
    }
    status.textContent = mediaType === "tv"
      ? "Searching Jackett for the exact episode first, then smart fallbacks…"
      : "Searching Jackett across your configured indexers…";
    const endpoint = new URL(browser.dataset.releasesEndpoint, window.location.origin);
    endpoint.searchParams.set("type", mediaType);
    endpoint.searchParams.set("tmdb_id", tmdbId);
    if (season) endpoint.searchParams.set("season", season);
    if (episode) endpoint.searchParams.set("episode", episode);
    try {
      const payload = await api(endpoint);
      payload.items.forEach((release) => releaseList.append(releaseRow(release, season, episode)));
      if (!payload.items.length) {
        status.textContent = "No exact episode or useful season-pack release was found with enough seeders.";
      } else if (payload.items[0].match_kind === "season_pack") {
        status.textContent = `${payload.items.length} season-level fallback release${payload.items.length === 1 ? "" : "s"} found because no strong exact episode match was available.`;
      } else {
        status.textContent = `${payload.items.length} seeded release${payload.items.length === 1 ? "" : "s"} found, strongest matches first.`;
      }
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (loadButton) {
        loadButton.disabled = false;
        loadButton.removeAttribute("aria-busy");
      }
    }
  };

  const addToLibrary = async () => {
    addButton.disabled = true;
    addButton.setAttribute("aria-busy", "true");
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
      addButton.disabled = false;
      addButton.removeAttribute("aria-busy");
    }
  };

  if (mediaType === "tv" && seasonSelect) {
    status.textContent = "Loading seasons from TMDB…";
    const endpoint = browser.dataset.seasonsTemplate.replace("999999999", encodeURIComponent(tmdbId));
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
  addButton?.addEventListener("click", addToLibrary);
})();
