import { createEngine } from "./engine.js";

const engine = createEngine();
const $ = (id) => document.getElementById(id);

const ui = {
  status: null,
  devices: null,
  models: [],
  loadingName: null,
  busy: false,
  lastError: null,
  editedAt: {}, // slider id -> time the user last moved it
};

// ---- small helpers -------------------------------------------------------

function toast(text, kind = "error") {
  const el = document.createElement("div");
  el.className = `toast ${kind === "ok" ? "ok" : ""}`;
  el.textContent = text;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "ok" ? 3000 : 6000);
}

function friendly(err) {
  const msg = String(err?.message ?? err);
  return msg.charAt(0).toUpperCase() + msg.slice(1);
}

async function call(method, params) {
  try {
    const result = await engine.call(method, params);
    if (result && result.phase) render(result);
    return result;
  } catch (err) {
    toast(friendly(err));
    throw err;
  }
}

function hash(str) {
  let h = 0;
  for (const c of str) h = (h * 31 + c.codePointAt(0)) >>> 0;
  return h;
}

function initials(name) {
  const words = name.replace(/[_-]+/g, " ").trim().split(/\s+/);
  const two = words.length > 1 ? words[0][0] + words[1][0] : name.slice(0, 2);
  return two.toUpperCase();
}

function throttle(fn, ms) {
  let last = 0, timer = null, args = null;
  return (...a) => {
    args = a;
    const wait = ms - (Date.now() - last);
    if (wait <= 0) { last = Date.now(); fn(...args); }
    else if (!timer) timer = setTimeout(() => { timer = null; last = Date.now(); fn(...args); }, wait);
  };
}

// ---- overlay -------------------------------------------------------------

function overlay({ title, text = "", spinner = true, progress = null, log = null, actions = [] } = {}) {
  if (!title) return void ($("overlay").hidden = true);
  $("overlay").hidden = false;
  $("overlayTitle").textContent = title;
  $("overlayText").textContent = text;
  $("overlaySpinner").hidden = !spinner;
  $("overlayProgress").hidden = progress === null;
  if (progress !== null) $("overlayBar").style.width = `${Math.round(progress * 100)}%`;
  $("overlayLog").hidden = !log;
  $("overlayLog").textContent = log || "";
  const box = $("overlayActions");
  box.replaceChildren(...actions.map(({ label, primary, onClick }) => {
    const b = document.createElement("button");
    b.className = `btn ${primary ? "primary" : ""}`;
    b.textContent = label;
    b.onclick = onClick;
    return b;
  }));
}

// ---- rendering -----------------------------------------------------------

const PHASES = {
  off: "Off",
  loading: "Loading voice",
  warming: "Warming up",
  live: "Live",
  real: "Real voice",
  muted: "Muted",
};

function powerText(s) {
  const voice = s.model || s.saved_model;
  switch (s.phase) {
    case "loading": return ["Loading voice…", ui.loadingName || voice || ""];
    case "warming": return ["Warming up…", "Your new voice starts in a moment"];
    case "live": return s.model
      ? ["You're live", `${s.model} · ${s.latency_ms} ms delay`]
      : ["Live, no voice picked", "Pick a voice to change how you sound"];
    case "real": return ["Real voice", `Press F8 to go back to ${s.model || "your voice"}`];
    case "muted": return ["Muted", "Press F7 to unmute"];
    default: return ["Ready", voice ? `Press start to speak as ${voice}` : "Add a voice, then press start"];
  }
}

function setSlider(id, value) {
  const el = $(id);
  if (Date.now() - (ui.editedAt[id] || 0) < 900) return; // user is dragging it
  el.value = value;
  paintSlider(el);
}

function paintSlider(el) {
  const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
  el.style.setProperty("--pct", `${pct}%`);
  const out = SLIDERS[el.id];
  if (out) $(out.label).textContent = out.format(Number(el.value));
}

const pct = (v) => `${Math.round(v * 100)}%`;
const SLIDERS = {
  pitch: { label: "pitchOut", format: (v) => (v === 0 ? "Normal" : `${v > 0 ? "+" : ""}${v} semitones`) },
  index_rate: { label: "indexOut", format: pct },
  in_gain: { label: "gainOut", format: pct },
  out_vol: { label: "volOut", format: pct },
  monitor_vol: { label: "monitorVolOut", format: pct },
};

function render(s) {
  ui.status = s;
  const pill = $("statusPill");
  pill.dataset.phase = s.phase;
  $("statusText").textContent = s.phase === "live" ? `Live · ${s.latency_ms} ms` : PHASES[s.phase] || s.phase;

  const power = $("power");
  power.classList.toggle("on", s.running);
  power.classList.toggle("busy", ui.busy || s.phase === "loading" || s.phase === "warming");
  power.setAttribute("aria-label", s.running ? "Stop" : "Start");
  const ring = $("powerRing");
  ring.style.transform = s.running ? `scale(${1 + s.levels.out * 0.12})` : "";
  const [title, sub] = powerText(s);
  $("powerTitle").textContent = title;
  $("powerSub").textContent = sub;

  $("bypass").classList.toggle("on", s.bypassed);
  $("mute").classList.toggle("on", s.muted);

  for (const b of $("latency").children) b.classList.toggle("on", b.dataset.value === s.latency);
  for (const b of $("fx").children) b.classList.toggle("on", !!s.fx[b.dataset.fx]);

  setSlider("pitch", s.pitch);
  setSlider("index_rate", s.index_rate);
  setSlider("in_gain", s.in_gain);
  setSlider("out_vol", s.out_vol);
  setSlider("monitor_vol", s.monitor_vol);

  $("inMeter").style.width = pct(s.levels.in);
  $("outMeter").style.width = pct(s.levels.out);

  $("monitorOn").checked = s.use_monitor;
  $("monitorBox").hidden = !s.use_monitor;
  if (ui.devices) {
    selectValue("inputSel", s.devices.input);
    selectValue("outputSel", s.devices.output);
    selectValue("monitorSel", s.devices.monitor);
    renderOutputHint();
  }

  if (ui.loadingName && s.phase !== "loading") ui.loadingName = null;
  renderVoiceStates();

  if (s.last_error && s.last_error !== ui.lastError) toast(friendly(s.last_error));
  ui.lastError = s.last_error;
}

function selectValue(id, value) {
  const el = $(id);
  if (value != null && el.value !== value && document.activeElement !== el) el.value = value;
}

function fillSelect(id, names, current, placeholder) {
  const el = $(id);
  const opts = names.map((n) => new Option(n, n));
  if (current && !names.includes(current)) opts.unshift(new Option(`${current} (not connected)`, current));
  if (!names.length && !current) opts.push(new Option(placeholder, ""));
  el.replaceChildren(...opts);
  if (current) el.value = current;
}

function renderDevices(d) {
  ui.devices = d;
  fillSelect("inputSel", d.inputs, d.input, "No microphone found");
  fillSelect("outputSel", d.outputs, d.output, "No output found");
  const monitorChoices = d.outputs.filter((n) => !/^CABLE/i.test(n));
  fillSelect("monitorSel", monitorChoices, d.monitor, "No speakers found");
  renderOutputHint();
}

function renderOutputHint() {
  const hint = $("outputHint");
  const out = ui.status?.devices.output || ui.devices?.output || "";
  const hasCable = ui.devices?.outputs.some((n) => /CABLE Input/i.test(n));
  hint.classList.remove("warn");
  if (/CABLE Input/i.test(out)) {
    hint.innerHTML = "In Discord or a game, choose <b>CABLE Output</b> as your microphone.";
  } else if (!hasCable) {
    hint.classList.add("warn");
    hint.innerHTML = "To use your voice in Discord or games, install <b>VB-Cable</b> (free), then pick <b>CABLE Input</b> here.";
  } else {
    hint.innerHTML = "You'll hear the new voice here. To use it in Discord, pick <b>CABLE Input</b>.";
  }
}

function renderVoices() {
  const grid = $("voiceGrid");
  const cards = ui.models.map((m) => {
    const card = document.createElement("button");
    card.className = "voice";
    card.dataset.name = m.name;
    const h = hash(m.name) % 360;
    card.innerHTML = `
      <div class="avatar" style="background: linear-gradient(135deg, hsl(${h} 72% 58%), hsl(${(h + 45) % 360} 70% 42%))"></div>
      <div class="voice-name"></div>
      <div class="voice-meta"></div>
      <span class="voice-badge" hidden></span>`;
    card.querySelector(".avatar").textContent = initials(m.name);
    card.querySelector(".voice-name").textContent = m.name;
    card.querySelector(".voice-meta").textContent = `${m.size_mb} MB${m.has_index ? " · tuned" : ""}`;
    card.title = m.has_index ? m.name : `${m.name} (no .index file, so it may sound a bit less like the voice)`;
    card.onclick = () => pickVoice(m.name);
    return card;
  });
  if (ui.models.length) {
    const add = document.createElement("button");
    add.className = "voice add";
    add.innerHTML = `<svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>Add voice</span>`;
    add.onclick = addVoices;
    cards.push(add);
  }
  grid.replaceChildren(...cards);
  $("emptyVoices").hidden = ui.models.length > 0;
  $("voiceCount").textContent = ui.models.length
    ? `${ui.models.length} voice${ui.models.length === 1 ? "" : "s"} · click one to switch, even while live`
    : "No voices yet";
  renderVoiceStates();
}

function renderVoiceStates() {
  const s = ui.status;
  for (const card of $("voiceGrid").querySelectorAll(".voice[data-name]")) {
    const name = card.dataset.name;
    const loading = ui.loadingName === name;
    const active = !loading && s && (s.model === name || (!s.model && !ui.loadingName && s.saved_model === name));
    card.classList.toggle("active", !!active);
    card.classList.toggle("loading", loading);
    const badge = card.querySelector(".voice-badge");
    badge.hidden = !(active || loading);
    badge.textContent = loading ? "Loading" : s?.model === name ? "Active" : "Selected";
  }
}

// ---- actions -------------------------------------------------------------

async function refreshModels() {
  ui.models = await engine.call("list_models");
  renderVoices();
}

async function pickVoice(name) {
  if (ui.loadingName || ui.status?.model === name) return;
  ui.loadingName = name;
  renderVoiceStates();
  try {
    await call("load_model", { model: name });
  } catch {
    /* toast already shown */
  } finally {
    ui.loadingName = null;
    renderVoiceStates();
  }
}

async function importPaths(paths) {
  const voices = paths.filter((p) => /\.pth$/i.test(p));
  if (!voices.length) {
    toast(paths.length ? "Drop the .pth voice file. Its .index comes along by itself when it's in the same folder." : "Nothing to add");
    return;
  }
  let first = null;
  for (const path of voices) {
    try {
      const r = await engine.call("import_model", { path });
      first ??= r.name;
      toast(`Added ${r.name}${r.has_index ? "" : " (no .index found next to it)"}`, "ok");
    } catch (err) {
      toast(`${path.split(/[\\/]/).pop()}: ${friendly(err)}`);
    }
  }
  await refreshModels();
  if (first && !ui.status?.model) pickVoice(first);
}

async function addVoices() {
  importPaths(await engine.pickFiles());
}

async function togglePower() {
  if (ui.busy) return;
  ui.busy = true;
  render(ui.status);
  try {
    await call(ui.status.running ? "stop" : "start");
  } catch {
    /* toast already shown */
  } finally {
    ui.busy = false;
    render(ui.status);
  }
}

function wire() {
  $("power").onclick = togglePower;
  $("bypass").onclick = () => call("toggle_bypass").catch(() => {});
  $("mute").onclick = () => call("toggle_mute").catch(() => {});
  $("addVoice").onclick = addVoices;
  $("openFolder").onclick = () => call("open_models_folder").catch(() => {});

  for (const b of $("latency").children) {
    b.onclick = async () => {
      if (b.dataset.value === ui.status.latency) return;
      for (const x of $("latency").children) x.classList.toggle("on", x === b);
      ui.busy = true;
      render(ui.status);
      try { await call("set_latency", { latency: b.dataset.value }); } catch { /* shown */ }
      ui.busy = false;
      render(ui.status);
    };
  }

  for (const b of $("fx").children) {
    b.onclick = () => call("set_fx", { [b.dataset.fx]: !ui.status.fx[b.dataset.fx] }).catch(() => {});
  }

  const sendSet = throttle((id, v) => call("set", { [id]: v }).catch(() => {}), 80);
  for (const id of Object.keys(SLIDERS)) {
    const el = $(id);
    el.addEventListener("input", () => {
      ui.editedAt[id] = Date.now();
      paintSlider(el);
      sendSet(id, Number(el.value));
    });
    el.addEventListener("dblclick", () => {
      const reset = { pitch: 0, index_rate: 0.75, in_gain: 1, out_vol: 1, monitor_vol: 1 }[id];
      el.value = reset;
      paintSlider(el);
      call("set", { [id]: reset }).catch(() => {});
    });
  }

  $("inputSel").onchange = (e) => call("set_devices", { input: e.target.value }).catch(() => {});
  $("outputSel").onchange = (e) => {
    call("set_devices", { output: e.target.value }).catch(() => {});
    renderOutputHint();
  };
  $("monitorSel").onchange = (e) => call("set_devices", { monitor: e.target.value }).catch(() => {});
  $("monitorOn").onchange = (e) => {
    const params = { use_monitor: e.target.checked };
    if (e.target.checked && !ui.status.devices.monitor && $("monitorSel").value) params.monitor = $("monitorSel").value;
    call("set_devices", params).catch(() => {});
  };

  engine.onFileDrop((e) => {
    if (e.type === "enter" || e.type === "over") $("dropOverlay").hidden = false;
    else if (e.type === "leave") $("dropOverlay").hidden = true;
    else if (e.type === "drop") {
      $("dropOverlay").hidden = true;
      importPaths(e.paths || []);
    }
  });

  if (!window.__TAURI__) {
    // The real engine catches F7/F8 globally; the preview fakes it.
    addEventListener("keydown", (e) => {
      if (e.key === "F8") call("toggle_bypass");
      if (e.key === "F7") call("toggle_mute");
    });
  }

  engine.on("state", render);
  engine.on("exit", async (info) => {
    const path = await engine.logPath().catch(() => null);
    overlay({
      title: "The voice engine stopped",
      text: path ? `Details are saved in ${path}` : "",
      spinner: false,
      log: info?.log_tail || `It exited with code ${info?.code ?? "unknown"}.`,
      actions: [{ label: "Restart engine", primary: true, onClick: boot }],
    });
  });
}

// ---- startup -------------------------------------------------------------

async function ensureBaseModels() {
  const hello = await engine.call("hello");
  if (hello.base_models_ready) return;
  overlay({
    title: "Setting up for the first time",
    text: "Downloading the shared voice models (about 550 MB). This only happens once.",
    spinner: false,
    progress: 0,
  });
  const onProgress = ({ done, total }) => {
    const mb = (n) => Math.round(n / 1e6);
    overlay({
      title: "Setting up for the first time",
      text: `Downloading the shared voice models: ${mb(done)} of ${mb(total)} MB. This only happens once.`,
      spinner: false,
      progress: total ? done / total : 0,
    });
  };
  engine.on("progress", onProgress);
  try {
    await engine.call("download_base_models");
  } finally {
    engine.handlers.progress = (engine.handlers.progress || []).filter((f) => f !== onProgress);
  }
}

async function boot() {
  overlay({ title: "Starting voice engine", text: "One moment…" });
  try {
    await engine.start();
    await ensureBaseModels();
    const [devices, status] = await Promise.all([engine.call("devices"), engine.call("status")]);
    renderDevices(devices);
    render(status);
    await refreshModels();
    overlay();
  } catch (err) {
    if (!$("overlayLog").hidden) return; // the engine crashed; its own screen is showing
    overlay({
      title: "Couldn't start",
      text: friendly(err),
      spinner: false,
      actions: [{ label: "Try again", primary: true, onClick: boot }],
    });
  }
}

wire();
boot();
