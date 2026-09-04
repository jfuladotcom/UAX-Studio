import { axFetch, notify, setControlLoading } from "./app.js";

const form = document.querySelector("#settings-form");
const providerSelect = form?.querySelector("#active-provider");
const modelStatus = document.querySelector("#model-status");
const OLLAMA_PREFIX = "ollama::";

function settingsPayload() {
  const data = new FormData(form);
  const providerChoice = data.get("provider_choice") || "deterministic";
  const ollamaBaseUrl = data.get("ollama_base_url") || form?.dataset.ollamaBaseUrl || "";
  const ollamaTimeout = data.get("ollama_timeout") || form?.dataset.ollamaTimeout || 20;
  const payload = {
    provider_choice: providerChoice,
    active_provider: "deterministic",
    ollama_base_url: ollamaBaseUrl,
    ollama_model: "",
    ollama_timeout: Number(ollamaTimeout),
    data_dir: data.get("data_dir"),
    export_dir: data.get("export_dir"),
    reduced_motion: Boolean(data.get("reduced_motion")),
  };
  if (providerChoice.startsWith(OLLAMA_PREFIX)) {
    payload.active_provider = "ollama";
    payload.ollama_model = providerChoice.slice(OLLAMA_PREFIX.length);
  }
  return payload;
}

function renderProviderOptions(models, selectedProvider = "deterministic") {
  if (!providerSelect) return;
  const previous = selectedProvider || providerSelect.value || "deterministic";
  const options = [new Option("Built-in draft helper", "deterministic")];
  for (const model of models) {
    options.push(new Option(`Ollama: ${model}`, `${OLLAMA_PREFIX}${model}`));
  }
  providerSelect.replaceChildren(...options);
  providerSelect.value = [...providerSelect.options].some((option) => option.value === previous)
    ? previous
    : "deterministic";
}

function syncProviderSelection(settings) {
  if (!providerSelect || settings.active_provider !== "deterministic") return;
  providerSelect.value = "deterministic";
}

function syncDirectoryFields(settings) {
  for (const name of ["data_dir", "export_dir"]) {
    const input = form?.querySelector(`[name="${name}"]`);
    if (input && settings[name]) input.value = settings[name];
  }
}

function syncComfortSettings(settings) {
  document.body.classList.toggle("reduced-motion", Boolean(settings.reduced_motion));
}

async function refreshModels() {
  const response = await axFetch("/api/settings/providers/ollama/models", {
    method: "POST",
    json: settingsPayload(),
    loadingMessage: "Checking local models...",
  });
  const models = response.data.models || [];
  renderProviderOptions(models, response.data.selected_provider);
  if (modelStatus) modelStatus.textContent = response.message || "Model list refreshed.";
  return response;
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter || form.querySelector('[type="submit"]');
  setControlLoading(submit, true);
  try {
    const response = await axFetch("/api/settings", {
      method: "PATCH",
      json: settingsPayload(),
      loadingMessage: "Saving settings...",
    });
    const settings = response.data.settings || {};
    syncProviderSelection(settings);
    syncDirectoryFields(settings);
    syncComfortSettings(settings);
    notify(response.message || "Settings saved.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(submit, false);
  }
});

document.querySelector("#test-local-models")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setControlLoading(button, true);
  try {
    const response = await refreshModels();
    notify(response.message || "Local models tested.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(button, false);
  }
});

document.querySelector("#reset-demo")?.addEventListener("click", async (event) => {
  const message =
    "Reset the GalleryFlow demo to its seeded state? This only changes the demo agent; your other agents are left alone.";
  if (!window.confirm(message)) return;
  const button = event.currentTarget;
  setControlLoading(button, true);
  try {
    const response = await axFetch(button.dataset.url, {
      method: "POST",
      json: {},
      loadingMessage: "Resetting demo agent...",
    });
    notify(response.message || "Demo reset.");
    window.location.href = `/agents/${response.data.project_id}/brief`;
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(button, false);
  }
});
