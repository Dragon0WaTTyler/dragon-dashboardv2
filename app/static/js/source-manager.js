(() => {
  const forms = [...document.querySelectorAll("[data-source-draft-form]")];
  document.querySelectorAll('.source-editor[action$="/sections/reading/sources"]').forEach((form) => {
    const button = form.querySelector('button[name="submit_action"][value="test"]');
    if (!button) return;
    form.dataset.testUrl = `${form.action}/test-draft`;
    form.dataset.sourceDraftForm = "";
    button.type = "button";
    button.removeAttribute("name");
    button.removeAttribute("value");
    button.dataset.testSource = "";
    button.textContent = "Test connection";
    const result = document.createElement("p");
    result.className = "source-test-result source-editor__wide";
    result.dataset.testResult = "";
    result.setAttribute("role", "status");
    result.hidden = true;
    form.querySelector(".source-editor__actions")?.before(result);
    forms.push(form);
  });

  forms.forEach((form) => {
    const button = form.querySelector("[data-test-source]");
    const result = form.querySelector("[data-test-result]");
    if (!button || !result) return;

    button.addEventListener("click", async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      button.disabled = true;
      result.hidden = false;
      result.dataset.state = "testing";
      result.textContent = "Testing connection…";
      try {
        const response = await fetch(form.dataset.testUrl, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        const payload = await response.json();
        result.dataset.state = payload.ok ? "success" : "error";
        result.textContent = payload.message;
      } catch (_error) {
        result.dataset.state = "error";
        result.textContent = "The connection test could not be completed.";
      } finally {
        button.disabled = false;
      }
    });
  });
})();
