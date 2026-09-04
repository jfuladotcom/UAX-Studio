import { axFetch, notify, setControlLoading } from "./app.js";

const includeSources = document.querySelector("#include-sources");
const exportList = document.querySelector("[data-export-list]");
const exportCount = document.querySelector("[data-export-count]");
const exportEmpty = document.querySelector("[data-export-empty]");

function downloadExport(url) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
}

function formatExportTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function fileDownloadUrl(downloadUrl, filename) {
  const url = new URL(downloadUrl, window.location.href);
  url.searchParams.set("file", filename);
  return `${url.pathname}${url.search}`;
}

function addExportToHistory(record) {
  if (!exportList) return;
  const article = document.createElement("article");
  const summary = document.createElement("div");
  const title = document.createElement("strong");
  const versions = document.createElement("small");
  title.textContent = `Package ${formatExportTime(record.created_at)}`;
  versions.textContent = `Contract v${record.contract_version} - Workflow v${record.workflow_version}`;
  summary.append(title, versions);

  const download = document.createElement("a");
  download.className = "button small";
  download.href = record.download_url;
  download.textContent = "Download ZIP";

  const details = document.createElement("details");
  const detailsSummary = document.createElement("summary");
  const files = document.createElement("ul");
  detailsSummary.textContent = "Individual files";
  const paths = [
    ...(record.manifest?.files || []).map((file) => file.path),
    "implementation_manifest.json",
  ];
  [...new Set(paths)].forEach((filename) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = fileDownloadUrl(record.download_url, filename);
    link.textContent = filename;
    item.append(link);
    files.append(item);
  });
  details.append(detailsSummary, files);
  article.append(summary, download, details);
  exportList.prepend(article);
  exportList.hidden = false;
  if (exportEmpty) exportEmpty.hidden = true;

  if (exportCount) {
    const count = Number(exportCount.dataset.count || 0) + 1;
    exportCount.dataset.count = String(count);
    exportCount.textContent = `${count} package${count === 1 ? "" : "s"}`;
  }
}

document.querySelector("#generate-export")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  setControlLoading(button, true);
  try {
    const response = await axFetch(button.dataset.url, {
      method: "POST",
      json: { include_sources: Boolean(includeSources?.checked) },
      loadingMessage: "Building export package...",
    });
    downloadExport(response.data.export.download_url);
    addExportToHistory(response.data.export);
    notify("ZIP download started.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setControlLoading(button, false);
  }
});
