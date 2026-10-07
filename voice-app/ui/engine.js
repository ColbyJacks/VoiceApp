// Talks to the Python voice engine. Inside the app that goes through the
// Tauri shell (engine_start / engine_send, engine-line / engine-exit events);
// in a plain browser a mock engine stands in so the UI can be previewed.

class TauriEngine {
  constructor() {
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = {};
    const { core, event } = window.__TAURI__;
    this.invoke = core.invoke;
    event.listen("engine-line", (e) => this._line(e.payload));
    event.listen("engine-exit", (e) => {
      for (const { reject } of this.pending.values()) reject(new Error("The voice engine stopped"));
      this.pending.clear();
      this._emit("exit", e.payload);
    });
  }

  on(name, fn) { (this.handlers[name] ||= []).push(fn); }
  _emit(name, data) { for (const fn of this.handlers[name] || []) fn(data); }

  _line(line) {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.event) return this._emit(msg.event, msg.data);
    const p = this.pending.get(msg.id);
    if (!p) return;
    this.pending.delete(msg.id);
    msg.error !== undefined ? p.reject(new Error(msg.error)) : p.resolve(msg.result);
  }

  start() { return this.invoke("engine_start"); }

  call(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.invoke("engine_send", { line: JSON.stringify({ id, method, params }) }).catch((err) => {
        this.pending.delete(id);
        reject(new Error(String(err)));
      });
    });
  }

  logPath() { return this.invoke("engine_log_path"); }

  async pickFiles() {
    const picked = await window.__TAURI__.dialog.open({
      multiple: true,
      title: "Add voices",
      filters: [{ name: "Voice model", extensions: ["pth"] }],
    });
    if (!picked) return [];
    return Array.isArray(picked) ? picked : [picked];
  }

  onFileDrop(fn) {
    window.__TAURI__.webview.getCurrentWebview().onDragDropEvent((e) => fn(e.payload));
  }
}

// ---------------------------------------------------------------------------

const LATENCY_MS = { low: 128, balanced: 192, safe: 256 };

class MockEngine {
  constructor() {
    const q = new URLSearchParams(location.search);
    this.handlers = {};
    this.baseReady = !q.has("firstrun");
    this.failBoot = q.has("crash");
    this.models = q.has("empty") ? [] : [
      { name: "AM", has_index: true, size_mb: 55.2 },
      { name: "AnimeYan", has_index: true, size_mb: 55.1 },
      { name: "Deep Narrator", has_index: false, size_mb: 57.6 },
      { name: "Robo Girl", has_index: true, size_mb: 55.0 },
      { name: "Villain", has_index: true, size_mb: 54.8 },
      { name: "Old Man Jenkins", has_index: false, size_mb: 56.3 },
      { name: "Kid Voice", has_index: true, size_mb: 55.4 },
    ];
    this.devs = {
      inputs: ["Microphone (HyperX SoloCast)", "Microphone Array (Realtek(R) Audio)", "CABLE Output (VB-Audio Virtual Cable)"],
      outputs: ["CABLE Input (VB-Audio Virtual Cable)", "Speakers (Realtek(R) Audio)", "Headphones (HyperX Cloud II)"],
    };
    this.s = {
      phase: "off", running: false, model: null, saved_model: q.has("empty") ? null : "AnimeYan",
      latency: "low", latency_ms: 128, pitch: 0, index_rate: 0.75, in_gain: 1, out_vol: 1,
      monitor_vol: 1, use_monitor: false, bypassed: false, muted: false,
      devices: { input: this.devs.inputs[0], output: this.devs.outputs[0], monitor: null },
      fx: { reverb: false, delay: false, chorus: false, radio: false },
      levels: { in: 0, out: 0 }, block_ms: null, load_ms: null, last_error: null,
    };
    this.warm = 0;
    setInterval(() => this._tick(), 100);
  }

  on(name, fn) { (this.handlers[name] ||= []).push(fn); }
  _emit(name, data) { for (const fn of this.handlers[name] || []) fn(data); }
  _status() {
    const s = this.s;
    s.phase = s.loading ? "loading" : !s.running ? "off" : s.muted ? "muted" : s.bypassed ? "real" : this.warm > 0 && s.model ? "warming" : "live";
    s.latency_ms = LATENCY_MS[s.latency];
    return structuredClone(s);
  }
  _tick() {
    if (!this.s.running) return;
    if (this.warm > 0) this.warm--;
    const t = Date.now() / 1000;
    const talk = Math.max(0, Math.sin(t * 1.3) * 0.5 + Math.sin(t * 3.7) * 0.3 + 0.25);
    const v = Math.min(1, talk * (0.75 + Math.random() * 0.25));
    this.s.levels = { in: v, out: this.s.muted ? 0 : v * 0.92 };
    this.s.block_ms = 38 + Math.round(Math.random() * 8);
    this._emit("state", this._status());
  }
  _wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

  async start() {
    await this._wait(500);
    if (this.failBoot) {
      setTimeout(() => this._emit("exit", { code: 1, log_tail: "Traceback (most recent call last):\n  File \"voiceapp_engine\\__main__.py\", line 12\nOSError: [WinError 126] The specified module could not be found. Error loading \"torch\\lib\\c10.dll\"" }), 50);
      return;
    }
    setTimeout(() => this._emit("ready", {}), 50);
  }
  logPath() { return Promise.resolve("C:\\Users\\you\\AppData\\Roaming\\com.colbyjacks.voiceapp\\logs\\engine.log"); }
  async pickFiles() { return ["C:\\Users\\you\\Downloads\\Narrator.pth"]; }
  onFileDrop() {}

  async call(method, p = {}) {
    if (this.failBoot) return new Promise(() => {}); // a dead engine never answers
    await this._wait(30);
    const s = this.s;
    switch (method) {
      case "hello": return { engine: "mock", core: "mock", base_models_ready: this.baseReady, models_folder: "C:\\Users\\you\\AppData\\Roaming\\VoiceApp\\models" };
      case "status": return this._status();
      case "devices": return { ...this.devs, ...s.devices, use_monitor: s.use_monitor };
      case "list_models": return structuredClone(this.models);
      case "set_devices":
        if (p.input != null) s.devices.input = p.input;
        if (p.output != null) s.devices.output = p.output;
        if (p.monitor != null) s.devices.monitor = p.monitor;
        if (p.use_monitor != null) s.use_monitor = p.use_monitor;
        return this._status();
      case "load_model": {
        if (!p.model) { s.model = null; return this._status(); }
        s.loading = true;
        this._emit("state", this._status());
        await this._wait(900);
        s.loading = false;
        s.model = s.saved_model = p.model;
        s.load_ms = 1840;
        this.warm = 6;
        return this._status();
      }
      case "import_model": {
        const name = p.path.split(/[\\/]/).pop().replace(/\.pth$/i, "");
        if (!this.models.some((m) => m.name === name)) this.models.push({ name, has_index: false, size_mb: 55 });
        this.models.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
        return { name, has_index: false };
      }
      case "open_models_folder": return this._status();
      case "set": Object.assign(s, p); return this._status();
      case "set_latency": await this._wait(400); s.latency = p.latency; this.warm = 5; return this._status();
      case "set_fx": Object.assign(s.fx, p); return this._status();
      case "toggle_bypass": s.bypassed = !s.bypassed; return this._status();
      case "toggle_mute": s.muted = !s.muted; return this._status();
      case "start":
        if (!s.model && s.saved_model) await this.call("load_model", { model: s.saved_model });
        await this._wait(250);
        s.running = true; this.warm = 6;
        return this._status();
      case "stop": s.running = false; s.levels = { in: 0, out: 0 }; return this._status();
      case "download_base_models": {
        const total = 554_000_000;
        for (let done = 0; done <= total; done += total / 40) {
          this._emit("progress", { done, total });
          await this._wait(60);
        }
        this.baseReady = true;
        return { base_models_ready: true };
      }
      default: throw new Error(`unknown method '${method}'`);
    }
  }
}

export function createEngine() {
  return window.__TAURI__ ? new TauriEngine() : new MockEngine();
}
