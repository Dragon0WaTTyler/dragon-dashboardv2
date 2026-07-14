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
