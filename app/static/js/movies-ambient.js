(() => {
  const root = document.querySelector(".movies-v2[data-ambient-level]");
  if (!root) return;

  const level = root.dataset.ambientLevel || "subtle";
  const motionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const reduced = root.dataset.reducedEffects === "true" || motionQuery?.matches;
  if (level === "off" || reduced) {
    root.dataset.ambientState = level === "off" ? "off" : "reduced";
    return;
  }

  const image = root.querySelector(
    ".movie-detail__backdrop img, .movie-detail__poster img, [data-home-focus] [data-media-image], [data-recommendation-poster]"
  );
  if (!image) return;

  const sourceUrl = image.currentSrc || image.src;
  const cacheKey = sourceUrl && sourceUrl.length <= 500
    ? `dragon:movies:ambient:v1:${sourceUrl}`
    : "";
  const clampChannel = (value) => Math.max(0, Math.min(170, Math.round(Number(value) || 0)));
  const applyPalette = (palette, state) => {
    if (!Array.isArray(palette) || palette.length !== 3) return false;
    const channels = palette.map(clampChannel);
    if (!channels.some(Boolean)) return false;
    root.style.setProperty("--movie-ambient-primary", channels.join(" "));
    root.style.setProperty(
      "--movie-ambient-secondary",
      channels.map((channel) => Math.max(0, Math.min(170, channel + 14))).join(" ")
    );
    root.dataset.ambientState = state;
    return true;
  };
  const readCachedPalette = () => {
    if (!cacheKey) return false;
    try {
      return applyPalette(JSON.parse(sessionStorage.getItem(cacheKey) || "null"), "cached");
    } catch (_error) {
      return false;
    }
  };
  const storePalette = (palette) => {
    if (!cacheKey) return;
    try {
      sessionStorage.setItem(cacheKey, JSON.stringify(palette));
    } catch (_error) {
      // The visual fallback must not depend on browser storage.
    }
  };
  const sampleArtwork = () => {
    if (readCachedPalette()) return;
    if (!image.naturalWidth || !image.naturalHeight) return;
    try {
      const canvas = document.createElement("canvas");
      const size = 16;
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return;
      context.drawImage(image, 0, 0, size, size);
      const pixels = context.getImageData(0, 0, size, size).data;
      const totals = [0, 0, 0];
      let sampled = 0;
      for (let index = 0; index < pixels.length; index += 4) {
        const [red, green, blue, alpha] = pixels.slice(index, index + 4);
        const luminance = (red * 0.2126) + (green * 0.7152) + (blue * 0.0722);
        if (alpha < 150 || luminance < 18 || luminance > 225) continue;
        totals[0] += red;
        totals[1] += green;
        totals[2] += blue;
        sampled += 1;
      }
      if (sampled < 10) return;
      const palette = totals.map((total) => clampChannel(total / sampled));
      if (applyPalette(palette, "artwork")) storePalette(palette);
    } catch (_error) {
      // Cross-origin artwork can make canvas reads unavailable; CSS keeps the fallback.
    }
  };
  const scheduleSample = () => {
    if (window.requestIdleCallback) {
      window.requestIdleCallback(sampleArtwork, { timeout: 900 });
      return;
    }
    window.setTimeout(sampleArtwork, 80);
  };

  if (image.complete) {
    scheduleSample();
  } else {
    image.addEventListener("load", scheduleSample, { once: true });
  }
})();
