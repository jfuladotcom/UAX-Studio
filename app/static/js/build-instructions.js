import { axFetch, notify, setControlLoading } from "./app.js";
import { saveContract } from "./contract.js";

document.querySelectorAll("[data-generate-instructions]").forEach((button) => {
  button.addEventListener("click", async () => {
    setControlLoading(button, true);
    try {
      if (document.querySelector("#contract-editor")) await saveContract();
      const response = await axFetch(button.dataset.generateInstructions, {
        method: "POST",
        json: {},
        loadingMessage: "Generating Build Instructions from saved Background Information...",
      });
      if (response.data.notice) sessionStorage.setItem("build-instructions-notice", response.data.notice);
      window.location.assign(button.dataset.instructionsUrl || window.location.href);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setControlLoading(button, false);
    }
  });
});

if (document.querySelector("#contract-editor")) {
  const notice = sessionStorage.getItem("build-instructions-notice");
  if (notice) {
    sessionStorage.removeItem("build-instructions-notice");
    notify(notice);
  }
}
