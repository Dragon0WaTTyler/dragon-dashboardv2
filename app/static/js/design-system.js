(() => {
  const trigger = document.querySelector("[data-toast-demo]");
  const toast = document.querySelector("[data-toast]");
  let hideTimer = null;
  if (!trigger || !toast) return;

  trigger.addEventListener("click", () => {
    toast.hidden = false;
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      toast.hidden = true;
    }, 2400);
  });
})();
