const token = document.querySelector('meta[name="csrf-token"]')?.content || "";
const liveRegion = document.querySelector("#live-region");
const loadingIndicator = document.querySelector("[data-loading-indicator]");
const loadingMessage = loadingIndicator?.querySelector("[data-loading-message]");
const activeRequests = new Map();
let requestSequence = 0;
let loadingTimer = null;

function updateLoadingMessage(message) {
  if (loadingMessage) loadingMessage.textContent = message || "Working...";
}

function showLoadingIndicator() {
  window.clearTimeout(loadingTimer);
  loadingTimer = null;
  if (loadingIndicator) loadingIndicator.hidden = false;
}

function beginRequestLoading(message = "Working...") {
  const requestId = ++requestSequence;
  activeRequests.set(requestId, message);
  updateLoadingMessage(message);
  if (activeRequests.size === 1) {
    loadingTimer = window.setTimeout(showLoadingIndicator, 120);
  }
  return requestId;
}

function finishRequestLoading(requestId) {
  activeRequests.delete(requestId);
  if (activeRequests.size) {
    updateLoadingMessage(Array.from(activeRequests.values()).at(-1));
    return;
  }
  window.clearTimeout(loadingTimer);
  loadingTimer = null;
  if (loadingIndicator) loadingIndicator.hidden = true;
}

function beginPageLoading(message, control) {
  updateLoadingMessage(message || "Loading...");
  showLoadingIndicator();
  document.body.classList.add("page-loading");
  document.body.setAttribute("aria-busy", "true");
  if (control) {
    control.classList.add("is-loading");
    control.setAttribute("aria-busy", "true");
  }
}

export function setControlLoading(control, isLoading) {
  if (!control) return;
  control.disabled = isLoading;
  control.classList.toggle("is-loading", isLoading);
  if (isLoading) {
    control.setAttribute("aria-busy", "true");
  } else {
    control.removeAttribute("aria-busy");
  }
}

export async function axFetch(url, options = {}) {
  const { json, loadingMessage: message = "Working...", ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers || {});
  headers.set("X-CSRFToken", token);
  const init = { ...requestOptions, headers };
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(json);
  }
  const requestId = beginRequestLoading(message);
  try {
    const response = await fetch(url, init);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error?.message || data.message || "Local request failed.");
    }
    return data;
  } finally {
    finishRequestLoading(requestId);
  }
}

export function notify(message, tone = "success") {
  if (liveRegion) {
    liveRegion.textContent = message;
  }
  const stack = document.querySelector(".flash-stack");
  if (!stack) return;
  const note = document.createElement("div");
  note.className = `flash flash-${tone}`;
  note.textContent = message;
  stack.append(note);
  dismissFlash(note);
}

function dismissFlash(note) {
  window.setTimeout(() => {
    note.classList.add("flash-exiting");
    note.addEventListener("animationend", () => note.remove(), { once: true });
  }, 4200);
}

export function setSaveStatus(message) {
  const status = document.querySelector("#save-status");
  if (status) status.textContent = message;
}

export function formToObject(form) {
  const data = new FormData(form);
  const payload = {};
  for (const [key, value] of data.entries()) {
    if (value instanceof File) continue;
    payload[key] = value;
  }
  return payload;
}

window.axFetch = axFetch;
window.axNotify = notify;

document.querySelectorAll(".flash-stack .flash").forEach(dismissFlash);

const railToggle = document.querySelector("[data-rail-toggle]");
const savedRailState = window.localStorage?.getItem("axRailCollapsed");
if (savedRailState === "true") {
  document.body.classList.add("rail-collapsed");
}

railToggle?.addEventListener("click", () => {
  const collapsed = document.body.classList.toggle("rail-collapsed");
  railToggle.textContent = collapsed ? "Expand" : "Collapse";
  railToggle.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
  window.localStorage?.setItem("axRailCollapsed", String(collapsed));
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form");
  if (!form) return;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    return;
  }
  if (!form.matches("[data-api-form]")) {
    if (event.defaultPrevented) return;
    const submit = event.submitter || form.querySelector('[type="submit"]');
    beginPageLoading(submit?.dataset.loadingMessage || "Loading...", submit);
    return;
  }
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]');
  setControlLoading(submit, true);
  try {
    const response = await axFetch(form.action, {
      method: form.method.toUpperCase(),
      body: new FormData(form),
      loadingMessage: submit?.dataset.loadingMessage || "Saving...",
    });
    notify(response.message || "Saved.");
    if (form.dataset.reload !== undefined) window.location.reload();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(submit, false);
  }
});

window.addEventListener("pageshow", () => {
  document.body.classList.remove("page-loading");
  document.body.removeAttribute("aria-busy");
  document.querySelectorAll(".is-loading").forEach((control) => {
    control.classList.remove("is-loading");
    control.removeAttribute("aria-busy");
  });
  if (!activeRequests.size && loadingIndicator) loadingIndicator.hidden = true;
});
