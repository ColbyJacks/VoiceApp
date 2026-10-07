// Voice App main process: window, tray, global hotkeys, settings, and the
// Python engine (engine/voiceapp_engine) spoken to over JSON lines.

const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, nativeImage, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const ROOT = path.resolve(__dirname, '..');
const ENGINE_DIR = path.join(ROOT, 'engine');
const VOICES_DIR = path.join(ROOT, 'voices');
const LOG_DIR = path.join(ROOT, 'logs');
const SETTINGS_FILE = path.join(ROOT, 'settings.json');
const ASSETS = path.join(__dirname, 'assets');

const captureArg = process.argv.find((a) => a.startsWith('--capture='));
const CAPTURE = captureArg ? captureArg.slice('--capture='.length) : null;
const delayArg = process.argv.find((a) => a.startsWith('--capture-delay='));
const CAPTURE_DELAY = delayArg ? Number(delayArg.slice('--capture-delay='.length)) : 6000;

// ---- settings ---------------------------------------------------------------

const DEFAULT_SETTINGS = {
  python: null, // path to python.exe; found automatically when null
  voice: null,
  devices: { input: null, output: null, monitor: null },
  monitorEnabled: false,
  legacyDevices: false,
  params: { pitch: 0, index_rate: 0.75, protect: 0.33, envelope: 1, in_gain: 1, out_vol: 1, monitor_vol: 0.8, gate_db: -50 },
  fx: {},
  preset: 'balanced',
  f0: null,
  hotkeys: { bypass: 'F8', mute: 'F7' },
  closeToTray: true,
  startOnLaunch: false,
};

function loadSettings() {
  try {
    const saved = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    return {
      ...DEFAULT_SETTINGS, ...saved,
      devices: { ...DEFAULT_SETTINGS.devices, ...saved.devices },
      params: { ...DEFAULT_SETTINGS.params, ...saved.params },
      hotkeys: { ...DEFAULT_SETTINGS.hotkeys, ...saved.hotkeys },
    };
  } catch {
    return structuredClone(DEFAULT_SETTINGS);
  }
}

let settings = loadSettings();
let saveTimer = null;
function saveSettings() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
    } catch (err) {
      console.error('Could not save settings:', err);
    }
  }, 300);
}

// ---- engine -------------------------------------------------------------------

function findPython() {
  const candidates = [
    settings.python,
    process.env.VOICEAPP_PYTHON,
    path.join(ROOT, 'python', 'python.exe'),
    path.join(ROOT, 'env', 'python.exe'),
    'E:\\Voice stuff\\env\\python.exe',
  ].filter(Boolean);
  return candidates.find((p) => fs.existsSync(p)) || 'python';
}

class Engine {
  constructor() {
    this.proc = null;
    this.pending = new Map();
    this.nextId = 1;
    this.state = null;
    this.stderrTail = [];
    this.status = { up: false, python: null, error: null };
  }

  start() {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    const python = findPython();
    const log = fs.createWriteStream(path.join(LOG_DIR, 'engine.log'), { flags: 'w' });
    log.write(`[app] starting engine with ${python}\n`);
    this.stderrTail = [];
    this.status = { up: true, python, error: null };
    sendToWindow('engine:status', this.status);

    const proc = spawn(python, ['-u', '-m', 'voiceapp_engine', '--voices', VOICES_DIR], {
      cwd: ENGINE_DIR,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    });
    this.proc = proc;

    readline.createInterface({ input: proc.stdout }).on('line', (line) => {
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        log.write(`[stdout] ${line}\n`);
        return;
      }
      if (msg.id !== undefined && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error !== undefined) reject(new Error(msg.error));
        else resolve(msg.result);
      } else if (msg.event) {
        if (msg.event === 'state') this.onState(msg.data);
        sendToWindow('engine:event', msg);
      }
    });

    proc.stderr.on('data', (chunk) => {
      log.write(chunk);
      this.stderrTail.push(...chunk.toString().split(/\r?\n/).filter(Boolean));
      this.stderrTail = this.stderrTail.slice(-30);
    });

    proc.on('error', (err) => {
      this.status = { up: false, python, error: `Couldn't start Python (${python}): ${err.message}` };
      sendToWindow('engine:status', this.status);
    });

    proc.on('exit', (code) => {
      log.end(`[app] engine exited with code ${code}\n`);
      if (this.proc !== proc) return; // replaced by a restart
      this.proc = null;
      for (const { reject } of this.pending.values()) reject(new Error('The engine stopped.'));
      this.pending.clear();
      if (!this.quitting) {
        this.status = {
          up: false, python, code,
          error: `The voice engine stopped (exit code ${code}).`,
          details: this.stderrTail.slice(-12).join('\n'),
        };
        sendToWindow('engine:status', this.status);
      }
    });
  }

  call(method, params = {}) {
    if (!this.proc) return Promise.reject(new Error('The voice engine is not running.'));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ id, method, params }) + '\n');
    });
  }

  onState(state) {
    this.state = state;
    updateTray();
  }

  stop() {
    this.quitting = true;
    if (this.proc) {
      try {
        this.proc.stdin.end();
      } catch {}
      const proc = this.proc;
      setTimeout(() => proc.kill(), 1500);
    }
  }

  restart() {
    const old = this.proc;
    this.proc = null;
    if (old) old.kill();
    this.quitting = false;
    this.start();
  }
}

const engine = new Engine();

// ---- window, tray, hotkeys ----------------------------------------------------

let win = null;
let tray = null;
let quitting = false;

function sendToWindow(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1220,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    show: false,
    backgroundColor: '#0f1018',
    title: 'Voice App',
    icon: path.join(ASSETS, 'icon.ico'),
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#0f1018', symbolColor: '#9aa0b8', height: 40 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.removeMenu();
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.once('ready-to-show', () => {
    if (!CAPTURE) win.show();
  });
  win.on('close', (e) => {
    if (!quitting && settings.closeToTray && !CAPTURE) {
      e.preventDefault();
      win.hide();
    }
  });
  // Links open in the browser, never inside the app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

function showWindow() {
  if (!win) return;
  win.show();
  win.focus();
}

function updateTray() {
  if (!tray) return;
  const s = engine.state || {};
  const live = s.running && !s.mute;
  tray.setImage(path.join(ASSETS, live ? 'tray-live.png' : 'tray.png'));
  const voice = s.voice && s.voice.name ? s.voice.name : 'no voice';
  const mode = !s.running ? 'Off' : s.mute ? 'Muted' : s.bypass ? 'Real voice' : `AI voice: ${voice}`;
  tray.setToolTip(`Voice App: ${mode}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: `Voice App: ${mode}`, enabled: false },
    { type: 'separator' },
    { label: 'Show Voice App', click: showWindow },
    { label: s.running ? 'Stop' : 'Start', click: () => engine.call(s.running ? 'stop' : 'start').catch(() => showWindow()) },
    { label: `Real voice (${settings.hotkeys.bypass})`, type: 'checkbox', checked: !!s.bypass, click: () => engine.call('toggle_bypass') },
    { label: `Mute (${settings.hotkeys.mute})`, type: 'checkbox', checked: !!s.mute, click: () => engine.call('toggle_mute') },
    { type: 'separator' },
    { label: 'Quit', click: () => { quitting = true; app.quit(); } },
  ]));
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(ASSETS, 'tray.png')));
  tray.on('click', showWindow);
  updateTray();
}

function registerHotkeys() {
  globalShortcut.unregisterAll();
  const failed = [];
  const bind = (accel, method) => {
    if (!accel) return;
    try {
      if (!globalShortcut.register(accel, () => engine.call(method).catch(() => {}))) failed.push(accel);
    } catch {
      failed.push(accel);
    }
  };
  bind(settings.hotkeys.bypass, 'toggle_bypass');
  bind(settings.hotkeys.mute, 'toggle_mute');
  return failed;
}

// ---- IPC ----------------------------------------------------------------------

ipcMain.handle('engine:call', (_e, method, params) => engine.call(method, params));
ipcMain.handle('engine:status', () => engine.status);
ipcMain.handle('engine:restart', () => engine.restart());

ipcMain.handle('settings:get', () => settings);
ipcMain.handle('settings:set', (_e, patch) => {
  settings = { ...settings, ...patch };
  saveSettings();
  if (patch.hotkeys) return { failedHotkeys: registerHotkeys() };
  return {};
});

ipcMain.handle('app:info', () => ({ root: ROOT, voices: VOICES_DIR, logs: LOG_DIR, version: app.getVersion() }));
ipcMain.handle('app:open-voices', () => {
  fs.mkdirSync(VOICES_DIR, { recursive: true });
  return shell.openPath(VOICES_DIR);
});
ipcMain.handle('app:open-logs', () => shell.openPath(path.join(LOG_DIR, 'engine.log')));
ipcMain.handle('app:pick-voices', async () => {
  const res = await dialog.showOpenDialog(win, {
    title: 'Add voices',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'RVC voices', extensions: ['pth', 'index'] }],
  });
  return res.canceled ? [] : res.filePaths;
});

ipcMain.on('renderer:ready', () => {
  if (!CAPTURE) return;
  // Screenshot mode for testing: wait for the UI to settle, save, quit.
  setTimeout(async () => {
    const image = await win.webContents.capturePage();
    fs.writeFileSync(CAPTURE, image.toPNG());
    quitting = true;
    app.quit();
  }, CAPTURE_DELAY);
});

// ---- lifecycle ------------------------------------------------------------------

if (!app.requestSingleInstanceLock() && !CAPTURE) {
  app.quit();
} else {
  app.on('second-instance', showWindow);
  app.whenReady().then(() => {
    app.setAppUserModelId('VoiceApp');
    createWindow();
    engine.start();
    if (!CAPTURE) {
      createTray();
      registerHotkeys();
    }
  });
  app.on('before-quit', () => {
    quitting = true;
    engine.stop();
  });
  app.on('will-quit', () => globalShortcut.unregisterAll());
  app.on('window-all-closed', () => app.quit());
}
