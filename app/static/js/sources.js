import { axFetch, notify, setControlLoading } from "./app.js";

document.querySelectorAll("[data-save-source]").forEach((button) => {
  button.addEventListener("click", async () => {
    const editor = button.closest("[data-source-id]");
    const payload = {};
    editor.querySelectorAll("[data-source-field]").forEach((field) => {
      payload[field.dataset.sourceField] = field.value;
    });
    setControlLoading(button, true);
    try {
      const response = await axFetch(button.dataset.saveSource, {
        method: "PATCH",
        json: payload,
        loadingMessage: "Saving background information...",
      });
      notify(response.message || "Background information saved.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setControlLoading(button, false);
    }
  });
});

document.querySelectorAll("[data-delete-source]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!window.confirm("Remove this background information?")) return;
    setControlLoading(button, true);
    try {
      await axFetch(button.dataset.deleteSource, {
        method: "DELETE",
        loadingMessage: "Removing background information...",
      });
      window.location.reload();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setControlLoading(button, false);
    }
  });
});
