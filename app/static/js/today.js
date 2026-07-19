(() => {
  const root = document.querySelector("[data-today-live]");
  if (!root) return;

  const movieFeature = root.querySelector("[data-live-movie]");
  const youtubeGrid = root.querySelector("[data-live-youtube]");
  const pockettubeGrid = root.querySelector("[data-live-pockettube]");
  const readingGrid = root.querySelector("[data-live-reading]");
  const movieCountdown = root.querySelector("[data-movie-countdown]");
  const youtubeCountdown = root.querySelector("[data-youtube-countdown]");
  const pockettubeCountdown = root.querySelector("[data-pockettube-countdown]");
  const readingCountdown = root.querySelector("[data-reading-countdown]");
  const announcer = root.querySelector("[data-live-announcer]");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let movieNextAt = Date.parse(root.dataset.movieNextAt);
  let youtubeNextAt = Date.parse(root.dataset.youtubeNextAt);
  let readingNextAt = Date.parse(root.dataset.readingNextAt);
  let retryAt = 0;
  let inFlight = false;

  function detailUrl(prefix, id) {
    return `${prefix}/${encodeURIComponent(id)}`;
  }

  function setMedia(frame, url, alt, fallbackText) {
    if (!frame) return;
    const fallback = frame.querySelector(".media-fallback");
    let image = frame.querySelector("img");
    frame.classList.remove("image-failed");
    if (url) {
      if (!image) {
        image = document.createElement("img");
        image.dataset.mediaImage = "";
        image.loading = "lazy";
        frame.insertBefore(image, fallback || null);
      }
      image.src = url;
      image.alt = alt;
    } else if (image) {
      image.remove();
    }
    if (fallback) fallback.textContent = fallbackText;
  }

  function animateUpdate(element) {
    if (!element || reduceMotion.matches || typeof element.animate !== "function") return;
    element.animate([{opacity: 0.45}, {opacity: 1}], {
      duration: 220,
      easing: "cubic-bezier(0.25, 1, 0.5, 1)",
    });
  }

  function renderMovie(movie) {
    if (!movieFeature || !movie) return;
    const url = detailUrl(root.dataset.moviesPrefix, movie.id);
    movieFeature.querySelectorAll("[data-live-movie-link]").forEach((link) => {
      link.href = url;
    });
    const title = movieFeature.querySelector("[data-live-movie-title]");
    const meta = movieFeature.querySelector("[data-live-movie-meta]");
    const metadata = [movie.year || "Year unknown"];
    if (movie.personal_score !== null && movie.personal_score !== undefined) {
      metadata.push(`${movie.personal_score}/5`);
    }
    title.textContent = movie.title;
    meta.textContent = metadata.join(" · ");
    setMedia(
      movieFeature.querySelector("[data-media-frame]"),
      movie.poster_url,
      `Poster for ${movie.title}`,
      movie.title.trim().slice(0, 1).toUpperCase() || "D"
    );
    animateUpdate(movieFeature);
  }

  function renderYouTube(items) {
    if (!youtubeGrid) return;
    const cards = [...youtubeGrid.querySelectorAll("[data-live-youtube-card]")];
    cards.forEach((card, index) => {
      const video = items[index];
      card.hidden = !video;
      if (!video) return;
      const url = detailUrl(root.dataset.youtubePrefix, video.id);
      card.querySelectorAll("[data-live-youtube-link]").forEach((link) => {
        link.href = url;
      });
      card.querySelector("[data-live-youtube-channel]").textContent =
        video.channel_title || "Unknown channel";
      card.querySelector("[data-live-youtube-title]").textContent = video.title;
      const duration = card.querySelector("[data-live-youtube-duration]");
      if (duration) {
        duration.textContent = video.duration_label || "";
        duration.hidden = !video.duration_label;
      }
      setMedia(
        card.querySelector("[data-media-frame]"),
        video.thumbnail_url,
        `Thumbnail for ${video.title}`,
        "▶"
      );
    });
    animateUpdate(youtubeGrid);
  }

  function renderPocketTube(items) {
    if (!pockettubeGrid) return;
    const cards = [...pockettubeGrid.querySelectorAll("[data-live-pockettube-card]")];
    cards.forEach((card, index) => {
      const video = items[index];
      card.hidden = !video;
      if (!video) return;
      const url = detailUrl(root.dataset.youtubePrefix, video.id);
      card.querySelectorAll("[data-live-pockettube-link]").forEach((link) => {
        link.href = url;
      });
      card.querySelector("[data-live-pockettube-channel]").textContent =
        video.channel_title || "Unknown channel";
      card.querySelector("[data-live-pockettube-title]").textContent = video.title;
      const duration = card.querySelector("[data-live-pockettube-duration]");
      if (duration) {
        duration.textContent = video.duration_label || "";
        duration.hidden = !video.duration_label;
      }
      setMedia(
        card.querySelector("[data-media-frame]"),
        video.thumbnail_url,
        `Thumbnail for ${video.title}`,
        "▶"
      );
    });
    animateUpdate(pockettubeGrid);
  }

  function renderReading(items) {
    if (!readingGrid) return;
    const cards = [...readingGrid.querySelectorAll("[data-live-reading-card]")];
    cards.forEach((card, index) => {
      const article = items[index];
      card.hidden = !article;
      if (!article) return;
      const url = detailUrl(root.dataset.readingPrefix, article.id);
      const openUrl = `${url}/open`;
      card.querySelectorAll("[data-live-reading-link]").forEach((link) => {
        link.href = url;
        link.dataset.articleOpen = openUrl;
      });
      card.querySelector("[data-live-reading-source]").textContent =
        article.source || "Unknown source";
      card.querySelector("[data-live-reading-title]").textContent = article.title;
      setMedia(
        card.querySelector("[data-media-frame]"),
        article.image_url,
        `Thumbnail for ${article.title}`,
        "R"
      );
    });
    animateUpdate(readingGrid);
  }

  function remainingLabel(nextAt, noun) {
    const minutes = Math.max(0, Math.ceil((nextAt - Date.now()) / 60000));
    if (minutes <= 0) return "Updating…";
    if (minutes >= 60) {
      const hours = Math.ceil(minutes / 60);
      return `New ${noun} in ${hours}h`;
    }
    return `New ${noun} in ${minutes}m`;
  }

  function updateCountdowns() {
    if (movieCountdown) movieCountdown.textContent = remainingLabel(movieNextAt, "pick");
    if (youtubeCountdown) youtubeCountdown.textContent = remainingLabel(youtubeNextAt, "mix");
    if (pockettubeCountdown) pockettubeCountdown.textContent = remainingLabel(youtubeNextAt, "mix");
    if (readingCountdown) readingCountdown.textContent = remainingLabel(readingNextAt, "reads");
  }

  async function refreshLive() {
    if (inFlight) return;
    inFlight = true;
    try {
      const response = await fetch(root.dataset.endpoint, {
        cache: "no-store",
        headers: {Accept: "application/json"},
      });
      if (!response.ok) throw new Error(`Live home update failed: ${response.status}`);
      const payload = await response.json();
      const live = payload.item;
      const rotation = live.rotation;
      const movieChanged = String(rotation.movie_bucket) !== root.dataset.movieBucket;
      const youtubeChanged = String(rotation.youtube_bucket) !== root.dataset.youtubeBucket;
      const readingChanged = String(rotation.reading_bucket) !== root.dataset.readingBucket;

      if (movieChanged) renderMovie(live.recommended_movie);
      if (youtubeChanged) renderYouTube(live.latest_youtube || []);
      if (youtubeChanged) renderPocketTube(live.pockettube_favorite || []);
      if (readingChanged) renderReading(live.continue_reading || []);
      root.dataset.movieBucket = rotation.movie_bucket;
      root.dataset.youtubeBucket = rotation.youtube_bucket;
      root.dataset.readingBucket = rotation.reading_bucket;
      root.dataset.movieNextAt = rotation.movie_next_at;
      root.dataset.youtubeNextAt = rotation.youtube_next_at;
      root.dataset.readingNextAt = rotation.reading_next_at;
      movieNextAt = Date.parse(rotation.movie_next_at);
      youtubeNextAt = Date.parse(rotation.youtube_next_at);
      readingNextAt = Date.parse(rotation.reading_next_at);
      retryAt = 0;
      if (movieChanged || youtubeChanged || readingChanged) {
        if (announcer) {
          const updates = [];
          if (movieChanged) updates.push("movie pick");
          if (youtubeChanged) updates.push("video mixes");
          if (readingChanged) updates.push("saved reads");
          announcer.textContent = `${updates.join(", ")} updated.`;
        }
      }
    } catch (error) {
      retryAt = Date.now() + 60000;
      console.error(error);
    } finally {
      inFlight = false;
      updateCountdowns();
    }
  }

  function tick() {
    updateCountdowns();
    if (document.hidden) return;
    const now = Date.now();
    if (now >= movieNextAt || now >= youtubeNextAt || now >= readingNextAt || (retryAt && now >= retryAt)) {
      refreshLive();
    }
  }

  root.addEventListener("today:refresh", refreshLive);
  document.addEventListener("visibilitychange", tick);
  window.setInterval(tick, 15000);
  tick();
})();
