(() => {
  const root = document.querySelector("[data-book-reader]");
  if (!root) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const endpoint = root.dataset.progressUrl || "";
  const chapters = [...root.querySelectorAll("[data-reader-chapter]")];
  const links = [...root.querySelectorAll("[data-reader-chapter-link]")];
  const status = root.querySelector("[data-reader-status]");

  function asNumber(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function currentChapter() {
    let selected = chapters[0];
    let selectedTop = Number.NEGATIVE_INFINITY;
    chapters.forEach((chapter) => {
      const top = chapter.getBoundingClientRect().top;
      if (top <= 120 && top > selectedTop) {
        selected = chapter;
        selectedTop = top;
      }
    });
    return selected;
  }

  function scrollPercent() {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    if (scrollable <= 0) return 0;
    return Math.min(Math.max((window.scrollY / scrollable) * 100, 0), 100);
  }

  function markActive(chapterIndex) {
    links.forEach((link) => {
      link.toggleAttribute("aria-current", link.dataset.readerChapterLink === String(chapterIndex));
    });
    if (status) status.textContent = `Chapter ${Number(chapterIndex) + 1}`;
  }

  async function saveProgress() {
    if (!endpoint || !csrf) return;
    const chapter = currentChapter();
    if (!chapter) return;
    const chapterIndex = asNumber(chapter.dataset.readerChapter);
    markActive(chapterIndex);
    try {
      await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
          Accept: "application/json",
        },
        body: JSON.stringify({
          chapter_index: chapterIndex,
          scroll_percent: scrollPercent(),
        }),
      });
    } catch (_error) {
      // Reading should never stop because an opportunistic local progress save failed.
    }
  }

  function resumePosition() {
    const chapterIndex = asNumber(root.dataset.initialChapter);
    const initialScroll = asNumber(root.dataset.initialScroll);
    const target = root.querySelector(`[data-reader-chapter="${chapterIndex}"]`);
    if (target) {
      target.scrollIntoView({ block: "start" });
      markActive(chapterIndex);
    }
    if (initialScroll > 0) {
      requestAnimationFrame(() => {
        const scrollable = document.documentElement.scrollHeight - window.innerHeight;
        window.scrollTo({ top: scrollable * (initialScroll / 100) });
      });
    }
  }

  let saveTimer = 0;
  window.addEventListener(
    "scroll",
    () => {
      window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(saveProgress, 500);
    },
    { passive: true }
  );
  window.addEventListener("pagehide", saveProgress);
  links.forEach((link) => {
    link.addEventListener("click", () => {
      markActive(link.dataset.readerChapterLink);
      window.setTimeout(saveProgress, 800);
    });
  });

  resumePosition();
})();
