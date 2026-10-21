const state = {
  data: null,
  statusAt: 0,
  busy: false,
  configDirty: false,
  settingsAt: 0,
  blocked: null,   // transient reason when a start/resume was rejected (e.g. low_water)
  countdown: null, // {remaining, at} client-side 1s countdown, seeded from status
  lastDose: null,  // {totalFlow, xTotal, yTotal} kept after stop until next Start / Total L change
  nodeClock: null, // {base, at, weekday} anchor for the locally-ticking node clock
};

const configFields = {
  tankModeInput: "tank_mode",
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

// Seconds -> clock string: 45 -> "0:45", 125 -> "2:05", 3725 -> "1:02:05".
function fmtClock(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (x) => String(x).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
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
  setDirtyUI(true);
}

function setDirtyUI(dirty) {
  document.querySelector(".settings-panel")?.classList.toggle("is-dirty", dirty);
  const saveState = byId("saveState");
  if (saveState) {
    saveState.textContent = dirty ? "not saved" : "";   // no label when saved/clean
    saveState.classList.toggle("is-dirty", dirty);
  }
  const btn = byId("saveConfigBtn");
  if (btn) btn.disabled = !dirty;   // Save disabled when there is nothing to save
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
  const vols = headVolumes();
  list.forEach((h, i) => {
    const name = h.name || `Head ${i + 1}`;
    const flow = Number(h.flow_l_hour) || 0;
    const share = vols.totalFlow > 0 ? flow / vols.totalFlow : 0;
    const x = vols.xTotal == null ? null : vols.xTotal * share;   // planned for this head
    const y = vols.yTotal == null ? null : vols.yTotal * share;   // dispensed for this head
    const head = document.createElement("div");
    head.className = "head";
    head.title = name;   // full name on hover (truncated label on tile)
    head.innerHTML = `
      <div class="drops" aria-hidden="true"><span></span><span></span><span></span></div>
      <strong>${escapeHtml(truncateName(name))}</strong>
      <span>${fmt(h.flow_l_hour, " L/h")}</span>
      <span class="head-dose">${headDoseText(y, x)}</span>
    `;
    grid.appendChild(head);
  });
}

// "Y / X" litres for a head: dispensed so far / planned. Shows "--" when no plan.
function headDoseText(y, x) {
  if (x == null && (y == null || y === 0)) return "&ndash;";
  const yTxt = y == null ? "0" : (Math.round(y * 100) / 100).toString();
  const xTxt = x == null ? "&infin;" : (Math.round(x * 100) / 100).toString();
  return `${yTxt} / ${xTxt} L`;
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

// ---- Tank mode + calibration editor (advanced mode) ----

function tankModeValue() {
  return byId("tankModeInput")?.value || "simple";
}

function updateTankModeVisibility() {
  const advanced = tankModeValue() === "advanced";
  const simple = byId("tankSimpleFields");
  const adv = byId("tankAdvancedFields");
  if (simple) simple.hidden = advanced;
  if (adv) adv.hidden = !advanced;
}

function calibRowTemplate(point = {}) {
  const row = document.createElement("div");
  row.className = "head-row";
  row.innerHTML = `
    <input class="calib-dist" type="number" min="0" step="0.1" inputmode="decimal" placeholder="cm" />
    <input class="calib-vol" type="number" min="0" step="0.1" inputmode="decimal" placeholder="L" />
    <button type="button" class="head-del" title="Remove point">&#10005;</button>
  `;
  row.querySelector(".calib-dist").value = point.distance_cm == null ? "" : point.distance_cm;
  row.querySelector(".calib-vol").value = point.volume_l == null ? "" : point.volume_l;
  row.querySelector(".calib-dist").addEventListener("input", markConfigDirty);
  row.querySelector(".calib-vol").addEventListener("input", markConfigDirty);
  row.querySelector(".head-del").addEventListener("click", () => { row.remove(); markConfigDirty(); });
  return row;
}

function renderCalibrationEditor(points) {
  if (state.configDirty) return;
  const editor = byId("calibrationEditor");
  if (!editor) return;
  editor.innerHTML = "";
  (Array.isArray(points) ? points : []).forEach((p) => editor.appendChild(calibRowTemplate(p)));
}

function calibrationFromEditor() {
  const editor = byId("calibrationEditor");
  if (!editor) return [];
  return Array.from(editor.querySelectorAll(".head-row")).map((row) => ({
    distance_cm: Number(row.querySelector(".calib-dist").value),
    volume_l: Number(row.querySelector(".calib-vol").value),
  })).filter((p) => Number.isFinite(p.distance_cm) && Number.isFinite(p.volume_l));
}

async function measureCalibrationPoint() {
  const btn = byId("addCalibBtn");
  if (btn) btn.disabled = true;
  try {
    const res = await aquaCommand("sensor_distance");
    const dist = res && (res.distance_cm ?? res.raw?.cm);
    const editor = byId("calibrationEditor");
    if (editor) {
      const row = calibRowTemplate({ distance_cm: Number.isFinite(Number(dist)) ? Math.round(Number(dist) * 10) / 10 : "" });
      editor.appendChild(row);
      row.querySelector(".calib-vol").focus();   // user types the litres
    }
    markConfigDirty();
    setMessage(Number.isFinite(Number(dist)) ? `Measured ${Math.round(Number(dist) * 10) / 10} cm — enter litres` : "Measure failed", Number.isFinite(Number(dist)) ? "neutral" : "error");
  } catch (err) {
    setMessage("Measure failed: " + (err?.message || ""), "error");
  } finally {
    if (btn) btn.disabled = false;
  }
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

// Per-head planned (X) and dispensed (Y) totals, split proportionally by flow.
// X = planned volume for this run (run target while a run exists, otherwise the
//     Total L typed into the run box). Y = actually dispensed so far, updated on
//     every state change (pause/stop/auto-stop) via run.elapsed_s / dispensed_l.
function headVolumes(data = state.data) {
  const flow = data?.flow || {};
  const totalFlow = Number(flow.heads_total_l_hour || 0);   // Sum of head flows
  const run = activeRun(data);
  const proj = projectedRun(data);

  let xTotal = null;   // planned total litres
  let yTotal = null;   // dispensed total litres
  if (run) {
    const target = Number(run.volume_l) || 0;               // timed target (0 for manual)
    xTotal = target > 0 ? target : null;                    // manual has no planned target
    if (proj && proj.dispensed_l != null) {
      yTotal = proj.dispensed_l;                            // timed: clamped dispensed
    } else {
      const elapsed = Math.max(0, Number(run.elapsed_s) || 0);
      yTotal = totalFlow > 0 ? totalFlow * elapsed / 3600 : 0;   // manual: flow * time
    }
    state.lastDose = { totalFlow, xTotal, yTotal };          // remember for after-stop display
    return state.lastDose;
  }
  // No active run. Keep the last run's Y/X after stop until the next Start or a
  // Total L change clears it (see clearLastDose()).
  if (state.lastDose) return state.lastDose;
  // Nothing remembered: preview X from the Total L typed in the run box, Y = 0.
  const typed = numberValue("runVolume") || 0;
  xTotal = typed > 0 ? typed : null;
  yTotal = 0;
  return { totalFlow, xTotal, yTotal };
}

// Clear the remembered post-stop Y/X (on next Start or when Total L changes).
function clearLastDose() {
  state.lastDose = null;
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
    // Seed the local timer ONLY on a run change, NOT on every status poll -> smooth,
    // no 2s jitter. The 1s ticker owns the displayed value.
    const key = `timed:${run.duration_s}`;
    if (!state.countdown || state.countdown.key !== key) {
      state.countdown = { key, dir: "down", base: Math.max(0, run.remaining_s), at: Date.now() };
    }
    setText("previewWaterLabel", "Outgoing");
    setText("previewAvailableAfter", `${fmt(run.dispensed_l, " L", 3)} / ${fmt(run.target_l, " L", 3)}`);
    availableAfterCard?.classList.remove("is-alert");
  } else if (active && run && run.infinite) {
    setText("previewDurationLabel", "Running (manual)");
    // Local up-counter, seeded once from status elapsed; ticker owns the display.
    if (!state.countdown || state.countdown.dir !== "up") {
      state.countdown = { key: "manual", dir: "up", base: Math.max(0, run.elapsed_s), at: Date.now() };
    }
    setText("previewWaterLabel", "Mode");
    setText("previewAvailableAfter", "manual");
    availableAfterCard?.classList.remove("is-alert");
  } else if (fstate === "PAUSED" && run && !run.infinite) {
    // Paused timed run: show the SAVED remaining time (not the full runtime).
    state.countdown = null;
    setText("previewDurationLabel", "Paused \u2014 remaining");
    setText("previewDuration", fmtClock(run.remaining_s));
    setText("previewWaterLabel", "Outgoing");
    setText("previewAvailableAfter", `${fmt(run.dispensed_l, " L", 3)} / ${fmt(run.target_l, " L", 3)}`);
    availableAfterCard?.classList.remove("is-alert");
  } else if (fstate === "PAUSED" && run && run.infinite) {
    // Paused manual run: no remaining time, show the SAVED elapsed instead.
    state.countdown = null;
    setText("previewDurationLabel", "Paused \u2014 elapsed");
    setText("previewDuration", fmtClock(run.elapsed_s));
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
    setText("previewDuration", fmtClock(estimate.duration));
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
  renderCalibrationEditor(config.tank_calibration);
  updateTankModeVisibility();
  setDirtyUI(state.configDirty);   // keep Save button + label in sync with dirty state
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
  payload.tank_mode = tankModeValue();
  payload.tank_calibration = calibrationFromEditor();
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
    setDirtyUI(false);   // clears the label + disables Save (nothing to save)
    setMessage("Configuration saved");
  } catch (err) {
    setDirtyUI(true);    // keep "not saved" + Save enabled so the user can retry
    setMessage("Save failed", "error");
  } finally {
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
      clearLastDose();   // next Start resets the per-head Y/X
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

// ======================= Schedule (cron) =======================

const SCHED_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Human label for a crontasks weekday field ('*', '0-6', '0-4', single '3').
function daysLabel(days) {
  const s = String(days == null ? "*" : days).trim();
  if (s === "*" || s === "0-6") return "Every day";
  const range = s.match(/^([0-6])-([0-6])$/);
  if (range) {
    const a = Number(range[1]), b = Number(range[2]);
    if (a === 0 && b === 4) return "Mon\u2013Fri";
    if (a === 5 && b === 6) return "Weekend";
    return `${SCHED_DAY_LABELS[a]}\u2013${SCHED_DAY_LABELS[b]}`;
  }
  if (/^[0-6]$/.test(s)) return SCHED_DAY_LABELS[Number(s)];
  return s;
}

function fmtHM(hour, minute) {
  const h = String(hour == null ? 0 : hour).padStart(2, "0");
  const m = String(minute == null ? 0 : minute).padStart(2, "0");
  return `${h}:${m}`;
}

function renderScheduleList(schedules) {
  const list = byId("scheduleList");
  if (!list) return;
  list.innerHTML = "";
  const items = Array.isArray(schedules) ? schedules : [];
  setText("scheduleSummary", items.length ? `${items.length} scheduled` : "none");
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "schedule-empty";
    empty.textContent = "No schedules yet.";
    list.appendChild(empty);
    return;
  }
  items.forEach((s) => {
    const row = document.createElement("div");
    row.className = "schedule-item";
    row.innerHTML = `
      <span class="sched-when"><strong>${fmtHM(s.hour, s.minute)}</strong> <span class="sched-days-lbl">${escapeHtml(daysLabel(s.days))}</span></span>
      <span class="sched-vol">${fmt(s.volume_l, " L")}</span>
      <button type="button" class="sched-del" title="Remove" data-index="${s.id}">&#10005;</button>
    `;
    row.querySelector(".sched-del").addEventListener("click", () => removeSchedule(s.id));
    list.appendChild(row);
  });
}

async function loadSchedules() {
  try {
    const res = await aquaCommand("schedule_list");
    renderScheduleList(res?.schedules);
    renderNodeClock(res?.now);
  } catch (err) {
    // best-effort; keep the panel usable even if the node is briefly unreachable
  }
}

// Show the node's local clock so it's clear what the scheduler works against.
// Seed from the node value, then tick locally while the panel is open.
function renderNodeClock(now) {
  if (now && now.iso) {
    // Parse "YYYY-MM-DD HH:MM:SS" into an epoch anchor for local ticking.
    const m = now.iso.match(/(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+)/);
    if (m) {
      const base = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
      state.nodeClock = { base, at: Date.now(), weekday: now.weekday };
    }
  } else {
    state.nodeClock = null;
  }
  paintNodeClock();
}

function paintNodeClock() {
  const el = byId("nodeClock");
  if (!el) return;
  const nc = state.nodeClock;
  if (!nc) { el.textContent = "Node time: unavailable"; return; }
  const d = new Date(nc.base + (Date.now() - nc.at));
  const pad = (n) => String(n).padStart(2, "0");
  const iso = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  // JS weekday: 0=Sun..6=Sat -> convert to node's 0=Mon..6=Sun.
  const wdIdx = (d.getDay() + 6) % 7;
  el.textContent = `Node time: ${iso} (${SCHED_DAY_LABELS[wdIdx]})`;
}

// Collect selected days as a list of crontasks weekday fields, one per
// CONTINUOUS block (the built-in scheduler can't store gaps in a single block).
// Every day -> ["0-6"]. Mon,Wed,Fri -> ["0","2","4"]. Mon,Tue,Thu,Fri -> ["0-1","3-4"].
// Returns [] when nothing is selected.
function selectedDayRanges() {
  if (byId("schedEveryDay")?.classList.contains("selected")) return ["0-6"];
  const days = Array.from(document.querySelectorAll(".sched-day[data-day].selected"))
    .map((b) => Number(b.dataset.day)).sort((a, b) => a - b);
  if (days.length === 0) return [];
  if (days.length === 7) return ["0-6"];
  // Group into continuous runs.
  const ranges = [];
  let start = days[0], prev = days[0];
  for (let i = 1; i < days.length; i++) {
    if (days[i] === prev + 1) { prev = days[i]; continue; }
    ranges.push(start === prev ? String(start) : `${start}-${prev}`);
    start = prev = days[i];
  }
  ranges.push(start === prev ? String(start) : `${start}-${prev}`);
  return ranges;
}

async function addSchedule(event) {
  event.preventDefault();
  const ranges = selectedDayRanges();
  if (ranges.length === 0) { setMessage("Select at least one day", "error"); return; }
  const hour = numberValue("schedHour");
  const minute = numberValue("schedMinute");
  const volume = numberValue("schedVolume");
  if (!Number.isFinite(hour) || hour < 0 || hour > 23) { setMessage("Enter a valid hour (0-23)", "error"); return; }
  if (!Number.isFinite(minute) || minute < 0 || minute > 59) { setMessage("Enter a valid minute (0-59)", "error"); return; }
  if (!Number.isFinite(volume) || volume <= 0) { setMessage("Enter a Total L amount", "error"); return; }
  const btn = byId("schedAddBtn");
  if (btn) btn.disabled = true;
  try {
    // Non-continuous day selections become several schedules (one per block).
    for (const days of ranges) {
      await aquaCommand("schedule_add", { days, hour, minute, volume_l: volume });
    }
    setMessage(ranges.length > 1 ? `Added ${ranges.length} schedules` : "Schedule added");
    resetScheduleForm();
    await loadSchedules();
  } catch (err) {
    setMessage("Add failed: " + (err?.message || ""), "error");
    await loadSchedules();   // reflect any partial additions
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function removeSchedule(index) {
  try {
    await aquaCommand("schedule_remove", { index });
    setMessage("Schedule removed");
    await loadSchedules();
  } catch (err) {
    setMessage("Remove failed: " + (err?.message || ""), "error");
  }
}

function resetScheduleForm() {
  document.querySelectorAll("#schedDays .sched-day.selected").forEach((b) => b.classList.remove("selected"));
  ["schedHour", "schedMinute", "schedVolume"].forEach((id) => { const el = byId(id); if (el) el.value = ""; });
}

function wireSchedule() {
  // Day toggles: picking a weekday clears "Every day" and vice versa.
  document.querySelectorAll("#schedDays .sched-day[data-day]").forEach((btn) => {
    btn.addEventListener("click", () => {
      byId("schedEveryDay")?.classList.remove("selected");
      btn.classList.toggle("selected");
    });
  });
  byId("schedEveryDay")?.addEventListener("click", () => {
    const on = byId("schedEveryDay").classList.toggle("selected");
    if (on) document.querySelectorAll("#schedDays .sched-day[data-day].selected").forEach((b) => b.classList.remove("selected"));
  });
  byId("scheduleForm")?.addEventListener("submit", addSchedule);
  // Load schedules when the panel is first opened.
  byId("scheduleDetails")?.addEventListener("toggle", (e) => {
    if (e.target.open) loadSchedules();
  });
  // Tick the node clock locally once a second while the panel is open.
  setInterval(() => {
    if (byId("scheduleDetails")?.open && state.nodeClock) paintNodeClock();
  }, 1000);
}

function wire() {
  byId("refreshBtn")?.addEventListener("click", refresh);
  byId("configForm")?.addEventListener("submit", saveConfig);
  byId("addHeadBtn")?.addEventListener("click", () => {
    const editor = byId("headsEditor");
    if (editor) editor.appendChild(headRowTemplate({}));
    markConfigDirty();
  });
  byId("addCalibBtn")?.addEventListener("click", measureCalibrationPoint);
  byId("tankModeInput")?.addEventListener("change", () => {
    markConfigDirty();
    updateTankModeVisibility();
  });
  byId("primaryBtn")?.addEventListener("click", primaryAction);
  byId("stopBtn")?.addEventListener("click", stopAction);
  byId("runCommandInput")?.addEventListener("focus", (event) => event.target.select());
  byId("runCommandInput")?.addEventListener("click", (event) => event.target.select());
  byId("runVolume")?.addEventListener("input", () => {
    renderLiveRun();
    renderFault();
    clearLastDose();   // changing Total L resets the per-head Y/X
    renderHeads(state.data?.flow?.heads);   // live X preview from the typed Total L
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
wireSchedule();
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

// Client-side 1s countdown: seeded on run change (renderLiveRun), counts down
// locally each second; status poll does NOT re-sync it (no jitter). Re-seeds
// only on a new run / resume. Displayed as m:ss.
setInterval(() => {
  const cd = state.countdown;
  if (!cd || fsmState() !== "RUNNING") return;
  const elapsed = (Date.now() - cd.at) / 1000;
  const value = cd.dir === "up"
    ? cd.base + elapsed
    : Math.max(0, cd.base - elapsed);
  setText("previewDuration", fmtClock(value));
}, 1000);
