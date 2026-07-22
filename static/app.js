"use strict";

const TABLE_META = {
  qualities: { title: "品质与权重", file: "data/qualities.jsonl", headers: ["品质 ID", "标签", "显示颜色", "权重", ""], grid: "grid-qualities" },
  specs: { title: "道具规格", file: "data/item_specs.jsonl", headers: ["规格 ID", "宽", "高", ""], grid: "grid-specs" },
  items: { title: "具体道具", file: "data/items.jsonl", headers: ["道具 ID", "名称", "规格", "品质", "价值", "资源点", ""], grid: "grid-items" },
  "value-costs": { title: "价值资源点建议规则", file: "data/value_costs.jsonl", headers: ["价值下限（含）", "价值上限（不含）", "建议资源点", ""], grid: "grid-value-costs" },
  "resource-budgets": { title: "资源预算档位", file: "data/resource_budgets.jsonl", headers: ["档位 ID", "资源点", ""], grid: "grid-resource-budgets" },
};
const QUALITY_COLORS = ["gray", "green", "blue", "purple", "orange", "red"];
const valueFormatter = new Intl.NumberFormat("zh-CN");

const topTabs = [...document.querySelectorAll(".top-tab")];
const tabPanels = [...document.querySelectorAll("[data-tab-panel]")];
const tableChoices = [...document.querySelectorAll(".table-choice")];
const configTable = document.querySelector("#config-table");
const configStatus = document.querySelector("#config-status");
const addRowButton = document.querySelector("#add-row");
const saveTableButton = document.querySelector("#save-table");
const reloadTableButton = document.querySelector("#reload-table");
const applyValueCostsButton = document.querySelector("#apply-value-costs");
const form = document.querySelector("#generator-form");
const saveSettingsButton = document.querySelector("#save-settings");
const settingsStatus = document.querySelector("#settings-status");
const formError = document.querySelector("#form-error");
const generateButton = document.querySelector("#generate-button");
const revealButton = document.querySelector("#reveal-button");
const revealSpeed = document.querySelector("#reveal-speed");
const revealSpeedValue = document.querySelector("#reveal-speed-value");
const previewQualityTags = document.querySelector("#preview-quality-tags");
const previewSpecTags = document.querySelector("#preview-spec-tags");
const board = document.querySelector("#board");
const boardScroll = document.querySelector("#board-scroll");
const emptyState = document.querySelector("#empty-state");
const metrics = document.querySelector("#metrics");
const valueNotice = document.querySelector("#value-notice");
const errorCard = document.querySelector("#error-card");
const statePill = document.querySelector("#generation-state");
const stateText = document.querySelector("#generation-state-text");

let activeTable = "qualities";
let configData = { qualities: [], specs: [], items: [], "value-costs": [], "resource-budgets": [] };
let configDirty = false;
let currentResult = null;
let animationToken = 0;
let displayState = "idle";
const selectedPreviewQualities = new Set();
const selectedPreviewSpecs = new Set();
const previewQualityClasses = QUALITY_COLORS.map((color) => `preview-quality-${color}`);

async function requestJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const details = body.error || {};
    const error = new Error(details.message || `请求失败（HTTP ${response.status}）`);
    error.code = details.code || "request_failed";
    error.suggestions = Array.isArray(details.suggestions) ? details.suggestions : [];
    error.status = response.status;
    throw error;
  }
  return body;
}

function setStatus(element, message, state = "") {
  element.textContent = message;
  element.dataset.state = state;
}

function setState(state, text) {
  statePill.dataset.state = state;
  stateText.textContent = text;
}

function setRevealButton(label, disabled) {
  revealButton.textContent = label;
  revealButton.disabled = disabled;
}

function switchTopTab(tabName) {
  const currentTab = topTabs.find((tab) => tab.classList.contains("is-active"))?.dataset.tab;
  if (currentTab === "config" && tabName !== "config" && configDirty
      && !window.confirm("当前配表有未保存修改，切换后仍会保留，但生成只使用已保存数据。确定继续吗？")) return false;
  for (const tab of topTabs) {
    const selected = tab.dataset.tab === tabName;
    tab.classList.toggle("is-active", selected);
    tab.setAttribute("aria-selected", String(selected));
  }
  for (const panel of tabPanels) panel.hidden = panel.dataset.tabPanel !== tabName;
  return true;
}

function updateCounts() {
  for (const tableName of Object.keys(TABLE_META)) {
    document.querySelector(`[data-count="${tableName}"]`).textContent = String(configData[tableName].length);
  }
}

function makePreviewTag(label, value, selectedSet, options = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `preview-tag${options.color ? " preview-tag-quality" : ""}`;
  button.dataset.tagValue = String(value);
  button.setAttribute("aria-pressed", String(selectedSet.has(value)));
  button.title = options.title || label;
  if (options.color) {
    const dot = document.createElement("span");
    dot.className = "preview-tag-dot";
    dot.style.setProperty("--tag-color", `var(--${options.color})`);
    button.append(dot);
  }
  const text = document.createElement("span");
  text.textContent = label;
  button.append(text);
  button.classList.toggle("is-selected", selectedSet.has(value));
  button.addEventListener("click", () => {
    if (selectedSet.has(value)) selectedSet.delete(value); else selectedSet.add(value);
    button.classList.toggle("is-selected", selectedSet.has(value));
    button.setAttribute("aria-pressed", String(selectedSet.has(value)));
    applyPreviewTags();
  });
  return button;
}

function renderPreviewTagControls() {
  const qualityIds = new Set(configData.qualities.map((quality) => Number(quality.qualityId)));
  const specIds = new Set(configData.specs.map((spec) => Number(spec.specId)));
  for (const value of [...selectedPreviewQualities]) if (!qualityIds.has(value)) selectedPreviewQualities.delete(value);
  for (const value of [...selectedPreviewSpecs]) if (!specIds.has(value)) selectedPreviewSpecs.delete(value);
  previewQualityTags.replaceChildren();
  previewSpecTags.replaceChildren();
  for (const quality of configData.qualities) {
    previewQualityTags.append(makePreviewTag(quality.label, Number(quality.qualityId), selectedPreviewQualities, { color: quality.color, title: `品质 ID ${quality.qualityId}` }));
  }
  for (const spec of configData.specs) {
    previewSpecTags.append(makePreviewTag(`${spec.width}×${spec.height}`, Number(spec.specId), selectedPreviewSpecs, { title: `规格 ID ${spec.specId}` }));
  }
  if (!configData.qualities.length) { const empty = document.createElement("span"); empty.className = "preview-tag-empty"; empty.textContent = "暂无品质"; previewQualityTags.append(empty); }
  if (!configData.specs.length) { const empty = document.createElement("span"); empty.className = "preview-tag-empty"; empty.textContent = "暂无规格"; previewSpecTags.append(empty); }
  applyPreviewTags();
  setPreviewTagsDisabled(displayState === "playing");
}

function clearOverlayPreviewTags(overlay) {
  overlay.classList.remove("is-preview-quality", "is-preview-spec", ...previewQualityClasses);
}

function applyPreviewTags() {
  if (displayState !== "preview" && displayState !== "playing") return;
  for (const overlay of board.querySelectorAll(".item-overlay")) {
    clearOverlayPreviewTags(overlay);
    if (overlay.classList.contains("is-revealed")) continue;
    if (selectedPreviewQualities.has(Number(overlay.dataset.qualityId))) {
      overlay.classList.add("is-preview-quality", `preview-quality-${overlay.dataset.quality}`);
    }
    if (selectedPreviewSpecs.has(Number(overlay.dataset.specId))) overlay.classList.add("is-preview-spec");
  }
}

function nextId(records, field) {
  const used = new Set(records.map((record) => Number(record[field])).filter((value) => Number.isSafeInteger(value)));
  let candidate = 1;
  while (used.has(candidate)) candidate += 1;
  return candidate;
}

function makeInput(field, value, type = "text", options = {}) {
  const input = document.createElement("input");
  input.dataset.field = field;
  input.type = type;
  input.value = value === null || value === undefined ? "" : String(value);
  input.setAttribute("aria-label", options.label || field);
  if (options.min !== undefined) input.min = String(options.min);
  if (options.max !== undefined) input.max = String(options.max);
  if (options.placeholder) input.placeholder = options.placeholder;
  input.addEventListener("input", markConfigDirty);
  return input;
}

function makeSelect(field, value, choices, label) {
  const select = document.createElement("select");
  select.dataset.field = field;
  select.setAttribute("aria-label", label);
  for (const choice of choices) {
    const option = document.createElement("option");
    option.value = String(choice.value);
    option.textContent = choice.label;
    option.selected = String(choice.value) === String(value);
    select.append(option);
  }
  select.addEventListener("change", markConfigDirty);
  return select;
}

function markConfigDirty() {
  configDirty = true;
  setStatus(configStatus, "当前配表有未保存修改");
}

function setConfigBusy(busy) {
  for (const choice of tableChoices) choice.disabled = busy;
  addRowButton.disabled = busy;
  saveTableButton.disabled = busy;
  reloadTableButton.disabled = busy;
  applyValueCostsButton.disabled = busy;
}

function updateValueCostAction() {
  applyValueCostsButton.hidden = activeTable !== "value-costs";
}

function suggestedResourceCost(value) {
  const band = configData["value-costs"].find((entry) => value >= entry.minValue && (entry.maxValueExclusive === null || value < entry.maxValueExclusive));
  if (!band) throw new Error(`价值 ${value} 没有匹配的资源点建议区间`);
  return band.resourceCost;
}

function makeRemoveButton(row) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "remove-row";
  button.textContent = "×";
  button.setAttribute("aria-label", "删除这一行");
  button.addEventListener("click", () => { row.remove(); markConfigDirty(); });
  return button;
}

function renderRecord(record) {
  const row = document.createElement("div");
  row.className = `config-row ${TABLE_META[activeTable].grid}`;
  if (activeTable === "qualities") {
    row.append(
      makeInput("qualityId", record.qualityId, "number", { label: "品质 ID", min: 1 }),
      makeInput("label", record.label, "text", { label: "品质标签" }),
      makeSelect("color", record.color, QUALITY_COLORS.map((color) => ({ value: color, label: color })), "品质显示颜色"),
      makeInput("weight", record.weight, "number", { label: "品质权重", min: 1, max: 1000000 }),
      makeRemoveButton(row),
    );
  } else if (activeTable === "specs") {
    row.append(
      makeInput("specId", record.specId, "number", { label: "规格 ID", min: 1 }),
      makeInput("width", record.width, "number", { label: "规格宽度", min: 1, max: 30 }),
      makeInput("height", record.height, "number", { label: "规格高度", min: 1, max: 30 }),
      makeRemoveButton(row),
    );
  } else if (activeTable === "items") {
    const valueInput = makeInput("value", record.value, "number", { label: "道具价值", min: 0 });
    const resourceInput = makeInput("resourceCost", record.resourceCost, "number", { label: "道具资源点", min: 1 });
    valueInput.addEventListener("change", () => {
      try { resourceInput.value = String(suggestedResourceCost(Number(valueInput.value))); markConfigDirty(); }
      catch (error) { setStatus(configStatus, error.message, "error"); }
    });
    row.append(
      makeInput("itemId", record.itemId, "number", { label: "道具 ID", min: 1 }),
      makeInput("name", record.name, "text", { label: "道具名称" }),
      makeSelect("specId", record.specId, configData.specs.map((spec) => ({ value: spec.specId, label: `${spec.width}×${spec.height} · #${spec.specId}` })), "道具规格"),
      makeSelect("qualityId", record.qualityId, configData.qualities.map((quality) => ({ value: quality.qualityId, label: `${quality.label} · 权重 ${quality.weight}` })), "道具品质"),
      valueInput,
      resourceInput,
      makeRemoveButton(row),
    );
  } else if (activeTable === "value-costs") {
    row.append(
      makeInput("minValue", record.minValue, "number", { label: "价值下限", min: 0 }),
      makeInput("maxValueExclusive", record.maxValueExclusive, "number", { label: "价值上限", min: 1, placeholder: "无上限" }),
      makeInput("resourceCost", record.resourceCost, "number", { label: "单次资源点", min: 1 }),
      makeRemoveButton(row),
    );
  } else {
    row.append(
      makeInput("budgetId", record.budgetId, "number", { label: "档位 ID", min: 1 }),
      makeInput("resourceBudget", record.resourceBudget, "number", { label: "资源点", min: 1 }),
      makeRemoveButton(row),
    );
  }
  return row;
}

function renderTable(records = configData[activeTable]) {
  configTable.replaceChildren();
  const meta = TABLE_META[activeTable];
  const header = document.createElement("div");
  header.className = `config-header ${meta.grid}`;
  for (const label of meta.headers) { const span = document.createElement("span"); span.textContent = label; header.append(span); }
  configTable.append(header);
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "empty-table";
    empty.textContent = "当前配表没有记录，请添加一行。";
    configTable.append(empty);
  } else {
    for (const record of records) configTable.append(renderRecord(record));
  }
}

function selectTable(tableName) {
  if (tableName === activeTable) return;
  if (configDirty && !window.confirm("当前配表有未保存修改，切换后将丢弃。确定继续吗？")) return;
  activeTable = tableName;
  configDirty = false;
  for (const choice of tableChoices) {
    const selected = choice.dataset.table === tableName;
    choice.classList.toggle("is-active", selected);
    if (selected) choice.setAttribute("aria-current", "true"); else choice.removeAttribute("aria-current");
  }
  document.querySelector("#active-table-title").textContent = TABLE_META[tableName].title;
  document.querySelector("#active-table-file").textContent = TABLE_META[tableName].file;
  setStatus(configStatus, "");
  updateValueCostAction();
  renderTable();
}

function readInteger(input, label, minimum = 0) {
  if (input.value.trim() === "") throw new Error(`${label}不能为空`);
  const value = Number(input.value);
  const maximum = input.max === "" ? Number.MAX_SAFE_INTEGER : Number(input.max);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    const range = maximum === Number.MAX_SAFE_INTEGER ? `大于等于 ${minimum}` : `${minimum}–${maximum}`;
    throw new Error(`${label}必须是${range}的安全整数`);
  }
  return value;
}

function collectActiveRecords() {
  return [...configTable.querySelectorAll(".config-row")].map((row, index) => {
    const value = {};
    for (const input of row.querySelectorAll("input, select")) {
      const field = input.dataset.field;
      if (field === "label" || field === "color" || field === "name") {
        const text = input.value.trim();
        if (!text) throw new Error(`第 ${index + 1} 行${input.getAttribute("aria-label")}不能为空`);
        value[field] = text;
      } else if (field === "maxValueExclusive" && input.value.trim() === "") {
        value[field] = null;
      } else {
        value[field] = readInteger(input, `第 ${index + 1} 行${input.getAttribute("aria-label")}`, field === "value" || field === "minValue" ? 0 : 1);
      }
    }
    return value;
  });
}

function addActiveRow() {
  let records;
  try { records = collectActiveRecords(); } catch (error) { setStatus(configStatus, error.message, "error"); return; }
  if (activeTable === "qualities") {
    const usedColors = new Set(records.map((record) => record.color));
    records.push({ qualityId: nextId(records, "qualityId"), label: "新品质", color: QUALITY_COLORS.find((color) => !usedColors.has(color)) || "gray", weight: 1 });
  } else if (activeTable === "specs") {
    records.push({ specId: nextId(records, "specId"), width: 1, height: 1 });
  } else if (activeTable === "items") {
    if (!configData.specs.length || !configData.qualities.length) { setStatus(configStatus, "请先配置并保存至少一条规格和品质", "error"); return; }
    records.push({ itemId: nextId(records, "itemId"), name: "新道具", specId: configData.specs[0].specId, qualityId: configData.qualities[0].qualityId, value: 10000, resourceCost: suggestedResourceCost(10000) });
  } else if (activeTable === "resource-budgets") {
    records.push({ budgetId: nextId(records, "budgetId"), resourceBudget: 1000 });
  } else if (records.length && records[records.length - 1].maxValueExclusive === null) {
    const last = records[records.length - 1];
    const splitPoint = last.minValue + 1;
    records.splice(records.length - 1, 0, { minValue: last.minValue, maxValueExclusive: splitPoint, resourceCost: last.resourceCost });
    last.minValue = splitPoint;
  } else {
    records.push({ minValue: records.length ? records[records.length - 1].maxValueExclusive : 0, maxValueExclusive: null, resourceCost: 1 });
  }
  renderTable(records);
  markConfigDirty();
}

async function saveActiveTable() {
  let records;
  try { records = collectActiveRecords(); } catch (error) { setStatus(configStatus, error.message, "error"); return; }
  const requestedTable = activeTable;
  setConfigBusy(true);
  setStatus(configStatus, "正在保存…");
  try {
    const body = await requestJson(`/api/config/${requestedTable}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ records }) });
    configData[requestedTable] = body.records;
    if (activeTable === requestedTable) configDirty = false;
    updateCounts();
    renderPreviewTagControls();
    if (activeTable === requestedTable) renderTable();
    setStatus(configStatus, `已保存 ${body.count} 条记录`, "success");
  } catch (error) { setStatus(configStatus, error.message, "error"); }
  finally { setConfigBusy(false); }
}

async function reloadActiveTable() {
  if (configDirty && !window.confirm("重新载入会丢弃当前未保存修改。确定继续吗？")) return;
  const requestedTable = activeTable;
  setConfigBusy(true);
  try {
    const body = await requestJson(`/api/config/${requestedTable}`);
    configData[requestedTable] = body.records;
    if (activeTable === requestedTable) configDirty = false;
    updateCounts();
    renderPreviewTagControls();
    if (activeTable === requestedTable) renderTable();
    setStatus(configStatus, "已重新载入", "success");
  } catch (error) { setStatus(configStatus, error.message, "error"); }
  finally { setConfigBusy(false); }
}

async function applyValueCostRules() {
  if (configDirty) { setStatus(configStatus, "请先保存当前价值资源点建议规则", "error"); return; }
  let records;
  try {
    records = configData.items.map((item) => ({ ...item, resourceCost: suggestedResourceCost(Number(item.value)) }));
  } catch (error) { setStatus(configStatus, error.message, "error"); return; }
  setConfigBusy(true);
  setStatus(configStatus, "正在将建议资源点应用到全部道具…");
  try {
    const body = await requestJson("/api/config/items", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ records }) });
    configData.items = body.records;
    updateCounts();
    setStatus(configStatus, `已更新 ${body.count} 个道具的资源点`, "success");
  } catch (error) { setStatus(configStatus, error.message, "error"); }
  finally { setConfigBusy(false); }
}

function updateRevealSpeedLabel() { revealSpeedValue.value = `${Number(revealSpeed.value).toFixed(2)} 秒`; }

function readOptionalInteger(selector, label, minimum) {
  const input = document.querySelector(selector);
  if (!input.value.trim()) return null;
  return readInteger(input, label, minimum);
}

function collectSettings() {
  return {
    boardWidth: readInteger(document.querySelector("#board-width"), "容纳盒宽度", 1),
    targetResourceBudget: readOptionalInteger("#target-resource-budget", "目标资源点", 1),
    seed: readOptionalInteger("#seed", "随机种子", 0),
    revealSpeedSeconds: Number(Number(revealSpeed.value).toFixed(2)),
  };
}

function applySettings(settings) {
  document.querySelector("#board-width").value = String(settings.boardWidth);
  document.querySelector("#target-resource-budget").value = settings.targetResourceBudget === null ? "" : String(settings.targetResourceBudget);
  document.querySelector("#seed").value = settings.seed === null ? "" : String(settings.seed);
  revealSpeed.value = String(settings.revealSpeedSeconds);
  updateRevealSpeedLabel();
}

async function saveDefaultSettings() {
  let settings;
  try { settings = collectSettings(); } catch (error) { setStatus(settingsStatus, error.message, "error"); return; }
  saveSettingsButton.disabled = true;
  setStatus(settingsStatus, "正在保存…");
  try {
    const body = await requestJson("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
    applySettings(body.settings);
    setStatus(settingsStatus, "默认参数已保存", "success");
  } catch (error) { setStatus(settingsStatus, error.message, "error"); }
  finally { saveSettingsButton.disabled = false; }
}

function cancelAnimation() { animationToken += 1; }

function setPreviewTagsDisabled(disabled) {
  for (const button of document.querySelectorAll(".preview-tag")) button.disabled = disabled;
}

async function waitRevealPhase(token, durationShare, onProgress = null) {
  if (onProgress) onProgress(0);
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || Number(revealSpeed.value) <= 0) {
    if (onProgress) onProgress(1);
    return token === animationToken;
  }
  let progress = 0;
  let previousTime = window.performance.now();
  while (progress < 1) {
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    if (token !== animationToken) return false;
    const currentTime = window.performance.now();
    const phaseDuration = Number(revealSpeed.value) * 1000 * durationShare;
    if (phaseDuration <= 0) { if (onProgress) onProgress(1); return true; }
    progress += (currentTime - previousTime) / phaseDuration;
    previousTime = currentTime;
    if (onProgress) onProgress(Math.min(progress, 1));
  }
  return true;
}

function clearPreview() {
  cancelAnimation(); displayState = "idle"; currentResult = null; board.replaceChildren(); boardScroll.hidden = true; emptyState.hidden = false;
  metrics.hidden = true; valueNotice.hidden = true; errorCard.hidden = true; setRevealButton("展示", true); setPreviewTagsDisabled(false);
}

function showServerError(error) {
  displayState = "idle"; currentResult = null; setRevealButton("展示", true); errorCard.hidden = false; metrics.hidden = true; valueNotice.hidden = true;
  document.querySelector("#error-message").textContent = error.message || "生成请求失败";
  const list = document.querySelector("#error-suggestions"); list.replaceChildren();
  for (const suggestion of error.suggestions || []) { const item = document.createElement("li"); item.textContent = suggestion; list.append(item); }
  setState("error", "生成失败");
}

function calculateCellSize(result) {
  const longest = Math.max(result.boardWidth, result.boardHeight);
  if (longest <= 10) return 48; if (longest <= 16) return 38; if (longest <= 24) return 31; if (longest <= 40) return 24; return 19;
}

function occupiedRuns(occupied) {
  const completed = [];
  let active = new Map();
  for (let y = 0; y < occupied.length; y += 1) {
    const next = new Map();
    const row = occupied[y];
    let x = 0;
    while (x < row.length) {
      if (!row[x]) { x += 1; continue; }
      const start = x;
      while (x < row.length && row[x]) x += 1;
      const width = x - start;
      const key = `${start}:${width}`;
      const run = active.get(key) || { x: start, y, width, height: 0 };
      run.height += 1;
      next.set(key, run);
    }
    for (const [key, run] of active) if (!next.has(key)) completed.push(run);
    active = next;
  }
  completed.push(...active.values());
  return completed;
}

function renderBoard(result) {
  board.replaceChildren();
  board.style.setProperty("--cols", result.boardWidth); board.style.setProperty("--rows", result.boardHeight); board.style.setProperty("--cell-size", `${calculateCellSize(result)}px`);
  for (const run of occupiedRuns(result.occupied)) {
    const snapshot = document.createElement("div"); snapshot.className = "snapshot-run"; snapshot.style.gridColumn = `${run.x + 1} / span ${run.width}`; snapshot.style.gridRow = `${run.y + 1} / span ${run.height}`; snapshot.setAttribute("aria-hidden", "true"); board.append(snapshot);
  }
  for (const item of result.items) {
    const overlay = document.createElement("div"); overlay.className = "item-overlay"; overlay.dataset.order = String(item.placementOrder); overlay.dataset.x = String(item.x); overlay.dataset.y = String(item.y); overlay.dataset.quality = item.quality; overlay.dataset.qualityId = String(item.qualityId); overlay.dataset.specId = String(item.specId);
    overlay.setAttribute("aria-hidden", "true");
    overlay.style.gridColumn = `${item.x + 1} / span ${item.width}`; overlay.style.gridRow = `${item.y + 1} / span ${item.height}`;
    overlay.dataset.detailTitle = `${item.name} · 道具 ID ${item.itemId} · ${item.qualityLabel}品质 · 价值 ${valueFormatter.format(item.value)} · 资源点 ${item.resourceCost}`;
    const spinner = document.createElement("span"); spinner.className = "spinner";
    const order = document.createElement("span"); order.className = "reveal-order"; order.textContent = item.uid;
    const content = document.createElement("span"); content.className = "item-content";
    content.setAttribute("aria-hidden", "true");
    const id = document.createElement("span"); id.className = "item-id"; id.textContent = item.itemId;
    const name = document.createElement("span"); name.className = "item-name"; name.textContent = item.name;
    const value = document.createElement("span"); value.className = "item-value"; value.textContent = valueFormatter.format(item.value);
    content.append(id, name, value); overlay.append(spinner, order, content); board.append(overlay);
  }
  displayState = "preview";
  applyPreviewTags();
  document.querySelector("#metric-total-value").textContent = valueFormatter.format(result.totalValue);
  document.querySelector("#metric-average-cell-value").textContent = valueFormatter.format(result.averageValuePerOccupiedCell);
  document.querySelector("#metric-average-item-value").textContent = valueFormatter.format(result.averageItemValue);
  document.querySelector("#metric-median-item-value").textContent = valueFormatter.format(result.medianItemValue);
  document.querySelector("#metric-budget").textContent = valueFormatter.format(result.resourceBudget);
  document.querySelector("#metric-resource").textContent = `${valueFormatter.format(result.resourceConsumed)} / ${valueFormatter.format(result.resourceRemaining)}`;
  document.querySelector("#metric-items").textContent = `${result.itemCount} 件 / ${result.boardHeight} 行`;
  document.querySelector("#metric-seed").textContent = String(result.seed);
  document.querySelector("#metric-config-hash").textContent = result.configHash || "—";
  document.querySelector("#metric-time").textContent = `${result.generatedMs.toFixed(2)} ms`;
  metrics.hidden = false; errorCard.hidden = true; emptyState.hidden = true; boardScroll.hidden = false; setRevealButton("展示", false);
  const budgetText = result.resourceBudgetMode === "configured" ? "使用指定" : "随机抽到";
  valueNotice.classList.toggle("is-warning", result.resourceRemaining > 0 || result.truncated);
  const ending = result.truncated ? "已达到 200 件上限，结果发生截断。" : "";
  valueNotice.textContent = `本局${budgetText} ${valueFormatter.format(result.resourceBudget)} 点预算，抽取 ${result.qualityRollCount} 件，消耗 ${valueFormatter.format(result.resourceConsumed)} 点，剩余 ${valueFormatter.format(result.resourceRemaining)} 点。${ending}`;
  valueNotice.hidden = false;
}

async function playReveal() {
  if (!currentResult) return;
  cancelAnimation(); const token = animationToken;
  displayState = "playing";
  const overlays = [...board.querySelectorAll(".item-overlay")].sort((first, second) => Number(first.dataset.y) - Number(second.dataset.y) || Number(first.dataset.x) - Number(second.dataset.x) || Number(first.dataset.order) - Number(second.dataset.order));
  for (const overlay of overlays) {
    overlay.className = "item-overlay";
    overlay.removeAttribute("title");
    overlay.style.removeProperty("--reveal-quality");
    overlay.style.removeProperty("background");
    overlay.setAttribute("aria-hidden", "true");
    overlay.removeAttribute("tabindex");
    overlay.removeAttribute("aria-label");
    overlay.removeAttribute("role");
    overlay.querySelector(".item-content").setAttribute("aria-hidden", "true");
  }
  applyPreviewTags();
  setState("working", "逐件展示中"); setRevealButton("展示中…", true); setPreviewTagsDisabled(true);
  for (const overlay of overlays) {
    if (token !== animationToken) return;
    const alreadyShowsQuality = overlay.classList.contains("is-preview-quality");
    if (!alreadyShowsQuality) {
      overlay.style.setProperty("--reveal-quality", `var(--${overlay.dataset.quality})`);
      overlay.classList.add("is-quality-transition");
    }
    overlay.classList.add("is-loading");
    const syncQualityTransition = alreadyShowsQuality
      ? null
      : (progress) => {
          const revealed = Math.round(progress * 10000) / 100;
          overlay.style.background = `color-mix(in srgb, var(--occupied-cell) ${100 - revealed}%, var(--reveal-quality) ${revealed}%)`;
        };
    if (!await waitRevealPhase(token, .8, syncQualityTransition)) return;
    clearOverlayPreviewTags(overlay);
    overlay.classList.remove("is-loading", "is-quality-transition"); overlay.classList.add("is-revealed", `quality-${overlay.dataset.quality}`); overlay.title = overlay.dataset.detailTitle;
    overlay.style.removeProperty("--reveal-quality");
    overlay.style.removeProperty("background");
    overlay.removeAttribute("aria-hidden");
    overlay.tabIndex = 0;
    overlay.setAttribute("role", "group");
    overlay.setAttribute("aria-label", overlay.dataset.detailTitle);
    overlay.querySelector(".item-content").setAttribute("aria-hidden", "false");
    if (!await waitRevealPhase(token, .2)) return;
  }
  if (token === animationToken) { displayState = "complete"; setState("success", "展示完成"); setRevealButton("重播", false); setPreviewTagsDisabled(false); }
}

async function generate(event) {
  event.preventDefault(); clearPreview(); formError.hidden = true;
  let settings;
  try { settings = collectSettings(); } catch (error) { formError.textContent = error.message; formError.hidden = false; setState("error", "参数无效"); return; }
  const payload = { boardWidth: settings.boardWidth };
  if (settings.targetResourceBudget !== null) payload.targetResourceBudget = settings.targetResourceBudget;
  if (settings.seed !== null) payload.seed = settings.seed;
  generateButton.disabled = true; generateButton.classList.add("is-busy"); setState("working", "正在读取配表并生成");
  try {
    const body = await requestJson("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    currentResult = body; renderBoard(body); setState("ready", "等待展示");
  } catch (error) { showServerError(error); }
  finally { generateButton.disabled = false; generateButton.classList.remove("is-busy"); }
}

async function initialize() {
  const [configResult, settingsResult] = await Promise.allSettled([requestJson("/api/config"), requestJson("/api/settings")]);
  if (configResult.status === "fulfilled") {
    const configBody = configResult.value;
    configData = { qualities: configBody.qualities, specs: configBody.specs, items: configBody.items, "value-costs": configBody.valueCosts, "resource-budgets": configBody.resourceBudgets };
    updateCounts(); renderTable(); renderPreviewTagControls(); updateValueCostAction();
  } else setStatus(configStatus, configResult.reason.message, "error");
  if (settingsResult.status === "fulfilled") applySettings(settingsResult.value.settings);
  else setStatus(settingsStatus, settingsResult.reason.message, "error");
}

for (const tab of topTabs) {
  tab.addEventListener("click", () => switchTopTab(tab.dataset.tab));
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const index = topTabs.indexOf(tab);
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const next = topTabs[(index + offset + topTabs.length) % topTabs.length];
    if (switchTopTab(next.dataset.tab)) next.focus();
  });
}
for (const choice of tableChoices) choice.addEventListener("click", () => selectTable(choice.dataset.table));
addRowButton.addEventListener("click", addActiveRow);
saveTableButton.addEventListener("click", saveActiveTable);
reloadTableButton.addEventListener("click", reloadActiveTable);
applyValueCostsButton.addEventListener("click", applyValueCostRules);
saveSettingsButton.addEventListener("click", saveDefaultSettings);
form.addEventListener("submit", generate);
revealButton.addEventListener("click", playReveal);
revealSpeed.addEventListener("input", updateRevealSpeedLabel);
window.addEventListener("beforeunload", (event) => { if (configDirty) { event.preventDefault(); event.returnValue = ""; } });
updateRevealSpeedLabel();
initialize();
