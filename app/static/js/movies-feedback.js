(() => {
  const region = document.createElement("div");
  region.className = "movies-toast-region";
  region.setAttribute("aria-live", "polite");
  region.setAttribute("aria-label", "Movies updates");
  document.body.append(region);

  const dismiss = (toast) => {
    toast.classList.add("is-leaving");
    window.setTimeout(() => toast.remove(), 180);
  };
  const show = (message, level = "success") => {
    const text = String(message || "").trim();
    if (!text) return;
    const toast = document.createElement("div");
    toast.className = `movies-toast movies-toast--${level}`;
    toast.setAttribute("role", level === "error" ? "alert" : "status");
    const copy = document.createElement("span");
    copy.textContent = text;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "movies-toast__close";
    close.setAttribute("aria-label", "Dismiss Movies update");
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(toast));
    toast.append(copy, close);
    region.append(toast);
    window.setTimeout(() => dismiss(toast), level === "error" ? 7000 : 4200);
  };
  const readNextPageToast = () => {
    try {
      const saved = JSON.parse(sessionStorage.getItem("dragon:movies:next-toast") || "null");
      sessionStorage.removeItem("dragon:movies:next-toast");
      if (saved?.message) show(saved.message, saved.level);
    } catch (_error) {
      // Feedback must not depend on browser storage.
    }
  };

  const flashRegion = document.querySelector(".flash-region");
  flashRegion?.querySelectorAll(".notice").forEach((notice) => {
    const classes = notice.classList;
    const level = classes.contains("notice--error")
      ? "error"
      : classes.contains("notice--warning")
      ? "warning"
      : "success";
    show(notice.textContent, level);
    notice.remove();
  });
  if (flashRegion && !flashRegion.children.length) flashRegion.hidden = true;
  readNextPageToast();
  window.addEventListener("dragon:movies:toast", (event) => {
    show(event.detail?.message, event.detail?.level || "success");
  });
})();
