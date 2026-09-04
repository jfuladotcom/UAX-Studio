import { axFetch, notify, setSaveStatus } from "./app.js";

const app = document.querySelector(".workflow-app");
const canvas = document.querySelector("#workflow-canvas");
const nodeLayer = document.querySelector("#workflow-nodes");
const edgeSvg = document.querySelector("#workflow-edges");
const nodeForm = document.querySelector("#node-form");
const inspectorEmpty = document.querySelector("#inspector-empty");
const nodeTable = document.querySelector("#node-table-body");
const edgeTable = document.querySelector("#edge-table-body");
const connectModeButton = document.querySelector("#connect-mode");
const disconnectModeButton = document.querySelector("#disconnect-mode");
const panelTabs = document.querySelectorAll("[data-panel-tab]");
const panelContents = document.querySelectorAll("[data-panel-content]");
const drawer = document.querySelector(".workflow-drawer");
const canvasWrap = document.querySelector(".workflow-canvas-wrap");
const addNodeButton = document.querySelector("#add-node");
const addNodeLabel = document.querySelector("#add-node-label");
const nodeTypeSelect = document.querySelector("#node-type");
const nodeAddControl = document.querySelector("[data-node-add-control]");
const nodeTypeMenu = document.querySelector("#node-type-menu");
const nodeTypeOptions = document.querySelectorAll("[data-node-type]");
const zoomSlider = document.querySelector("#workflow-zoom");
const zoomOutput = document.querySelector("#workflow-zoom-value");
const viewButtons = document.querySelectorAll("[data-workflow-view]");

const WORKFLOW_VIEWS = ["graph", "connections", "sequence"];
const VIEW_ALIASES = {
  list: "sequence",
  "build-sequence": "sequence",
};
const NODE_WIDTH = 240;
const NODE_HEIGHT = 92;
const MIN_ZOOM = 0.45;
const MAX_ZOOM = 1.8;
const WHEEL_ZOOM_SENSITIVITY = 0.0015;
const MINT = "#68e0ad";
const TEXT_MUTED = "#a3a3a3";
const TEXT = "#f5f5f5";

let state = app ? JSON.parse(app.dataset.workflow) : { nodes: [], edges: [] };
let selectedId = null;
let connectSourceId = null;
let disconnectSourceId = null;
let connectPointer = null;
const storedZoom = Number(state.viewport?.zoom);
let zoom = Number.isFinite(storedZoom) ? Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, storedZoom)) : 1;
let dragging = null;
let panning = null;
let restoredViewport = false;

function nodeById(id) {
  return state.nodes.find((node) => node.id === id);
}

function edgesBetween(sourceId, targetId) {
  return state.edges.filter(
    (edge) =>
      (edge.source_node_id === sourceId && edge.target_node_id === targetId) ||
      (edge.source_node_id === targetId && edge.target_node_id === sourceId)
  );
}

function hasConnectionBetween(sourceId, targetId) {
  return edgesBetween(sourceId, targetId).length > 0;
}

function edgeUrl(id) {
  return `/api/workflow-edges/${id}`;
}

function nodeUrl(id) {
  return `/api/workflow-nodes/${id}`;
}

function viewportWrap() {
  return canvasWrap || canvas?.parentElement;
}

function clampZoom(value) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function setZoom(value) {
  zoom = clampZoom(value);
  render();
}

function nodeTypeLabel(type) {
  const option = Array.from(nodeTypeSelect?.options || []).find((item) => item.value === type);
  return option?.textContent.trim() || type.replaceAll("_", " ");
}

function selectedNodeType() {
  return nodeTypeSelect?.value || nodeTypeOptions[0]?.dataset.nodeType || "task";
}

function setSelectedNodeType(type) {
  if (!type) return;
  if (nodeTypeSelect) nodeTypeSelect.value = type;
  nodeTypeOptions.forEach((option) => {
    const selected = option.dataset.nodeType === type;
    option.classList.toggle("selected", selected);
  });
}

function isAddMenuOpen() {
  return Boolean(nodeTypeMenu?.classList.contains("open"));
}

function setAddMenuOpen(open) {
  nodeTypeMenu?.classList.toggle("open", open);
  nodeTypeMenu?.setAttribute("aria-hidden", String(!open));
  addNodeButton?.setAttribute("aria-expanded", String(open));
  if (addNodeLabel) addNodeLabel.textContent = open ? "Close" : "Add Step";
  nodeTypeOptions.forEach((option) => {
    option.tabIndex = open ? 0 : -1;
  });
}

function switchPanel(name) {
  panelTabs.forEach((tab) => {
    const active = tab.dataset.panelTab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  panelContents.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.panelContent !== name);
  });
}

function openDrawer(name = "inspector") {
  app?.classList.add("drawer-open");
  switchPanel(name);
  drawer?.setAttribute("aria-hidden", "false");
  drawer?.removeAttribute("inert");
}

function closeDrawer() {
  app?.classList.remove("drawer-open");
  drawer?.setAttribute("aria-hidden", "true");
  drawer?.setAttribute("inert", "");
}

function applyZoom() {
  if (canvas) canvas.style.transform = `scale(${zoom})`;
  const percentage = Math.round(zoom * 100);
  if (zoomSlider) zoomSlider.value = String(percentage);
  if (zoomOutput) zoomOutput.textContent = `${percentage}%`;
}

function restoreViewport() {
  const wrap = viewportWrap();
  if (!wrap || restoredViewport) return;
  restoredViewport = true;
  window.requestAnimationFrame(() => {
    const panX = Number(state.viewport?.pan_x);
    const panY = Number(state.viewport?.pan_y);
    wrap.scrollLeft = Number.isFinite(panX) ? Math.max(0, panX) : 0;
    wrap.scrollTop = Number.isFinite(panY) ? Math.max(0, panY) : 0;
  });
}

function centerNode(node) {
  const wrap = viewportWrap();
  if (!wrap || !node) return;
  window.requestAnimationFrame(() => {
    wrap.scrollLeft = Math.max(0, (node.position_x + NODE_WIDTH / 2) * zoom - wrap.clientWidth / 2);
    wrap.scrollTop = Math.max(0, (node.position_y + NODE_HEIGHT / 2) * zoom - wrap.clientHeight / 2);
    nodeLayer?.querySelector(`[data-node-id="${window.CSS?.escape ? CSS.escape(node.id) : node.id}"]`)?.focus();
  });
}

function worldPoint(event) {
  const wrap = viewportWrap();
  const rect = wrap.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left + wrap.scrollLeft) / zoom,
    y: (event.clientY - rect.top + wrap.scrollTop) / zoom,
  };
}

function render() {
  if (!app) return;
  applyZoom();
  syncModeUi();
  renderEdges();
  renderNodes();
  renderTables();
}

function normalizeWorkflowView(view) {
  const normalized = VIEW_ALIASES[view] || view;
  return WORKFLOW_VIEWS.includes(normalized) ? normalized : "graph";
}

function setWorkflowView(view) {
  if (!app) return;
  const nextView = normalizeWorkflowView(view);
  app.dataset.activeView = nextView;
  viewButtons.forEach((button) => {
    const active = normalizeWorkflowView(button.dataset.workflowView) === nextView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    if (button.getAttribute("role") === "tab") {
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
  });
  document.querySelectorAll("[data-workflow-view-panel]").forEach((panel) => {
    const active = normalizeWorkflowView(panel.dataset.workflowViewPanel) === nextView;
    panel.hidden = !active;
  });
  if (nextView !== "graph") {
    closeDrawer();
  }
}

function createArrowMarker(id, fill) {
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", id);
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "7");
  marker.setAttribute("markerHeight", "7");
  marker.setAttribute("orient", "auto-start-reverse");
  const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path");
  arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  arrow.setAttribute("fill", fill);
  marker.append(arrow);
  return marker;
}

function renderEdges() {
  if (!edgeSvg) return;
  edgeSvg.textContent = "";
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.append(createArrowMarker("arrow", MINT));
  defs.append(createArrowMarker("arrow-preview", MINT));
  defs.append(createArrowMarker("arrow-disconnect", TEXT));
  edgeSvg.append(defs);

  state.edges.forEach((edge) => {
    const source = nodeById(edge.source_node_id);
    const target = nodeById(edge.target_node_id);
    if (!source || !target) return;

    const startX = source.position_x + NODE_WIDTH;
    const startY = source.position_y + NODE_HEIGHT / 2;
    const endX = target.position_x;
    const endY = target.position_y + NODE_HEIGHT / 2;
    const midX = Math.max(startX + 70, (startX + endX) / 2);
    const disconnectCandidate =
      disconnectSourceId &&
      (edge.source_node_id === disconnectSourceId || edge.target_node_id === disconnectSourceId);

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    if (disconnectCandidate) path.classList.add("disconnect-candidate-edge");
    path.setAttribute("d", `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", MINT);
    path.setAttribute("stroke-width", edge.is_default ? "3" : "2");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("marker-end", disconnectCandidate ? "url(#arrow-disconnect)" : "url(#arrow)");
    edgeSvg.append(path);

    if (edge.condition_label) {
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", String((startX + endX) / 2));
      text.setAttribute("y", String((startY + endY) / 2 - 10));
      text.setAttribute("fill", TEXT_MUTED);
      text.setAttribute("font-size", "14");
      text.textContent = edge.condition_label;
      edgeSvg.append(text);
    }
  });

  renderConnectionPreview();
}

function renderConnectionPreview() {
  if (!connectSourceId || !connectPointer) return;
  const source = nodeById(connectSourceId);
  if (!source) return;

  const startX = source.position_x + NODE_WIDTH;
  const startY = source.position_y + NODE_HEIGHT / 2;
  const endX = connectPointer.x;
  const endY = connectPointer.y;
  const midX = Math.max(startX + 70, (startX + endX) / 2);

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.classList.add("connection-preview-edge");
  path.setAttribute("d", `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("marker-end", "url(#arrow-preview)");
  edgeSvg.append(path);
}

function renderNodes() {
  if (!nodeLayer) return;
  nodeLayer.textContent = "";
  state.nodes.forEach((node) => {
    const button = document.createElement("button");
    const selected = node.id === selectedId;
    button.type = "button";
    button.className = `workflow-node node-type-${node.node_type}`;
    if (selected) button.classList.add("selected");
    if (node.id === connectSourceId) {
      button.classList.add("connect-source");
    } else if (connectSourceId) {
      button.classList.add("connect-target");
    }
    if (node.id === disconnectSourceId) {
      button.classList.add("disconnect-source");
    } else if (disconnectSourceId && hasConnectionBetween(disconnectSourceId, node.id)) {
      button.classList.add("disconnect-target");
    }
    button.style.left = `${node.position_x}px`;
    button.style.top = `${node.position_y}px`;
    button.dataset.nodeId = node.id;
    button.setAttribute("aria-label", `${node.label}, ${node.node_type}`);
    button.setAttribute("aria-pressed", String(selected));

    const type = document.createElement("span");
    type.className = "node-type-label";
    type.textContent = node.node_type.replaceAll("_", " ");
    const title = document.createElement("strong");
    title.textContent = node.label;
    const meta = document.createElement("span");
    meta.textContent = node.actor || "Actor unset";
    button.append(type, title, meta);

    button.addEventListener("click", () => handleNodeClick(node.id));
    button.addEventListener("keydown", (event) => handleNodeKey(event, node.id));
    button.addEventListener("pointerdown", (event) => startDrag(event, node.id));
    nodeLayer.append(button);
  });
}

async function handleNodeClick(id) {
  if (connectSourceId) {
    if (connectSourceId === id) {
      selectNode(id);
      notify("Click another step to finish the connection, or cancel connect mode.");
      return;
    }
    const sourceId = connectSourceId;
    const created = await createEdge(sourceId, id);
    if (created) stopConnectMode();
    return;
  }
  if (disconnectSourceId) {
    if (disconnectSourceId === id) {
      selectNode(id);
      notify("Click a connected step to disconnect it, or cancel disconnect mode.");
      return;
    }
    const disconnected = await disconnectNodes(disconnectSourceId, id);
    if (disconnected) stopDisconnectMode();
    return;
  }
  selectNode(id);
}

function handleNodeKey(event, id) {
  const node = nodeById(id);
  if (!node) return;
  const delta = event.shiftKey ? 50 : 20;
  const moves = {
    ArrowLeft: [-delta, 0],
    ArrowRight: [delta, 0],
    ArrowUp: [0, -delta],
    ArrowDown: [0, delta],
  };
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    handleNodeClick(id);
    return;
  }
  if (moves[event.key]) {
    event.preventDefault();
    node.position_x = Math.max(0, node.position_x + moves[event.key][0]);
    node.position_y = Math.max(0, node.position_y + moves[event.key][1]);
    patchNodePosition(node);
    render();
  }
}

function startDrag(event, id) {
  if (event.button !== 0) return;
  if (connectSourceId || disconnectSourceId) return;
  const node = nodeById(id);
  if (!node) return;
  const point = worldPoint(event);
  dragging = {
    id,
    startX: point.x,
    startY: point.y,
    originalX: node.position_x,
    originalY: node.position_y,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
}

document.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const node = nodeById(dragging.id);
  const point = worldPoint(event);
  node.position_x = Math.max(0, dragging.originalX + point.x - dragging.startX);
  node.position_y = Math.max(0, dragging.originalY + point.y - dragging.startY);
  render();
});

document.addEventListener("pointerup", async () => {
  if (!dragging) return;
  const node = nodeById(dragging.id);
  dragging = null;
  await patchNodePosition(node);
});

function startCanvasPan(event) {
  if (event.button !== 0) return;
  if (dragging || connectSourceId || disconnectSourceId) return;
  if (event.target.closest(".workflow-node")) return;
  const wrap = viewportWrap();
  if (!wrap) return;
  panning = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: wrap.scrollLeft,
    scrollTop: wrap.scrollTop,
  };
  wrap.classList.add("is-panning");
  wrap.setPointerCapture?.(event.pointerId);
  event.preventDefault();
}

function moveCanvasPan(event) {
  if (!panning || event.pointerId !== panning.pointerId) return;
  const wrap = viewportWrap();
  if (!wrap) return;
  wrap.scrollLeft = panning.scrollLeft - (event.clientX - panning.startX);
  wrap.scrollTop = panning.scrollTop - (event.clientY - panning.startY);
  event.preventDefault();
}

function stopCanvasPan(event) {
  if (!panning) return;
  if (event && event.pointerId !== panning.pointerId) return;
  const wrap = viewportWrap();
  wrap?.classList.remove("is-panning");
  panning = null;
}

function zoomCanvasWithWheel(event) {
  const wrap = viewportWrap();
  if (!wrap || panning) return;
  const wheelDelta = event.deltaY || event.deltaX;
  if (!wheelDelta) return;
  event.preventDefault();

  const rect = wrap.getBoundingClientRect();
  const before = worldPoint(event);
  const nextZoom = clampZoom(zoom * Math.exp(-wheelDelta * WHEEL_ZOOM_SENSITIVITY));
  if (nextZoom === zoom) return;

  zoom = nextZoom;
  render();
  wrap.scrollLeft = Math.max(0, before.x * zoom - (event.clientX - rect.left));
  wrap.scrollTop = Math.max(0, before.y * zoom - (event.clientY - rect.top));
}

async function patchNodePosition(node) {
  if (!node) return;
  setSaveStatus("Saving position");
  try {
    await axFetch(nodeUrl(node.id), {
      method: "PATCH",
      json: { position_x: node.position_x, position_y: node.position_y },
    });
    setSaveStatus("Saved locally");
  } catch (error) {
    notify(error.message, "error");
    setSaveStatus("Save error");
  }
}

function defaultConnectPointer(source) {
  return {
    x: source.position_x + NODE_WIDTH + 140,
    y: source.position_y + NODE_HEIGHT / 2,
  };
}

function startConnectMode(sourceId) {
  const source = nodeById(sourceId);
  if (!source) return;
  disconnectSourceId = null;
  selectedId = sourceId;
  connectSourceId = sourceId;
  connectPointer = defaultConnectPointer(source);
  syncModeUi();
  notify("Connection mode on. Click a target step to connect it.");
  render();
}

function stopConnectMode(message = "") {
  connectSourceId = null;
  connectPointer = null;
  syncModeUi();
  if (message) notify(message);
  render();
}

function startDisconnectMode(sourceId) {
  const source = nodeById(sourceId);
  if (!source) return;
  connectSourceId = null;
  connectPointer = null;
  selectedId = sourceId;
  disconnectSourceId = sourceId;
  syncModeUi();
  notify("Disconnect mode on. Click a connected step to remove the connection.");
  render();
}

function stopDisconnectMode(message = "") {
  disconnectSourceId = null;
  syncModeUi();
  if (message) notify(message);
  render();
}

function syncModeUi() {
  const connecting = Boolean(connectSourceId);
  const disconnecting = Boolean(disconnectSourceId);
  app?.classList.toggle("connection-mode", connecting);
  app?.classList.toggle("disconnect-mode", disconnecting);
  if (connectModeButton) {
    connectModeButton.classList.toggle("primary", connecting);
    connectModeButton.textContent = connecting ? "Cancel Connect" : "Connect";
    connectModeButton.setAttribute("aria-pressed", String(connecting));
    connectModeButton.title = connecting
      ? "Turn off connection mode."
      : "Select a step, then click Connect.";
  }
  if (disconnectModeButton) {
    disconnectModeButton.classList.toggle("active", disconnecting);
    disconnectModeButton.textContent = disconnecting ? "Cancel Disconnect" : "Disconnect";
    disconnectModeButton.setAttribute("aria-pressed", String(disconnecting));
    disconnectModeButton.title = disconnecting
      ? "Turn off disconnect mode."
      : "Select a step, then click Disconnect.";
  }
}

function selectNode(id) {
  selectedId = id;
  const node = nodeById(id);
  inspectorEmpty?.classList.toggle("hidden", Boolean(node));
  nodeForm?.classList.toggle("hidden", !node);
  if (node && nodeForm) {
    openDrawer("inspector");
    for (const field of nodeForm.elements) {
      if (!field.name) continue;
      field.value = node[field.name] ?? "";
    }
  }
  render();
}

function focusRequestedNode(id) {
  const node = nodeById(id);
  if (!node) return false;
  setWorkflowView("graph");
  selectNode(id);
  centerNode(node);
  return true;
}

function renderTables() {
  if (nodeTable) {
    nodeTable.textContent = "";
    state.nodes.forEach((node) => {
      const row = document.createElement("tr");
      [node.label, node.node_type, node.actor, node.description].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value || "";
        row.append(cell);
      });
      row.className = "workflow-list-row";
      row.tabIndex = 0;
      row.setAttribute("aria-label", `Edit ${node.label || "workflow step"}`);
      row.addEventListener("click", () => {
        setWorkflowView("graph");
        selectNode(node.id);
      });
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        setWorkflowView("graph");
        selectNode(node.id);
      });
      nodeTable.append(row);
    });
  }

  if (!edgeTable) return;
  edgeTable.textContent = "";
  state.edges.forEach((edge) => {
    const row = document.createElement("tr");
    const source = document.createElement("td");
    source.textContent = nodeById(edge.source_node_id)?.label || "Missing step";
    const condition = document.createElement("td");
    const conditionInput = document.createElement("input");
    conditionInput.value = edge.condition_label;
    condition.append(conditionInput);
    const target = document.createElement("td");
    target.textContent = nodeById(edge.target_node_id)?.label || "Missing step";
    const defaultCell = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = edge.is_default;
    defaultCell.append(checkbox);
    const actions = document.createElement("td");
    const save = document.createElement("button");
    save.className = "button small";
    save.type = "button";
    save.textContent = "Save";
    save.addEventListener("click", async () => {
      try {
        const response = await axFetch(edgeUrl(edge.id), {
          method: "PATCH",
          json: { condition_label: conditionInput.value, is_default: checkbox.checked },
        });
        Object.assign(edge, response.data.edge);
        notify("Connection saved.");
        render();
      } catch (error) {
        notify(error.message, "error");
      }
    });
    const remove = document.createElement("button");
    remove.className = "button small";
    remove.type = "button";
    remove.textContent = "Disconnect";
    remove.addEventListener("click", async () => {
      if (!window.confirm("Disconnect this connection?")) return;
      await disconnectEdges([edge], "Connection disconnected.");
    });
    actions.append(save, document.createTextNode(" "), remove);
    row.append(source, condition, target, defaultCell, actions);
    edgeTable.append(row);
  });
}

async function createEdge(sourceId, targetId) {
  try {
    const response = await axFetch(`/api/workflows/${state.id}/edges`, {
      method: "POST",
      json: {
        source_node_id: sourceId,
        target_node_id: targetId,
        condition_label: document.querySelector("#edge-label")?.value || "Next",
        is_default: state.edges.filter((edge) => edge.source_node_id === sourceId).length === 0,
      },
    });
    state.edges.push(response.data.edge);
    notify("Connection created.");
    render();
    return true;
  } catch (error) {
    notify(error.message, "error");
    return false;
  }
}

async function disconnectEdges(edges, message) {
  if (!edges.length) return false;
  setSaveStatus("Saving connection");
  try {
    await Promise.all(edges.map((edge) => axFetch(edgeUrl(edge.id), { method: "DELETE" })));
    const removedIds = new Set(edges.map((edge) => edge.id));
    state.edges = state.edges.filter((edge) => !removedIds.has(edge.id));
    notify(message);
    setSaveStatus("Saved locally");
    render();
    return true;
  } catch (error) {
    notify(error.message, "error");
    setSaveStatus("Save error");
    return false;
  }
}

async function disconnectNodes(sourceId, targetId) {
  const edges = edgesBetween(sourceId, targetId);
  if (!edges.length) {
    notify("No direct connection found between those steps.", "error");
    return false;
  }
  const source = nodeById(sourceId);
  const target = nodeById(targetId);
  const message =
    edges.length === 1
      ? `Disconnect ${source?.label || "these steps"} and ${target?.label || "that step"}?`
      : `Disconnect ${edges.length} connections between these steps?`;
  if (!window.confirm(message)) return false;
  return disconnectEdges(
    edges,
    edges.length === 1 ? "Connection disconnected." : "Connections disconnected."
  );
}

function newNodePosition() {
  const stagger = state.nodes.length % 8;
  const wrap = viewportWrap();
  if (!wrap) {
    return {
      position_x: 160 + state.nodes.length * 36,
      position_y: 130 + state.nodes.length * 28,
    };
  }
  const visibleLeft = wrap.scrollLeft / zoom;
  const visibleTop = wrap.scrollTop / zoom;
  const visibleInsetX = Math.min(wrap.clientWidth / zoom * 0.25, 260);
  const visibleInsetY = Math.min(wrap.clientHeight / zoom * 0.25, 220);
  return {
    position_x: Math.max(40, Math.round(visibleLeft + visibleInsetX + stagger * 32)),
    position_y: Math.max(40, Math.round(visibleTop + visibleInsetY + stagger * 28)),
  };
}

async function addWorkflowNode(type = selectedNodeType()) {
  setSelectedNodeType(type);
  const position = newNodePosition();
  try {
    const response = await axFetch(`/api/workflows/${state.id}/nodes`, {
      method: "POST",
      json: {
        node_type: type,
        position_x: position.position_x,
        position_y: position.position_y,
      },
    });
    state.nodes.push(response.data.node);
    selectNode(response.data.node.id);
    notify(`${nodeTypeLabel(type)} step added.`);
  } catch (error) {
    notify(error.message, "error");
  }
}

nodeForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const node = nodeById(selectedId);
  if (!node) return;
  const formData = new FormData(nodeForm);
  const payload = Object.fromEntries(formData.entries());
  try {
    const response = await axFetch(nodeUrl(node.id), { method: "PATCH", json: payload });
    Object.assign(node, response.data.node);
    notify("Step saved.");
    render();
  } catch (error) {
    notify(error.message, "error");
  }
});

document.querySelector("#delete-node")?.addEventListener("click", async () => {
  const node = nodeById(selectedId);
  if (!node || !window.confirm("Delete this step and its connections?")) return;
  try {
    await axFetch(nodeUrl(node.id), { method: "DELETE" });
    state.nodes = state.nodes.filter((item) => item.id !== node.id);
    state.edges = state.edges.filter((edge) => edge.source_node_id !== node.id && edge.target_node_id !== node.id);
    if (connectSourceId === node.id) {
      connectSourceId = null;
      connectPointer = null;
    }
    if (disconnectSourceId === node.id) disconnectSourceId = null;
    syncModeUi();
    selectedId = null;
    inspectorEmpty?.classList.remove("hidden");
    nodeForm?.classList.add("hidden");
    closeDrawer();
    notify("Step deleted.");
    render();
  } catch (error) {
    notify(error.message, "error");
  }
});

addNodeButton?.addEventListener("click", (event) => {
  event.preventDefault();
  const open = !isAddMenuOpen();
  setAddMenuOpen(open);
  if (open) {
    const selected = Array.from(nodeTypeOptions).find((option) => option.dataset.nodeType === selectedNodeType());
    selected?.focus();
  }
});

nodeTypeSelect?.addEventListener("change", () => {
  setSelectedNodeType(nodeTypeSelect.value);
});

nodeTypeOptions.forEach((option) => {
  option.addEventListener("click", async (event) => {
    event.preventDefault();
    await addWorkflowNode(option.dataset.nodeType);
    setAddMenuOpen(true);
  });
});

nodeTypeMenu?.addEventListener("keydown", (event) => {
  const options = Array.from(nodeTypeOptions);
  if (!options.length) return;
  const currentIndex = Math.max(0, options.indexOf(document.activeElement));
  if (event.key === "ArrowDown" || event.key === "ArrowRight") {
    event.preventDefault();
    options[(currentIndex + 1) % options.length]?.focus();
  }
  if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
    event.preventDefault();
    options[(currentIndex - 1 + options.length) % options.length]?.focus();
  }
});

document.addEventListener("click", (event) => {
  if (!isAddMenuOpen()) return;
  if (!nodeAddControl?.contains(event.target)) setAddMenuOpen(false);
});

connectModeButton?.addEventListener("click", (event) => {
  event.preventDefault();
  if (connectSourceId) {
    stopConnectMode("Connect mode off.");
    return;
  }
  if (!selectedId) {
    notify("Select a step, then click Connect.");
    return;
  }
  startConnectMode(selectedId);
});

disconnectModeButton?.addEventListener("click", (event) => {
  event.preventDefault();
  if (disconnectSourceId) {
    stopDisconnectMode("Disconnect mode off.");
    return;
  }
  if (!selectedId) {
    notify("Select a step, then click Disconnect.");
    return;
  }
  startDisconnectMode(selectedId);
});

canvas?.addEventListener("pointermove", (event) => {
  if (!connectSourceId) return;
  connectPointer = worldPoint(event);
  renderEdges();
});

canvasWrap?.addEventListener("pointerdown", startCanvasPan);
canvasWrap?.addEventListener("pointermove", moveCanvasPan);
canvasWrap?.addEventListener("pointerup", stopCanvasPan);
canvasWrap?.addEventListener("pointercancel", stopCanvasPan);
canvasWrap?.addEventListener("lostpointercapture", stopCanvasPan);
canvasWrap?.addEventListener("wheel", zoomCanvasWithWheel, { passive: false });

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (isAddMenuOpen()) {
    event.preventDefault();
    setAddMenuOpen(false);
    addNodeButton?.focus();
    return;
  }
  if (!connectSourceId && !disconnectSourceId) return;
  event.preventDefault();
  if (connectSourceId) {
    stopConnectMode("Connect mode off.");
    return;
  }
  if (disconnectSourceId) stopDisconnectMode("Disconnect mode off.");
});

document.querySelector("#close-workflow-panel")?.addEventListener("click", () => {
  window.history.replaceState(null, "", window.location.pathname);
  closeDrawer();
});

panelTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    window.history.replaceState(null, "", `#${tab.dataset.panelTab}`);
    setWorkflowView("graph");
    openDrawer(tab.dataset.panelTab);
  });
});

viewButtons.forEach((button) => {
  button.addEventListener("click", () => setWorkflowView(button.dataset.workflowView));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = Array.from(viewButtons).filter((candidate) => candidate.getAttribute("role") === "tab");
    const index = tabs.indexOf(button);
    if (index === -1) return;
    event.preventDefault();
    let nextIndex = index;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    tabs[nextIndex]?.focus();
    setWorkflowView(tabs[nextIndex]?.dataset.workflowView);
  });
});

zoomSlider?.addEventListener("input", () => {
  setZoom(Number(zoomSlider.value) / 100);
});

function fitWorkflow() {
  if (!state.nodes.length) return;
  const wrap = viewportWrap();
  if (!wrap) return;
  const minX = Math.min(...state.nodes.map((node) => node.position_x));
  const minY = Math.min(...state.nodes.map((node) => node.position_y));
  const maxX = Math.max(...state.nodes.map((node) => node.position_x + NODE_WIDTH));
  const maxY = Math.max(...state.nodes.map((node) => node.position_y + NODE_HEIGHT));
  setZoom(Math.min(1.15, wrap.clientWidth / Math.max(500, maxX - minX + 120)));
  wrap.scrollLeft = Math.max(0, minX * zoom - 50);
  wrap.scrollTop = Math.max(0, minY * zoom - 50);
}

document.querySelector("#fit-workflow")?.addEventListener("click", fitWorkflow);

const queryParams = new URLSearchParams(window.location.search);
const requestedPanel = queryParams.get("panel") || app?.dataset.initialPanel;
const requestedNodeId = queryParams.get("node") || app?.dataset.focusNodeId;
setWorkflowView(app?.dataset.activeView || "graph");
if (window.location.hash === "#sources" || requestedPanel === "sources") {
  setWorkflowView("graph");
  openDrawer("sources");
} else if (window.location.hash === "#inspector" || requestedPanel === "inspector") {
  setWorkflowView("graph");
  openDrawer("inspector");
} else {
  closeDrawer();
}
setSelectedNodeType(selectedNodeType());
setAddMenuOpen(false);
render();
if (!focusRequestedNode(requestedNodeId)) {
  restoreViewport();
}
