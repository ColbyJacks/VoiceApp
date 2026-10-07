'use strict';
// Voice App renderer. All audio work happens in the Python engine; this page
// shows its state and sends it commands through window.voiceapp (preload.js).

const api = window.voiceapp;
const $ = (id) => document.getElementById(id);

let settings = null;
let engineState = null;
let voices = [];
let deviceList = { inputs: [], outputs: [], defaults: {} };
let engineReady = false;

const PRESET_HELP = {
  low: 'About 85 ms blocks with the fast FCPE pitch detector: least delay, a little less accurate pitch.',
  balanced: 'About 170 ms blocks with RMVPE pitch detection: good quality with moderate delay.',
  safe: 'About 256 ms blocks: the most headroom for slower GPUs or heavy games, with the most delay.',
};

// ---------------------------------------------------------------- helpers

function toast(message, level = 'info', ms = 5000) {
  const el = document.createElement('div');
  el.className = `toast ${level}`;
  el.textContent = message;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

async function call(method, params = {}, { quiet = false } = {}) {
  try {
    return await api.call(method, params);
  } catch (err) {
    if (!quiet) toast(err.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''), 'error', 7000);
    throw err;
  }
}

function save(patch) {
  Object.assign(settings, patch);
  return api.saveSettings(patch);
}

function throttle(fn, ms) {
  let last = 0, timer = null, args = null;
  return (...a) => {
    args = a;
    const now = Date.now();
    if (now - last >= ms) {
      last = now;
      fn(...args);
    } else {
      clearTimeout(timer);
      timer = setTimeout(() => { last = Date.now(); fn(...args); }, ms - (now - last));
    }
  };
}

function hue(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

const toDb = (rms) => (rms > 1e-6 ? 20 * Math.log10(rms) : -Infinity);
const dbToPct = (db) => Math.max(0, Math.min(100, ((db + 60) / 60) * 100));

const FORMATS = {
  pct: (v) => `${Math.round(v * 100)}%`,
  x: (v) => `${(+v).toFixed(2)}×`,
  db: (v) => `${Math.round(v)} dB`,
  protect: (v) => (v >= 0.5 ? 'off' : `${Math.round((0.5 - v) * 200)}%`),
  envelope: (v) => (v >= 1 ? 'off' : `${Math.round((1 - v) * 100)}%`),
};
function formatValue(input) {
  const v = parseFloat(input.value);
  const fmt = FORMATS[input.dataset.fmt];
  if (fmt) return fmt(v);
  return v > 0 ? `+${v}` : `${v}`;
}
function paintRange(input) {
  const pct = ((input.value - input.min) / (input.max - input.min)) * 100;
  input.style.setProperty('--pct', `${pct}%`);
  const out = $(`${input.id}Out`);
  if (out) out.textContent = formatValue(input);
}

// ---------------------------------------------------------------- engine state

function applyState(s) {
  engineState = s;
  const hero = $('hero');
  const voice = s.voice || {};
  const live = s.running && !s.mute;
  hero.classList.toggle('live', live && !s.bypass);
  hero.classList.toggle('real', live && s.bypass);
  hero.classList.toggle('muted', s.running && s.mute);
  hero.classList.toggle('starting', !!s.starting);

  let label = 'Off';
  if (s.starting) label = 'Starting…';
  else if (s.running && s.mute) label = 'Muted';
  else if (s.running && s.bypass) label = 'Live · real voice';
  else if (s.running && voice.status === 'loading') label = 'Live · loading voice…';
  else if (s.running && voice.status === 'ready') label = 'Live · AI voice';
  else if (s.running) label = 'Live · real voice (no voice loaded)';
  $('heroLabel').textContent = label;
  $('power').setAttribute('aria-label', s.running ? 'Stop voice changer' : 'Start voice changer');

  const current = voices.find((v) => v.name === voice.name);
  $('heroVoice').textContent = voice.name ? (current ? current.label : voice.name) : 'Real voice only';

  const chips = [];
  if (voice.status === 'loading') chips.push(['Loading voice…', '']);
  if (voice.status === 'error') chips.push(['Voice failed to load', 'bad']);
  if (voice.status === 'ready') {
    chips.push([`${voice.version} · ${Math.round(voice.sample_rate / 1000)} kHz`, '']);
    chips.push([voice.index ? 'index ✓' : 'no index', voice.index ? 'good' : 'bad']);
  }
  if (s.gpu && s.gpu.status === 'loading') chips.push(['Loading GPU…', '']);
  else if (s.gpu && s.gpu.cuda === false) chips.push(['CPU only', 'bad']);
  chips.push([`${s.block_ms} ms blocks · ${s.f0.toUpperCase()}`, '']);
  $('heroChips').replaceChildren(...chips.map(([t, cls]) => {
    const el = document.createElement('span');
    el.className = `chip ${cls}`;
    el.textContent = t;
    return el;
  }));

  $('modeAi').classList.toggle('on', !s.bypass);
  $('modeReal').classList.toggle('on', s.bypass);
  $('muteBtn').classList.toggle('on', s.mute);
  $('muteBtn').querySelector('span').textContent = s.mute ? 'Muted' : 'Mute';

  for (const b of document.querySelectorAll('#presets button')) b.classList.toggle('on', b.dataset.preset === s.preset);
  $('presetHelp').textContent = PRESET_HELP[s.preset] || '';
  for (const b of document.querySelectorAll('.fx')) b.classList.toggle('on', !!(s.fx && s.fx[b.dataset.fx]));
  for (const el of document.querySelectorAll('.fx-opt')) el.classList.toggle('show', !!(s.fx && s.fx[el.dataset.for]));
  // Effect sliders follow the engine (its defaults fill in anything not saved yet).
  for (const input of document.querySelectorAll('input[data-fxparam]')) {
    const v = s.fx && s.fx[input.dataset.fxparam];
    if (v !== undefined && document.activeElement !== input && parseFloat(input.value) !== v) {
      input.value = v;
      paintRange(input);
    }
  }

  const gpu = s.gpu || {};
  $('gpuInfo').textContent = gpu.status === 'ready' ? gpu.name : gpu.status === 'error' ? 'GPU error' : 'Loading GPU…';
  $('titleStatus').textContent = s.running ? label : voice.status === 'loading' ? 'Loading voice…' : 'Ready';
  if (!s.running) {
    $('stats').textContent = s.error ? s.error : 'Not running. Press the power button to start.';
    resetMeters();
  }
  renderVoices();
}

function resetMeters() {
  for (const id of ['meterIn', 'meterOut']) {
    $(id).querySelector('.fill').style.width = '0';
    $(id).querySelector('.peak').style.left = '0';
  }
  $('dbIn').textContent = '–∞';
  $('dbOut').textContent = '–∞';
}

function applyLevels(l) {
  const setMeter = (id, rms, peak, dbId) => {
    const m = $(id);
    m.querySelector('.fill').style.width = `${dbToPct(toDb(rms))}%`;
    m.querySelector('.peak').style.left = `calc(${dbToPct(toDb(peak))}% - 2px)`;
    const db = toDb(rms);
    $(dbId).textContent = Number.isFinite(db) ? `${db.toFixed(0)} dB` : '–∞';
  };
  setMeter('meterIn', l.in, l.in_peak, 'dbIn');
  setMeter('meterOut', l.out, l.out_peak, 'dbOut');
  const load = Math.round(l.load * 100);
  const loadCls = load > 90 ? ' class="hot"' : load > 70 ? ' class="warm"' : '';
  $('stats').innerHTML =
    `Delay ≈ <b>${l.latency_ms} ms</b> · conversion <b>${l.proc_ms} ms</b> per block · GPU busy <b${loadCls}>${load}%</b>` +
    (l.underruns || l.dropped ? ` · glitches <b>${l.underruns + l.dropped}</b>` : '');
}

function paintGate() {
  $('gateMark').style.left = `${dbToPct(parseFloat($('gate_db').value))}%`;
}

// ---------------------------------------------------------------- voices

function micIcon() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  for (const d of ['M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z', 'M19 11a7 7 0 0 1-14 0', 'M12 18v3']) {
    const p = document.createElementNS(ns, 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
  }
  return svg;
}

function renderVoices() {
  const q = $('voiceSearch').value.trim().toLowerCase();
  const current = engineState && engineState.voice ? engineState.voice : {};
  const list = $('voiceList');
  const items = [];

  const make = (name, label, sub, isReal) => {
    const el = document.createElement('button');
    el.className = 'voice';
    el.setAttribute('role', 'option');
    const active = isReal ? !current.name : current.name === name;
    el.classList.toggle('active', active);
    el.setAttribute('aria-selected', active);
    const av = document.createElement('div');
    av.className = 'avatar';
    if (isReal) av.appendChild(micIcon());
    else av.textContent = label.replace(/[^A-Za-z0-9]/g, '').slice(0, 1).toUpperCase() || '?';
    av.style.background = isReal ? '#3a3f5c' : `hsl(${hue(label)} 55% 42%)`;
    const text = document.createElement('div');
    text.className = 'voice-text';
    const n = document.createElement('div');
    n.className = 'voice-name';
    n.textContent = label;
    const s = document.createElement('div');
    s.className = 'voice-sub';
    s.innerHTML = sub;
    text.append(n, s);
    el.append(av, text);
    if (active && current.status === 'loading') {
      const sp = document.createElement('div');
      sp.className = 'spinner';
      el.append(sp);
    }
    el.addEventListener('click', () => selectVoice(isReal ? null : name));
    return el;
  };

  if (!q || 'real voice'.includes(q)) items.push(make(null, 'Real voice', 'No AI, just your mic', true));
  for (const v of voices) {
    if (q && !v.label.toLowerCase().includes(q) && !v.name.toLowerCase().includes(q)) continue;
    let sub = v.index ? `${v.size_mb} MB · index ✓` : `${v.size_mb} MB · <span class="warn">no index</span>`;
    if (current.name === v.name && current.status === 'error') sub = '<span class="warn">Failed to load</span>';
    items.push(make(v.name, v.label, sub, false));
  }
  if (!voices.length) {
    const empty = document.createElement('div');
    empty.className = 'voice-empty';
    empty.textContent = 'No voices yet. Add .pth files with ＋ or drop them here.';
    items.push(empty);
  }
  list.replaceChildren(...items);
}

async function refreshVoices() {
  voices = await call('list_voices');
  renderVoices();
}

async function selectVoice(name) {
  save({ voice: name });
  await call('load_voice', { name });
}

async function importVoices(paths) {
  if (!paths.length) return;
  const res = await call('import_voices', { paths });
  voices = res.voices;
  renderVoices();
  if (res.copied.length) {
    toast(`Added ${res.copied.join(', ')}`);
    const pth = res.copied.find((n) => n.toLowerCase().endsWith('.pth'));
    if (pth) selectVoice(pth.replace(/\.pth$/i, ''));
  }
}

// ---------------------------------------------------------------- devices

function fillSelect(select, list, selectedId, placeholder) {
  const groups = {};
  for (const d of list) (groups[d.api] = groups[d.api] || []).push(d);
  const nodes = [];
  if (selectedId && !list.some((d) => d.id === selectedId)) {
    const o = new Option(`${selectedId.split('::')[1]} (not connected)`, selectedId);
    nodes.push(o);
  }
  if (!selectedId) nodes.push(new Option(placeholder, ''));
  for (const [apiName, devs] of Object.entries(groups)) {
    const g = document.createElement('optgroup');
    g.label = apiName === 'WASAPI' ? 'Windows audio (WASAPI)' : apiName;
    for (const d of devs) g.appendChild(new Option(d.name, d.id));
    nodes.push(g);
  }
  select.replaceChildren(...nodes);
  select.value = selectedId || '';
}

async function refreshDevices() {
  deviceList = await call('list_devices', { include_legacy: !!settings.legacyDevices });
  const d = { ...settings.devices };
  const has = (list, id) => id && list.some((x) => x.id === id);
  // First run: your default mic, VB-Cable if installed, default speakers for monitoring.
  if (!d.input) d.input = deviceList.defaults.input;
  if (!d.output) d.output = deviceList.defaults.cable || deviceList.defaults.output;
  if (!d.monitor || d.monitor === d.output) {
    d.monitor = has(deviceList.outputs, deviceList.defaults.output) && deviceList.defaults.output !== d.output
      ? deviceList.defaults.output
      : d.monitor;
  }
  fillSelect($('inputDev'), deviceList.inputs, d.input, 'Choose a microphone');
  fillSelect($('outputDev'), deviceList.outputs, d.output, 'Choose an output');
  fillSelect($('monitorDev'), deviceList.outputs, d.monitor, 'Choose headphones');
  $('cableHelp').classList.toggle('hidden', !deviceList.defaults.cable && !(d.output || '').toLowerCase().includes('cable'));
  if (!deviceList.defaults.cable) {
    $('cableHelp').classList.remove('hidden');
    $('cableHelp').innerHTML = 'To use the voice in Discord or games, install <b>VB-Audio Virtual Cable</b>, then choose <b>CABLE Input</b> here.';
  }
  save({ devices: d });
  await pushDevices();
}

async function pushDevices() {
  const d = settings.devices;
  await call('set_devices', { input: d.input, output: d.output, monitor: d.monitor });
}

// ---------------------------------------------------------------- controls

function bindRanges() {
  const pushParam = throttle((name, value) => call('set', { [name]: value }, { quiet: true }).catch(() => {}), 40);
  const pushFx = throttle((name, value) => call('set_fx', { [name]: value }, { quiet: true }).catch(() => {}), 80);
  for (const input of document.querySelectorAll('input[type=range]')) {
    const param = input.dataset.param;
    const fxParam = input.dataset.fxparam;
    if (param) input.value = settings.params[param];
    if (fxParam && settings.fx[fxParam] !== undefined) input.value = settings.fx[fxParam];
    paintRange(input);
    input.addEventListener('input', () => {
      paintRange(input);
      const v = parseFloat(input.value);
      if (param) pushParam(param, v);
      if (fxParam) pushFx(fxParam, v);
      if (input.id === 'gate_db') paintGate();
    });
    input.addEventListener('change', () => {
      const v = parseFloat(input.value);
      if (param) save({ params: { ...settings.params, [param]: v } });
      if (fxParam) save({ fx: { ...settings.fx, [fxParam]: v } });
    });
    // Double-click a slider to reset it.
    input.addEventListener('dblclick', () => {
      const defaults = { pitch: 0, index_rate: 0.75, protect: 0.33, envelope: 1, in_gain: 1, out_vol: 1, monitor_vol: 0.8, gate_db: -50 };
      if (param && defaults[param] !== undefined) {
        input.value = defaults[param];
        input.dispatchEvent(new Event('input'));
        input.dispatchEvent(new Event('change'));
      }
    });
  }
  for (const b of document.querySelectorAll('[data-pitch]')) {
    b.addEventListener('click', () => {
      const p = $('pitch');
      p.value = b.dataset.pitch;
      p.dispatchEvent(new Event('input'));
      p.dispatchEvent(new Event('change'));
    });
  }
  paintGate();
}

function bindControls() {
  $('power').addEventListener('click', async () => {
    if (!engineState) return;
    if (engineState.running) return call('stop');
    if (!settings.devices.input || !settings.devices.output) {
      toast('Choose a microphone and an output first.', 'warn');
      return;
    }
    // Errors arrive as an engine log event, which shows a toast.
    await call('start', {}, { quiet: true }).catch(() => {});
  });
  $('modeAi').addEventListener('click', () => call('set_bypass', { value: false }));
  $('modeReal').addEventListener('click', () => call('set_bypass', { value: true }));
  $('muteBtn').addEventListener('click', () => call('toggle_mute'));

  const onDevice = (key) => async (e) => {
    save({ devices: { ...settings.devices, [key]: e.target.value || null } });
    await pushDevices().catch(() => {});
  };
  $('inputDev').addEventListener('change', onDevice('input'));
  $('outputDev').addEventListener('change', onDevice('output'));
  $('monitorDev').addEventListener('change', onDevice('monitor'));

  $('monitorOn').checked = !!settings.monitorEnabled;
  $('monitorOpts').classList.toggle('hidden', !settings.monitorEnabled);
  $('monitorOn').addEventListener('change', async (e) => {
    save({ monitorEnabled: e.target.checked });
    $('monitorOpts').classList.toggle('hidden', !e.target.checked);
    if (e.target.checked && settings.devices.monitor && settings.devices.monitor === settings.devices.output) {
      toast('Pick your headphones for "Hear myself", not the same device as the voice output.', 'warn');
    }
    await call('set_monitor', { enabled: e.target.checked }).catch(() => {});
  });

  $('legacyDevs').checked = !!settings.legacyDevices;
  $('legacyDevs').addEventListener('change', async (e) => {
    save({ legacyDevices: e.target.checked });
    if (engineState && engineState.running) toast('The device list refreshes after you stop the voice changer.', 'warn');
    else refreshDevices();
  });

  for (const b of document.querySelectorAll('.fx')) {
    b.addEventListener('click', () => {
      const on = !(engineState && engineState.fx && engineState.fx[b.dataset.fx]);
      save({ fx: { ...settings.fx, [b.dataset.fx]: on } });
      call('set_fx', { [b.dataset.fx]: on });
    });
  }
  for (const b of document.querySelectorAll('#presets button')) {
    b.addEventListener('click', () => {
      save({ preset: b.dataset.preset });
      call('set_performance', { preset: b.dataset.preset });
    });
  }
  $('f0').value = settings.f0 || '';
  $('f0').addEventListener('change', (e) => {
    save({ f0: e.target.value || null });
    call('set_performance', { f0: e.target.value || null });
  });
  $('closeToTray').checked = !!settings.closeToTray;
  $('closeToTray').addEventListener('change', (e) => save({ closeToTray: e.target.checked }));
  $('startOnLaunch').checked = !!settings.startOnLaunch;
  $('startOnLaunch').addEventListener('change', (e) => save({ startOnLaunch: e.target.checked }));

  $('voiceSearch').addEventListener('input', renderVoices);
  $('openVoices').addEventListener('click', () => api.openVoicesFolder());
  $('addVoices').addEventListener('click', async () => importVoices(await api.pickVoiceFiles()));
  $('openLogs').addEventListener('click', () => api.openLogs());
  $('overlayLogs').addEventListener('click', () => api.openLogs());
  $('restartEngine').addEventListener('click', () => {
    showOverlay('Starting the voice engine…', 'Loading PyTorch and your GPU.');
    api.restartEngine();
    connect();
  });
  $('muteKey').textContent = settings.hotkeys.mute;
  $('bypassKey').textContent = settings.hotkeys.bypass;

  // Drag and drop voices.
  let depth = 0;
  window.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; $('dropZone').classList.remove('hidden'); });
  window.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; $('dropZone').classList.add('hidden'); } });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    depth = 0;
    $('dropZone').classList.add('hidden');
    importVoices([...e.dataTransfer.files].map((f) => api.pathForFile(f)).filter(Boolean));
  });
}

// ---------------------------------------------------------------- startup

function showOverlay(title, text, details, actions = false) {
  $('engineOverlay').classList.remove('hidden');
  $('overlayTitle').textContent = title;
  $('overlayText').textContent = text;
  $('overlayDetails').classList.toggle('hidden', !details);
  $('overlayDetails').textContent = details || '';
  $('overlayActions').classList.toggle('hidden', !actions);
}

api.onEngineStatus((status) => {
  if (!status.up && status.error) {
    engineReady = false;
    showOverlay(
      'The voice engine isn\'t running',
      `${status.error} Python: ${status.python || 'not found'}`,
      status.details,
      true,
    );
  }
});

api.onEvent((msg) => {
  if (msg.event === 'state') applyState(msg.data);
  else if (msg.event === 'levels') applyLevels(msg.data);
  else if (msg.event === 'log' && msg.data.level !== 'info') toast(msg.data.message, msg.data.level, 7000);
});

async function connect() {
  // The engine answers "hello" as soon as Python is up (torch loads after).
  for (let i = 0; i < 120; i++) {
    try {
      const state = await api.call('hello');
      engineReady = true;
      $('engineOverlay').classList.add('hidden');
      applyState(state);
      await configureEngine();
      return;
    } catch {
      const status = await api.engineStatus();
      if (!status.up && status.error) return; // overlay already shows the error
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  showOverlay('The voice engine didn\'t respond', 'Open the log to see what went wrong.', null, true);
}

async function configureEngine() {
  await call('set', settings.params).catch(() => {});
  await call('set_fx', settings.fx).catch(() => {});
  if (settings.preset !== 'balanced' || settings.f0) {
    await call('set_performance', { preset: settings.preset, f0: settings.f0 }).catch(() => {});
  }
  await refreshDevices().catch(() => {});
  if (settings.monitorEnabled) await call('set_monitor', { enabled: true }).catch(() => {});
  await refreshVoices().catch(() => {});
  if (settings.voice && voices.some((v) => v.name === settings.voice)) {
    await call('load_voice', { name: settings.voice }).catch(() => {});
  } else if (!settings.voice && voices.length === 0) {
    toast('Add a voice (.pth) to get started: click ＋ or drop the file on the window.');
  }
  if (settings.startOnLaunch && settings.devices.input && settings.devices.output) {
    call('start').catch(() => {});
  }
  api.ready();
}

async function main() {
  settings = await api.getSettings();
  bindRanges();
  bindControls();
  showOverlay('Starting the voice engine…', 'Loading Python. This takes a few seconds.');
  connect();
}

main();
