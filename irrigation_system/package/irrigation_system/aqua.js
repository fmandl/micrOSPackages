const state = {
  data: null,
  statusAt: 0,
  busy: false,
  configDirty: false,
  settingsAt: 0,
  blocked: null,   // transient reason when a start/resume was rejected (e.g. low_water)
  countdown: null, // {remaining, at} client-side 1s countdown, seeded from status
};

const configFields = {
  tankWidthInput: "tank_width_cm",
  tankDepthInput: "tank_depth_cm",
  tankHeightInput: "tank_height_cm",
  waterDistanceInput: "water_distance_cm",
  minLevelInput: "min_level_cm",
  pumpFlowInput: "pump_l_hour",
  soilSensorCountInput: "soil_sensor_count",
  levelModuleInput: "level_module",
  pumpPinInput: "pump_pin",
};

const REST_TIMEOUT_MS = 10000;
const SETTINGS_SYNC_MS = 30000;
const SETTINGS_PATH = "/aqua/settings";

function restValue(value) {
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "string") return encodeURIComponent(JSON.stringify(value));
  return null;
}

function restParams(params = {}) {
  return Object.entries(params)
    .filter(([, value]) => value !== null && value !== "" && typeof value !== "undefined")
    .map(([key, value]) => {
      const encoded = restValue(value);
      return encoded === null ? null : `${key}=${encoded}`;
    })
    .filter(Boolean);
}

function aquaCommandText(command, params = {}) {
  return ["aqua", command, ...restParams(params)].join(" ");
}

async function aquaCommand(command, params = {}, timeout = REST_TIMEOUT_MS) {
  if (typeof restAPI !== "function") {
    throw new Error("uapi.js is not loaded");
  }
  const response = await restAPI(aquaCommandText(command, params), false, timeout);
  if (!response || response.state !== true) {
    throw new Error(response?.result || "Aqua REST command failed");
  }
  return response.result;
}

async function requestJson(path, options = { cache: "no-store" }) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error("request " + response.status);
  const data = await response.json();
  if (data?.state === false) throw new Error(data.error || "request failed");
  return data;
}

async function requestSettings() {
  return requestJson(SETTINGS_PATH);
}

async function saveSettings(config) {
  return requestJson(SETTINGS_PATH, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ config }),
  });
}

async function syncSettings(data) {
  if (state.configDirty || Date.now() - state.settingsAt < SETTINGS_SYNC_MS) return data;
  try {
    const settings = await requestSettings();
    state.settingsAt = Date.now();
    if (settings?.config) data.config = settings.config;
  } catch (err) {
    console.warn("Settings sync failed:", err);
  }
  return data;
}

function byId(id) {
  return document.getElementById(id);
}

function numberValue(id) {
  const value = byId(id)?.value;
  if (value === "" || value === null || typeof value === "undefined") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function textValue(id) {
  const value = byId(id)?.value;
  return value && value.trim() ? value.trim() : null;
}

function setText(id, value) {
  const el = byId(id);
  if (el) el.textContent = value;
}

function setMessage(message, type = "neutral") {
  const el = byId("messageLine");
  if (!el) return;
  el.textContent = message;
  el.dataset.type = type;
}

function trimDecimalZeros(value) {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

function fmt(value, suffix = "", digits = 1) {
  if (value === null || typeof value === "undefined" || Number.isNaN(Number(value))) {
    return "--" + suffix;
  }
  const n = Number(value);
  const fixed = Number.isInteger(n) ? String(n) : n.toFixed(digits);
  return trimDecimalZeros(fixed) + suffix;
}

function clampCount(value, minimum = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return minimum;
  return Math.max(minimum, Math.min(100, Math.trunc(parsed)));
}

function clampPercent(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : null;
}

function inputText(value, digits = 3) {
  if (value === null || typeof value === "undefined" || Number.isNaN(Number(value))) return "";
  const fixed = Number(value).toFixed(digits);
  return trimDecimalZeros(fixed);
}

function setNumberInput(id, value, digits = 3) {
  const el = byId(id);
  if (!el || document.activeElement === el) return;
  el.value = inputText(value, digits);
}

function markConfigDirty() {
  state.configDirty = true;
  setText("saveState", "not saved");
}

function isManualLevelModule(value) {
  return levelModuleKey(value) === "manual";
}

function levelModuleKey(value) {
  const key = String(value || "manual").toLowerCase();
  if (["manual", "none", "no_sensor", "no-sensor", "nosensor", "disabled", "disable", "off", "false", "0"].includes(key)) {
    return "manual";
  }
  if (key.includes("hcsr04") || key.includes("hc-sr04")) return "hcsr04";
  if (key.includes("rcwl")) return "rcwl1670";
  return key;
}

function selectedLevelModule(config = null) {
  const select = byId("levelModuleInput");
  if (state.configDirty && select) return select.value;
  return select?.value || config?.level_module || "manual";
}

function updateManualDistanceVisibility(config = null) {
  const module = selectedLevelModule(config);
  const manual = isManualLevelModule(module);
  const field = byId("waterDistanceField");
  const input = byId("waterDistanceInput");
  const sensorField = byId("sensorDistanceField");
  if (field) field.hidden = !manual;
  if (input) input.disabled = !manual;
  if (sensorField) sensorField.hidden = manual;
  renderSensorDistanceReadout(state.data, module);
}

function pumpPinNeedsAttention(data = state.data) {
  return data?.runtime?.pump_hw === false;
}

function updatePumpPinLock(data = state.data) {
  const input = byId("pumpPinInput");
  const field = byId("pumpPinField");
  const hint = byId("pumpPinHint");
  const needsAttention = pumpPinNeedsAttention(data);
  const error = data?.runtime?.pump_error;
  if (input) {
    input.disabled = Boolean(data?.runtime?.pump_hw);
    input.classList.toggle("needs-attention", needsAttention);
    input.setAttribute("aria-invalid", needsAttention ? "true" : "false");
    if (needsAttention) {
      input.setAttribute("aria-describedby", "pumpPinHint");
    } else {
      input.removeAttribute("aria-describedby");
    }
  }
  field?.classList.toggle("needs-attention", needsAttention);
  if (hint) {
    hint.hidden = !needsAttention;
    hint.textContent = needsAttention ? "Please configure pump pin and save." : "";
  }
}

async function requestStatus() {
  return aquaCommand("status", { measure: true });
}

function badge(id, text, kind) {
  const el = byId(id);
  if (!el) return;
  el.textContent = text;
  el.className = "badge" + (kind ? " " + kind : "");
}

function renderBadges(data) {
  const ready = data.ready || {};
  const tank = data.tank || {};
  const minLevel = Number(data.config?.min_level_cm);
  const pumpOn = Boolean(data.pump_on);
  const pumpAttention = pumpPinNeedsAttention(data);

  if (ready.ok) {
    badge("readyBadge", "Ready", "ok");
  } else {
    badge("readyBadge", "Locked", "alert");
  }

  if (pumpAttention) {
    badge("pumpBadge", "Set pump pin", "warn");
  } else {
    badge("pumpBadge", pumpOn ? "Pump on" : "Pump off", pumpOn ? "warn" : "");
  }

  const level = tank.level_percent;
  const waterHeight = Number(tank.water_height_cm);
  if (level === null || typeof level === "undefined") {
    badge("levelBadge", "Level unknown", "warn");
  } else if (Number.isFinite(minLevel) && Number.isFinite(waterHeight) && waterHeight < minLevel) {
    badge("levelBadge", "Tank low", "alert");
  } else {
    badge("levelBadge", `${Math.round(Number(level))}%`, "ok");
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function truncateName(name, max = 18) {
  const s = String(name == null ? "" : name);
  return s.length > max ? s.slice(0, max - 1) + "\u2026" : s;
}

function renderHeads(heads) {
  const grid = byId("headGrid");
  if (!grid) return;
  grid.innerHTML = "";
  const list = Array.isArray(heads) && heads.length
    ? heads
    : [{ name: "Head 1", flow_l_hour: 0 }];
  list.forEach((h, i) => {
    const name = h.name || `Head ${i + 1}`;
    const head = document.createElement("div");
    head.className = "head";
    head.title = name;   // full name on hover (truncated label on tile)
    head.innerHTML = `
      <div class="drops" aria-hidden="true"><span></span><span></span><span></span></div>
      <strong>${escapeHtml(truncateName(name))}</strong>
      <span>${fmt(h.flow_l_hour, " L/h")}</span>
    `;
    grid.appendChild(head);
  });
}

function soilLevelClass(value) {
  const moisture = Number(value);
  if (!Number.isFinite(moisture)) return "";
  if (moisture < 35) return "dry";
  if (moisture > 72) return "wet";
  return "ok";
}

function renderSoilSensors(soil) {
  const grid = byId("soilGrid");
  if (!grid) return;
  const sensors = Array.isArray(soil?.sensors) ? soil.sensors.slice(0, 100) : [];
  const count = clampCount(soil?.count ?? sensors.length, 0);
  const average = soil?.average_percent;

  setText("soilSummary", count ? `${count} sensors / avg ${fmt(average, "%")}` : "0 sensors");
  grid.innerHTML = "";

  if (!count) {
    const empty = document.createElement("div");
    empty.className = "soil-empty";
    empty.textContent = "No soil sensors";
    grid.appendChild(empty);
    return;
  }

  sensors.forEach((sensor, index) => {
    const moisture = sensor.moisture_percent;
    const tile = document.createElement("div");
    tile.className = `soil-sensor ${soilLevelClass(moisture)}`;
    tile.innerHTML = `
      <span class="soil-probe" aria-hidden="true"></span>
      <strong>S${sensor.id || index + 1}</strong>
      <span>${fmt(moisture, "%")}</span>
    `;
    grid.appendChild(tile);
  });
}

function levelModuleLabel(value) {
  const key = levelModuleKey(value);
  if (key === "hcsr04") return "HC-SR04";
  if (key === "rcwl1670") return "RCWL-1670";
  if (key === "manual") return "No sensor";
  return value ? String(value) : "--";
}

function setLevelMetric(source, value) {
  const mode = String(source || "--");
  setText("metricSensorLabel", `Water level (${mode === "Manual" ? "manual" : mode})`);
  setText("metricSensor", value);
}

function levelPercent(heightCm, tankHeight) {
  const markerLevel = Number(heightCm);
  const height = Number(tankHeight);
  return !Number.isFinite(markerLevel) || !Number.isFinite(height) || height <= 0
    ? null
    : clampPercent(markerLevel * 100 / height);
}

function minLevelText(minLevelCm) {
  return Number.isFinite(Number(minLevelCm)) ? `Min ${fmt(minLevelCm, " cm")}` : "Min -- cm";
}

function reserveText(minLevelCm, reserveL) {
  const reserve = Number(reserveL);
  return `${Number.isFinite(Number(minLevelCm)) ? fmt(minLevelCm, " cm") : "-- cm"} / ${Number.isFinite(reserve) ? fmt(reserve, " L") : "-- L"}`;
}

function renderSensorDistanceReadout(data, module = null) {
  const el = byId("sensorDistanceReadout");
  if (!el) return;

  const activeModule = module || data?.config?.level_module;
  if (isManualLevelModule(activeModule)) {
    el.value = "";
    return;
  }

  const sensor = data?.level_sensor || {};
  const activeKey = levelModuleKey(activeModule);
  const sensorKey = levelModuleKey(sensor.module);
  if (sensor.state && activeKey === sensorKey && Number.isFinite(Number(sensor.distance_cm))) {
    el.value = fmt(sensor.distance_cm, " cm");
  } else if (sensor.error && activeKey === sensorKey) {
    el.value = "offline";
  } else {
    el.value = "-- cm";
  }
}

function renderLevelSensor(data) {
  const sensor = data.level_sensor || {};
  const moduleName = sensor.module || data.config?.level_module;
  const label = levelModuleLabel(moduleName);
  let source = label;
  let value = "-- cm";

  if (String(sensor.source || "").startsWith("manual") && Number.isFinite(Number(sensor.distance_cm))) {
    source = "Manual";
    value = fmt(sensor.distance_cm, " cm");
  } else if (label === "No sensor" || sensor.enabled === false) {
    source = "Manual";
    value = "No sensor";
  } else if (sensor.state && Number.isFinite(Number(sensor.distance_cm))) {
    value = fmt(sensor.distance_cm, " cm");
  } else if (sensor.error) {
    value = "offline";
  }
  setLevelMetric(source, value);
  renderSensorDistanceReadout(data);
}

function fillInputs(config) {
  if (state.configDirty) return;
  Object.keys(configFields).forEach((id) => {
    const el = byId(id);
    const key = configFields[id];
    if (!el || document.activeElement === el) return;
    const value = config?.[key];
    if (id === "levelModuleInput") {
      el.value = levelModuleKey(value);
      return;
    }
    el.value = value === null || typeof value === "undefined" ? "" : value;
  });
}

// ---- Heads editor (per-head name + flow) ----

function headRowTemplate(head = {}) {
  const row = document.createElement("div");
  row.className = "head-row";
  if (head.id != null) row.dataset.headId = String(head.id);
  const name = head.name == null ? "" : head.name;
  const flow = head.flow_l_hour == null ? "" : head.flow_l_hour;
  row.innerHTML = `
    <input class="head-name" type="text" placeholder="Name" maxlength="24" />
    <input class="head-flow" type="number" min="0" step="0.1" inputmode="decimal" placeholder="L/h" />
    <button type="button" class="head-del" title="Remove head">&#10005;</button>
  `;
  row.querySelector(".head-name").value = name;
  row.querySelector(".head-flow").value = flow;
  row.querySelector(".head-name").addEventListener("input", markConfigDirty);
  row.querySelector(".head-flow").addEventListener("input", markConfigDirty);
  row.querySelector(".head-del").addEventListener("click", () => {
    row.remove();
    markConfigDirty();
  });
  return row;
}

function renderHeadsEditor(heads) {
  if (state.configDirty) return;   // don't clobber in-progress edits
  const editor = byId("headsEditor");
  if (!editor) return;
  editor.innerHTML = "";
  (Array.isArray(heads) ? heads : []).forEach((h) => editor.appendChild(headRowTemplate(h)));
}

function headsFromEditor() {
  const editor = byId("headsEditor");
  if (!editor) return [];
  return Array.from(editor.querySelectorAll(".head-row")).map((row) => {
    const name = row.querySelector(".head-name").value.trim();
    const flow = Number(row.querySelector(".head-flow").value);
    const head = { name: name || "Head", flow_l_hour: Number.isFinite(flow) ? Math.max(0, flow) : 0 };
    if (row.dataset.headId) head.id = Number(row.dataset.headId);   // keep id for existing heads
    return head;
  });
}

function runEstimate() {
  const data = state.data || {};
  const config = data.config || {};
  const flow = data.flow || {};
  const pump = Number(config.pump_l_hour || 0);
  // A model: combined flow comes from the backend (sum of per-head flows).
  const totalFlow = Number(flow.heads_total_l_hour || 0);
  const heads = clampCount(flow.head_count || (Array.isArray(config.heads) ? config.heads.length : 1), 1);
  const totalVolume = numberValue("runVolume") || 0;
  return {
    heads,
    pump,
    totalFlow,
    totalVolume,
    duration: totalFlow > 0 ? totalVolume * 3600 / totalFlow : 0,
    overload: pump > 0 && totalFlow > pump,
  };
}

function waterRunPayload(estimate = runEstimate()) {
  return {
    volume_l: Math.max(0, estimate.totalVolume || 0),
  };
}

function renderRunCommand(estimate = runEstimate()) {
  const input = byId("runCommandInput");
  if (input) input.value = aquaCommandText("start", waterRunPayload(estimate));
}

function activeRun(data = state.data) {
  // New state-machine run object: {mode, elapsed_s, duration_s, volume_l, per_head_l}
  return data?.run || null;
}

function fsmState(data = state.data) {
  return data?.state || "IDLE";
}

function projectedRun(data = state.data) {
  // Status-only display (SPEC §13 "A" simplification): show the backend's
  // elapsed_s/duration_s directly, no client-side interpolation. A faster poll
  // while RUNNING keeps it reasonably live without jumping/resetting.
  const run = activeRun(data);
  if (!run) return null;
  const duration = Number(run.duration_s) || 0;         // timed total (manual: null/0 -> infinite)
  const target = Number(run.volume_l) || 0;
  const elapsed = Math.max(0, Number(run.elapsed_s) || 0);
  const running = fsmState(data) === "RUNNING";
  if (duration > 0) {
    const clampedElapsed = Math.min(duration, elapsed);
    const remaining = Math.max(0, duration - clampedElapsed);
    const ratio = Math.min(1, clampedElapsed / duration);
    return {
      mode: run.mode,
      active: running && remaining > 0,
      remaining_s: remaining,
      dispensed_l: Math.min(target, target * ratio),
      target_l: target,
      infinite: false,
    };
  }
  // manual / infinite
  return {
    mode: run.mode || "manual",
    active: running,
    remaining_s: null,
    dispensed_l: null,
    target_l: target,
    elapsed_s: elapsed,
    infinite: true,
  };
}

const PRIMARY_LABELS = {
  IDLE: "&#9654; Start",
  RUNNING: "&#10073;&#10073; Pause",
  PAUSED: "&#9654; Resume",
};

function renderPrimaryButton(fstate) {
  const btn = byId("primaryBtn");
  if (!btn) return;
  btn.innerHTML = PRIMARY_LABELS[fstate] || PRIMARY_LABELS.IDLE;
  btn.dataset.action = fstate === "RUNNING" ? "pause" : (fstate === "PAUSED" ? "resume" : "start");
  // Yellow in RUNNING (Pause), green otherwise (Start/Resume).
  btn.classList.toggle("pause", fstate === "RUNNING");
  btn.classList.toggle("primary", fstate !== "RUNNING");
  btn.disabled = Boolean(state.busy);
  // Start needs a volume; pause/resume always allowed.
  if (fstate === "IDLE") {
    const est = runEstimate();
    // Start needs a volume and must not overload the pump.
    btn.disabled = Boolean(state.busy) || !(est.totalVolume > 0) || est.overload;
  }
}

function renderLiveRun(data = state.data) {
  const flow = data?.flow || {};
  const fstate = fsmState(data);
  const run = projectedRun(data);
  const active = fstate === "RUNNING";
  const availableAfterCard = byId("availableAfterCard");
  const estimate = runEstimate();

  const stateLabel = { IDLE: "Idle", RUNNING: "Watering", PAUSED: "Paused" }[fstate] || "Idle";
  setText("pumpState", stateLabel);
  setText("pumpFlow", active && run && !run.infinite
    ? `${fmt(run.dispensed_l, " L", 2)} / ${fmt(run.target_l, " L", 2)}`
    : fmt(flow.pump_l_hour, " L/h"));
  document.querySelector(".pump-node")?.classList.toggle("is-watering", active);

  renderPrimaryButton(fstate);
  const stopBtn = byId("stopBtn");
  if (stopBtn) stopBtn.disabled = Boolean(state.busy) || fstate === "IDLE";

  if (active && run && !run.infinite) {
    setText("previewDurationLabel", "Countdown");
    // Seed the local countdown ONLY on a run change (new start/resume or different
    // duration), NOT on every status poll -> the number counts down smoothly and
    // is not yanked back every 2s. The 1s ticker owns the displayed value.
    const key = `${run.duration_s}`;
    if (!state.countdown || state.countdown.key !== key) {
      state.countdown = { key, remaining: Math.max(0, run.remaining_s), at: Date.now() };
    }
    setText("previewWaterLabel", "Outgoing");
    setText("previewAvailableAfter", `${fmt(run.dispensed_l, " L", 3)} / ${fmt(run.target_l, " L", 3)}`);
    availableAfterCard?.classList.remove("is-alert");
  } else if (active && run && run.infinite) {
    state.countdown = null;
    setText("previewDurationLabel", "Running (manual)");
    setText("previewDuration", Math.floor(run.elapsed_s) + " s");
    setText("previewWaterLabel", "Mode");
    setText("previewAvailableAfter", "manual");
    availableAfterCard?.classList.remove("is-alert");
  } else {
    state.countdown = null;
    const tank = state.data?.tank || {};
    const usable = Number(tank.usable_l);
    const rawAfter = Number.isFinite(usable) ? usable - estimate.totalVolume : null;
    const after = rawAfter === null ? null : Math.max(0, rawAfter);
    setText("previewDurationLabel", "Pump runtime");
    setText("previewDuration", Math.round(estimate.duration) + " s");
    setText("previewWaterLabel", "Available after");
    setText("previewAvailableAfter", fmt(after, " L", 3));
    availableAfterCard?.classList.toggle("is-alert", rawAfter !== null && rawAfter < 0);
  }
  setText("previewTotalFlow", fmt(estimate.totalFlow, " L/h"));
  renderRunCommand(estimate);
}

function renderFault(data = state.data) {
  const banner = byId("faultBanner");
  if (!banner) return;
  const fault = data?.fault;
  // Priority: a persistent backend fault (e.g. low_water auto-pause) wins;
  // otherwise show a transient "blocked" reason from a rejected start/resume.
  if (fault) {
    banner.hidden = false;
    if (fault.reason === "low_water") {
      banner.className = "fault-banner is-low-water";
      banner.textContent = "\u26A0 Low water \u2014 refill tank, then Resume";
    } else {
      banner.className = "fault-banner is-error";
      banner.textContent = "\u26A0 " + (fault.reason || "Fault") + " \u2014 check device";
    }
    return;
  }
  if (state.blocked === "low_water" || state.blocked === "not_enough_usable_water") {
    banner.hidden = false;
    banner.className = "fault-banner is-low-water";
    banner.textContent = "\u26A0 Not enough water \u2014 refill tank or lower the amount";
    return;
  }
  if (state.blocked === "pump_overload") {
    banner.hidden = false;
    banner.className = "fault-banner is-error";
    banner.textContent = "\u26A0 Pump overload \u2014 heads exceed pump capacity";
    return;
  }
  // Planning-time overload (IDLE): heads' combined flow exceeds pump capacity.
  if (fsmState(data) === "IDLE" && runEstimate().overload) {
    banner.hidden = false;
    banner.className = "fault-banner is-error";
    banner.textContent = "\u26A0 Pump overload \u2014 reduce heads or head flow";
    return;
  }
  banner.hidden = true;
  banner.className = "fault-banner";
}

function renderStatus(data) {
  state.data = data;
  state.statusAt = Date.now();
  const tank = data.tank || {};
  const flow = data.flow || {};
  const soil = data.soil || {};
  const config = data.config || {};
  const headCount = flow.head_count || config.head_count || 0;
  const soilCount = soil.count ?? config.soil_sensor_count ?? 0;

  const level = Number(tank.level_percent);
  const tankHeight = Number(tank.height_cm);
  const waterHeight = Number(tank.water_height_cm);
  const measuredLevel = Number.isFinite(tankHeight) && tankHeight > 0 && Number.isFinite(waterHeight)
    ? waterHeight * 100 / tankHeight
    : level;
  const minLevel = Number(config.min_level_cm);
  const fill = byId("tankFill");
  const waterLevel = clampPercent(measuredLevel);
  if (fill) fill.style.height = waterLevel === null ? "0%" : `${waterLevel}%`;
  const waterMarker = byId("waterHeightMarker");
  if (waterMarker) {
    waterMarker.hidden = waterLevel === null;
    waterMarker.style.bottom = `${waterLevel || 0}%`;
    waterMarker.classList.toggle("is-high", waterLevel !== null && waterLevel > 82);
  }
  setText("waterHeightLabel", Number.isFinite(waterHeight) ? fmt(waterHeight, " cm") : "-- cm");
  const marker = byId("minLevelMarker");
  const minMarkerLevel = levelPercent(minLevel, tankHeight);
  if (marker) {
    marker.hidden = minMarkerLevel === null;
    marker.style.bottom = `${minMarkerLevel || 0}%`;
  }

  setText("tankPercent", Number.isFinite(level) ? `${Math.round(level)}%` : "--%");
  setText("tankVolume", fmt(tank.volume_l, " L"));
  setText("tankCapacity", fmt(tank.capacity_l, " L"));
  setText("minLevelLabel", minLevelText(minLevel));
  setText("schemeSummary", `${headCount} heads / ${soilCount} sensors`);
  setText("usableWater", fmt(tank.usable_l, " L"));
  setText("metricPump", fmt(flow.pump_l_hour, " L/h"));
  setText("metricHead", fmt(flow.heads_total_l_hour, " L/h"));
  setText("metricReserve", reserveText(minLevel, tank.reserve_l));

  renderHeads(flow.heads);
  renderSoilSensors(soil);
  renderLevelSensor(data);
  renderBadges(data);
  fillInputs(config);
  renderHeadsEditor(config.heads);
  updatePumpPinLock(data);
  updateManualDistanceVisibility(config);
  renderLiveRun(data);
  renderFault(data);
}

async function refresh() {
  if (state.busy) return;
  try {
    const data = await syncSettings(await requestStatus());
    renderStatus(data);
    setMessage("Synced");
  } catch (err) {
    setMessage("Aqua API unavailable. Run `aqua load` on the device.", "error");
    badge("readyBadge", "Offline", "alert");
  }
}

function configPayload() {
  const payload = {};
  Object.keys(configFields).forEach((id) => {
    const el = byId(id);
    if (!el || el.disabled) return;
    const key = configFields[id];
    payload[key] = el.type === "number" ? numberValue(id) : textValue(id);
  });
  if (!isManualLevelModule(payload.level_module)) {
    delete payload.water_distance_cm;
  }
  payload.heads = headsFromEditor();
  return payload;
}

async function saveConfig(event) {
  event.preventDefault();
  state.busy = true;
  byId("saveConfigBtn").disabled = true;
  setText("saveState", "saving");
  try {
    const data = await saveSettings(configPayload());
    state.settingsAt = Date.now();
    state.configDirty = false;
    renderStatus(data);
    setText("saveState", "saved");
    setMessage("Configuration saved");
  } catch (err) {
    setText("saveState", "not saved");
    setMessage("Save failed", "error");
  } finally {
    byId("saveConfigBtn").disabled = false;
    state.busy = false;
  }
}

async function primaryAction() {
  const btn = byId("primaryBtn");
  const action = btn?.dataset.action || "start";
  state.busy = true;
  if (btn) btn.disabled = true;
  try {
    let result = null;
    if (action === "start") {
      const run = waterRunPayload(runEstimate());
      if (!run.volume_l) {
        setMessage("Enter a water amount", "error");
        return;
      }
      result = await aquaCommand("start", run);
    } else if (action === "pause") {
      result = await aquaCommand("pause");
    } else if (action === "resume") {
      result = await aquaCommand("resume");
    }
    // The LM returns a result object; state:false means the command was rejected
    // (e.g. low_water lockout). It does NOT throw in that case.
    if (result && result.state === false) {
      const reason = result.error || "blocked";
      const known = ["low_water", "not_enough_usable_water", "pump_overload"];
      state.blocked = known.includes(reason) ? reason : null;
      const msg = reason === "pump_overload" ? "Pump overload"
        : (reason === "low_water" || reason === "not_enough_usable_water") ? "Not enough water"
        : (action + " rejected: " + reason);
      setMessage(msg, "error");
    } else {
      state.blocked = null;
      setMessage({ start: "Watering started", pause: "Paused", resume: "Resumed" }[action] || "OK");
    }
  } catch (err) {
    setMessage((action.charAt(0).toUpperCase() + action.slice(1)) + " command failed", "error");
  } finally {
    state.busy = false;
    await refresh();
    renderFault();
  }
}

async function stopAction() {
  byId("stopBtn").disabled = true;
  state.busy = true;
  try {
    await aquaCommand("stop");
    setMessage("Stopped");
  } catch (err) {
    setMessage("Stop failed", "error");
  } finally {
    state.busy = false;
    await refresh();
  }
}

function wire() {
  byId("refreshBtn")?.addEventListener("click", refresh);
  byId("configForm")?.addEventListener("submit", saveConfig);
  byId("addHeadBtn")?.addEventListener("click", () => {
    const editor = byId("headsEditor");
    if (editor) editor.appendChild(headRowTemplate({}));
    markConfigDirty();
  });
  byId("primaryBtn")?.addEventListener("click", primaryAction);
  byId("stopBtn")?.addEventListener("click", stopAction);
  byId("runCommandInput")?.addEventListener("focus", (event) => event.target.select());
  byId("runCommandInput")?.addEventListener("click", (event) => event.target.select());
  byId("runVolume")?.addEventListener("input", () => {
    renderLiveRun();
    renderFault();
  });
  Object.keys(configFields).forEach((id) => {
    byId(id)?.addEventListener("input", () => {
      markConfigDirty();
      if (id === "levelModuleInput") updateManualDistanceVisibility();
    });
  });
  byId("levelModuleInput")?.addEventListener("change", () => {
    markConfigDirty();
    updateManualDistanceVisibility();
  });
}

wire();
updateManualDistanceVisibility();
refresh();

// Adaptive status poll: faster while RUNNING (live-ish countdown without
// client-side interpolation), slower otherwise. No separate 1s interpolation
// tick (SPEC §13 "A": status-only display).
function scheduleRefresh() {
  const running = fsmState() === "RUNNING";
  setTimeout(async () => {
    await refresh();
    scheduleRefresh();
  }, running ? 2000 : 5000);
}
scheduleRefresh();

// Client-side 1s countdown: seeded from status (renderLiveRun sets state.countdown),
// counts down locally each second; the 2s status poll re-syncs the base. Start and
// end points match the backend; only the in-between seconds are local.
setInterval(() => {
  const cd = state.countdown;
  if (!cd || fsmState() !== "RUNNING") return;
  const left = Math.max(0, cd.remaining - (Date.now() - cd.at) / 1000);
  setText("previewDuration", Math.ceil(left) + " s");
}, 1000);
