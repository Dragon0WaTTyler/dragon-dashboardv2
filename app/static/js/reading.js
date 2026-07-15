const openForm = document.querySelector("[data-article-open-form]");

if (openForm) {
  document.querySelectorAll("[data-article-open]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      event.preventDefault();
      const card = link.closest(".article-card");
      card?.setAttribute("aria-busy", "true");
      link.setAttribute("aria-disabled", "true");
      openForm.action = link.dataset.articleOpen;
      openForm.submit();
    });
  });
}
