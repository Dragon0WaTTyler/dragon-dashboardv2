(() => {
  const list = document.querySelector("[data-home-layout-list]");
  const orderInput = document.querySelector("[data-layout-order]");
  if (!list || !orderInput) return;

  let dragged = null;
  const updateOrder = () => {
    orderInput.value = [...list.querySelectorAll("[data-home-key]")]
      .map((item) => item.dataset.homeKey)
      .join(",");
  };

  list.querySelectorAll("[data-home-key]").forEach((item) => {
    item.addEventListener("dragstart", () => {
      dragged = item;
      item.classList.add("is-dragging");
    });
    item.addEventListener("dragend", () => {
      dragged?.classList.remove("is-dragging");
      dragged = null;
      updateOrder();
    });
    item.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (!dragged || dragged === item) return;
      const after = event.clientY > item.getBoundingClientRect().top + item.offsetHeight / 2;
      list.insertBefore(dragged, after ? item.nextSibling : item);
    });
  });
})();
