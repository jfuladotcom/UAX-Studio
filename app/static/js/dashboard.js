const search = document.querySelector("#brief-search");
const status = document.querySelector("#brief-status-filter");
const sort = document.querySelector("#brief-sort");
const cards = Array.from(document.querySelectorAll("[data-brief-card]"));
const noMatches = document.querySelector("#brief-no-matches");
const list = document.querySelector("#project-list");
const clearFilters = document.querySelector("#clear-brief-filters");

function applyFilters() {
  const query = (search?.value || "").trim().toLowerCase();
  const selectedStatus = status?.value || "all";
  let visibleCount = 0;

  cards.forEach((card) => {
    const matchesStatus = selectedStatus === "all" || card.dataset.status === selectedStatus;
    const haystack = (card.dataset.search || "").toLowerCase();
    const matchesSearch = !query || haystack.includes(query);
    const visible = matchesStatus && matchesSearch;
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  });

  if (noMatches) {
    noMatches.classList.toggle("hidden", visibleCount !== 0);
  }
}

function applySort() {
  if (!list || !sort) return;
  const sorted = [...cards].sort((a, b) => {
    if (sort.value === "name") {
      return (a.dataset.name || "").localeCompare(b.dataset.name || "");
    }
    if (sort.value === "status") {
      return (a.dataset.status || "").localeCompare(b.dataset.status || "");
    }
    return (b.dataset.updated || "").localeCompare(a.dataset.updated || "");
  });
  sorted.forEach((card) => list.append(card));
}

function syncList() {
  applySort();
  applyFilters();
}

search?.addEventListener("input", applyFilters);
status?.addEventListener("change", applyFilters);
sort?.addEventListener("change", syncList);
clearFilters?.addEventListener("click", () => {
  if (search) search.value = "";
  if (status) status.value = "all";
  syncList();
});
