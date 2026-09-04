import { axFetch, notify, setControlLoading } from "./app.js";

document.querySelector("#run-review")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setControlLoading(button, true);
  try {
    const response = await axFetch(button.dataset.url, {
      method: "POST",
      json: { reviewer_type: document.querySelector("#reviewer-type").value },
      loadingMessage: "Running quality check...",
    });
    notify(response.message || "Quality check completed.");
    window.location.reload();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(button, false);
  }
});

document.querySelector("#finding-filter")?.addEventListener("change", (event) => {
  const value = event.target.value;
  document.querySelectorAll(".finding-card").forEach((card) => {
    card.hidden = value !== "all" && card.dataset.severity !== value;
  });
});

document.querySelectorAll("[data-finding-status]").forEach((button) => {
  button.addEventListener("click", async () => {
    const card = button.closest("[data-finding-id]");
    const note = card.querySelector("[data-resolution-note]").value;
    setControlLoading(button, true);
    try {
      const response = await axFetch(button.dataset.url, {
        method: "PATCH",
        json: { status: button.dataset.findingStatus, resolution_note: note },
        loadingMessage: "Updating quality note...",
      });
      notify(response.message || "Quality note updated.");
      window.location.reload();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setControlLoading(button, false);
    }
  });
});
