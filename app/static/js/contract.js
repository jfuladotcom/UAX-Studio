import { axFetch, notify, setControlLoading, setSaveStatus } from "./app.js";

const editor = document.querySelector("#contract-editor");
const status = document.querySelector("#contract-status");
let saveTimer = null;

function uuid() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `item-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setStatus(message, tone = "") {
  if (status) {
    status.textContent = message;
    status.className = `status-chip ${tone}`;
  }
  setSaveStatus(message);
}

function serializeContract() {
  const content = {};
  editor.querySelectorAll(".contract-section").forEach((section) => {
    const sectionKey = section.dataset.section;
    content[sectionKey] = {
      title: section.querySelector("h3")?.textContent || sectionKey,
      fields: {},
    };
    section.querySelectorAll(".contract-field").forEach((field) => {
      const fieldKey = field.dataset.field;
      const type = field.dataset.type;
      const payload = {
        label: field.querySelector("[data-label]").value,
        type,
        provenance: field.querySelector("[data-provenance]").value || "user_written",
      };
      if (type === "list") {
        payload.items = Array.from(field.querySelectorAll(".contract-list-item")).map((item) => ({
          id: item.dataset.itemId || uuid(),
          text: item.querySelector("[data-item-text]").value,
          provenance: item.querySelector("[data-item-provenance]").value || "user_written",
        })).filter((item) => item.text.trim());
      } else {
        payload.value = field.querySelector("[data-field-value]").value;
      }
      content[sectionKey].fields[fieldKey] = payload;
    });
  });
  return content;
}

async function saveContract() {
  if (!editor) return;
  setStatus("Saving", "");
  try {
    await axFetch(editor.dataset.saveUrl, {
      method: "PATCH",
      json: { content_json: serializeContract() },
      loadingMessage: "Saving instructions...",
    });
    setStatus("Saved", "saved");
  } catch (error) {
    setStatus("Save error", "error");
    notify(error.message, "error");
  }
}

function scheduleSave() {
  setStatus("Unsaved", "");
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(saveContract, 700);
}

function createListItem() {
  const row = document.createElement("div");
  row.className = "contract-list-item";
  row.dataset.itemId = uuid();

  const textarea = document.createElement("textarea");
  textarea.rows = 2;
  textarea.dataset.itemText = "";

  const provenance = document.createElement("input");
  provenance.type = "hidden";
  provenance.dataset.itemProvenance = "";
  provenance.value = "user_written";

  const remove = document.createElement("button");
  remove.className = "icon-button";
  remove.type = "button";
  remove.dataset.removeItem = "";
  remove.setAttribute("aria-label", "Remove item");
  remove.title = "Remove item";
  remove.textContent = "x";

  row.append(textarea, provenance, remove);
  return row;
}

if (editor) {
  editor.addEventListener("input", scheduleSave);
  editor.addEventListener("change", scheduleSave);
  editor.addEventListener("click", (event) => {
    const add = event.target.closest("[data-add-item]");
    if (add) {
      const list = add.closest(".contract-field").querySelector(".contract-list");
      list.append(createListItem());
      scheduleSave();
    }
    const remove = event.target.closest("[data-remove-item]");
    if (remove) {
      remove.closest(".contract-list-item").remove();
      scheduleSave();
    }
  });
}

document.querySelector("[data-contract-suggest]")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setControlLoading(button, true);
  try {
    const response = await axFetch(button.dataset.contractSuggest, {
      method: "POST",
      json: {},
      loadingMessage: "Drafting build instructions...",
    });
    notify(response.data.notice || response.message || "Build instructions updated.");
    window.location.reload();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(button, false);
  }
});

document.querySelector("[data-contract-version]")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setControlLoading(button, true);
  try {
    await saveContract();
    const response = await axFetch(button.dataset.contractVersion, {
      method: "POST",
      json: {},
      loadingMessage: "Saving instruction version...",
    });
    notify(response.message || "Version saved.");
    window.location.reload();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(button, false);
  }
});
