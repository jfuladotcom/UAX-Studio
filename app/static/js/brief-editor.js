import { axFetch, notify, setControlLoading } from "./app.js";

const dialog = document.querySelector("#brief-editor");
const form = document.querySelector("#brief-section-form");
const fields = document.querySelector("#brief-editor-fields");
const title = document.querySelector("#brief-editor-title");
const message = document.querySelector("#brief-editor-message");
const save = document.querySelector("#brief-editor-save");
let selected = null;
let baseline = {};
let openerKey = "";
let endpoint = "";
let saving = false;
let loadSequence = 0;
let controlSequence = 0;

function values() {
  return Object.fromEntries([...fields.children].map((field) => {
    const key = field.dataset.fieldKey;
    const value = field.dataset.fieldType === "list"
      ? [...field.querySelectorAll("[data-list-item]")].map((row) => ({
        ...(row.dataset.itemId ? { id: row.dataset.itemId } : {}),
        text: row.querySelector("textarea").value,
      }))
      : field.querySelector("textarea").value;
    return [key, value];
  }));
}

function dirty() {
  return selected && JSON.stringify(values()) !== JSON.stringify(baseline);
}

function closePanel() {
  if (saving) return;
  if (dirty() && !window.confirm("Discard your unsaved changes to this section?")) return;
  dialog.close();
}

function textarea(label, value, maxlength) {
  const input = document.createElement("textarea");
  input.id = `brief-input-${++controlSequence}`;
  input.rows = 3;
  input.value = value;
  if (maxlength) input.maxLength = maxlength;
  input.setAttribute("aria-label", label);
  return input;
}

function listRow(container, field, item = {}) {
  const row = document.createElement("div");
  row.className = "brief-editor-list-item";
  row.dataset.listItem = "";
  if (item.id) row.dataset.itemId = item.id;
  const input = textarea(`${field.label} item`, item.text || "");
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "button small";
  remove.textContent = "Remove";
  remove.setAttribute("aria-label", `Remove item from ${field.label}`);
  remove.addEventListener("click", () => {
    const nextFocus = row.nextElementSibling?.querySelector("textarea")
      || row.previousElementSibling?.querySelector("textarea")
      || container.parentElement.querySelector("[data-add-brief-item]");
    row.remove();
    nextFocus?.focus();
  });
  row.append(input, remove);
  container.append(row);
  return input;
}

function renderFields(module) {
  fields.replaceChildren();
  for (const field of module.fields) {
    const container = document.createElement(field.type === "list" ? "fieldset" : "div");
    container.className = "brief-editor-field";
    container.dataset.fieldKey = field.key;
    container.dataset.fieldType = field.type;
    const label = document.createElement(field.type === "list" ? "legend" : "label");
    label.textContent = field.label;
    container.append(label);
    if (field.type === "list") {
      const list = document.createElement("div");
      container.append(list);
      for (const item of field.items) listRow(list, field, item);
      const add = document.createElement("button");
      add.type = "button";
      add.className = "button small";
      add.dataset.addBriefItem = "";
      add.textContent = "Add item";
      add.setAttribute("aria-label", `Add item to ${field.label}`);
      add.addEventListener("click", () => listRow(list, field).focus());
      container.append(add);
    } else {
      const input = textarea(field.label, field.value, field.maxlength);
      label.htmlFor = input.id;
      container.append(input);
    }
    fields.append(container);
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-edit-section]");
  if (!button || dialog.open) return;
  openerKey = button.dataset.editSection;
  endpoint = button.dataset.sectionUrl;
  selected = null;
  fields.replaceChildren();
  title.textContent = button.dataset.sectionTitle;
  message.textContent = "Loading saved values...";
  message.className = "quiet";
  save.disabled = true;
  dialog.showModal();
  document.body.classList.add("brief-editor-open");
  title.focus();
  const request = ++loadSequence;
  try {
    const response = await axFetch(endpoint, { loadingMessage: "Loading section..." });
    if (!dialog.open || request !== loadSequence) return;
    selected = response.data.module;
    title.textContent = selected.title;
    renderFields(selected);
    baseline = values();
    message.textContent = "";
    save.disabled = false;
    fields.querySelector("textarea, button")?.focus();
  } catch (error) {
    if (!dialog.open || request !== loadSequence) return;
    message.textContent = error.message;
    message.className = "error-text";
  }
});

dialog.querySelectorAll("[data-close-brief-editor]").forEach((button) => button.addEventListener("click", closePanel));
dialog.addEventListener("cancel", (event) => { event.preventDefault(); closePanel(); });
dialog.addEventListener("click", (event) => { if (event.target === dialog) closePanel(); });
dialog.addEventListener("close", () => {
  // A queued close event can arrive after the user has already reopened it.
  if (dialog.open) return;
  ++loadSequence;
  selected = null;
  document.body.classList.remove("brief-editor-open");
  document.querySelector(`[data-edit-section="${openerKey}"]`)?.focus();
});
dialog.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closePanel();
    return;
  }
  if (event.key !== "Tab") return;
  const controls = [...dialog.querySelectorAll("button:not(:disabled), textarea:not(:disabled)")];
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && (document.activeElement === first || document.activeElement === title)) {
    event.preventDefault(); last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault(); first?.focus();
  }
});
window.addEventListener("beforeunload", (event) => {
  if (!dirty()) return;
  event.preventDefault();
  event.returnValue = "";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selected || saving) return;
  saving = true;
  setControlLoading(save, true);
  dialog.setAttribute("aria-busy", "true");
  const changes = Object.fromEntries(Object.entries(values()).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(baseline[key])));
  form.querySelectorAll("textarea, button").forEach((control) => { control.disabled = true; });
  message.textContent = "Saving changes...";
  message.className = "quiet";
  try {
    const response = await axFetch(endpoint, {
      method: "PATCH", json: { fields: changes, revision: selected.revision },
      loadingMessage: "Saving section...",
    });
    document.querySelector("#brief-modules").innerHTML = response.data.modules_html;
    document.querySelector("[data-project-status]").textContent = response.data.status;
    document.querySelector("[data-project-progress]").textContent = `${response.data.percent}% complete`;
    selected = null;
    dialog.close();
    notify(response.message || "Changes saved.");
  } catch (error) {
    message.textContent = error.message;
    message.className = "error-text";
  } finally {
    saving = false;
    dialog.removeAttribute("aria-busy");
    form.querySelectorAll("textarea, button").forEach((control) => { control.disabled = false; });
    setControlLoading(save, false);
  }
});
