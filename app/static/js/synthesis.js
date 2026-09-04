import { axFetch, notify, setControlLoading } from "./app.js";

document.querySelectorAll("[data-save-synthesis]").forEach((button) => {
  button.addEventListener("click", async () => {
    const item = button.closest("[data-item-id]");
    const payload = {};
    item.querySelectorAll("[data-synthesis-field]").forEach((field) => {
      const key = field.dataset.synthesisField;
      payload[key] = field.type === "checkbox" ? field.checked : field.value;
    });
    setControlLoading(button, true);
    try {
      const response = await axFetch(button.dataset.saveSynthesis, {
        method: "PATCH",
        json: payload,
        loadingMessage: "Saving key detail...",
      });
      notify(response.message || "Key detail saved.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setControlLoading(button, false);
    }
  });
});
