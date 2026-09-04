import { axFetch, notify, setControlLoading } from "./app.js";

document.querySelectorAll("[data-auto-correct-attention]").forEach((button) => {
  button.addEventListener("click", async () => {
    const label = button.textContent;
    setControlLoading(button, true);
    button.textContent = "Correcting";
    try {
      const response = await axFetch(button.dataset.autoCorrectAttention, {
        method: "POST",
        json: {},
        loadingMessage: "Correcting your brief...",
      });
      notify(response.message || "Auto correct finished.");
      window.location.reload();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setControlLoading(button, false);
      button.textContent = label;
    }
  });
});
