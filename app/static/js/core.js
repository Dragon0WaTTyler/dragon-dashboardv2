(() => {
  window.requestAnimationFrame(() => document.body.classList.add("is-ready"));

  document.querySelectorAll(
    "main h1, main h2, main h3, main p, main blockquote, main dd, main td, main li"
  ).forEach((element) => {
    if (!element.hasAttribute("dir")) element.setAttribute("dir", "auto");
  });

  document.addEventListener(
    "error",
    (event) => {
      if (!(event.target instanceof HTMLImageElement) || !event.target.matches("[data-media-image]")) {
        return;
      }
      event.target.closest("[data-media-frame]")?.classList.add("image-failed");
    },
    true
  );

  const focusableSelector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  let dialogOpener = null;

  function openDialog(dialog, opener) {
    if (!dialog || dialog.open) return;
    dialogOpener = opener;
    dialog.showModal();
    const target = dialog.querySelector("input, button, a[href]");
    if (target) target.focus();
  }

  function closeDialog(dialog) {
    if (!dialog || !dialog.open) return;
    dialog.close();
    if (dialogOpener) dialogOpener.focus();
    dialogOpener = null;
  }

  document.addEventListener("click", (event) => {
    const openTrigger = event.target.closest("[data-dialog-open]");
    if (openTrigger) {
      openDialog(document.getElementById(openTrigger.dataset.dialogOpen), openTrigger);
      return;
    }

    const closeTrigger = event.target.closest("[data-dialog-close]");
    if (closeTrigger) closeDialog(closeTrigger.closest("dialog"));
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      const trigger = document.querySelector("[data-dialog-open='command-dialog']");
      openDialog(document.getElementById("command-dialog"), trigger);
      return;
    }

    const dialog = document.querySelector("dialog[open]");
    if (!dialog) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog(dialog);
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = [...dialog.querySelectorAll(focusableSelector)].filter(
      (element) => !element.hasAttribute("hidden")
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog(dialog);
    });
  });

  const search = document.querySelector("[data-command-search]");
  if (search) {
    search.addEventListener("input", () => {
      const query = search.value.trim().toLowerCase();
      document.querySelectorAll("[data-command-list] > *").forEach((item) => {
        item.hidden = query.length > 0 && !item.textContent.toLowerCase().includes(query);
      });
    });
  }

})();
