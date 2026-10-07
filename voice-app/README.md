# Voice App

Real-time voice changer for Windows. A small Tauri window (this folder) runs
the Python voice engine (`../voiceapp/engine`, which uses the shared RVC code
in `../core`) in the background and talks to it over stdin/stdout.

```
voice-app/
  ui/            the interface: plain HTML/CSS/JS, no build step
  src-tauri/     the window: starts the engine, relays its messages
  engine/        PyInstaller spec that packages the engine as voiceapp-engine.exe
  scripts/       build-windows.ps1 (full build), preview.mjs (browser preview)
```

## What it does

- Voice cards: click one to switch voices, even while live. Drag a `.pth`
  (with its `.index` next to it) onto the window, or use **Add voice**.
- Microphone and output pickers with level meters. Only WASAPI devices are
  listed, and they're remembered by name.
- Pitch, voice match (index strength), mic boost and output volume.
- Effects: reverb, echo, robot, radio.
- Delay presets: Low 128 ms (default), Balanced 192 ms, Safe 256 ms.
- F8 switches to your real voice, F7 mutes; both work while a game has focus.
- "Hear myself" plays the result on a second device.
- First run downloads the shared base models (about 550 MB) if the build
  didn't include them.
- Everything is saved in `%APPDATA%\VoiceApp\settings.json`; voices live in
  `%APPDATA%\VoiceApp\models`.

## Build on Windows

Needs: a Python with `voiceapp\requirements.txt` (GPU torch), plus Node 20+
and Rust (`winget install Rustlang.Rustup`, with the MSVC build tools) for the
window. To skip Rust and Node, download `voice-app.exe` from the
"Voice App window" GitHub Actions run and pass it with `-ShellExe`.

```powershell
cd voice-app
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1 `
    -Python "E:\Voice stuff\env\python.exe" `
    -BaseModels "E:\Voice stuff" `
    -Voices "E:\Voice stuff\models" `
    -Out "$env:USERPROFILE\Desktop\Voice App (new)"
```

Result:

```
Voice App (new)\
  Voice App.exe
  engine\voiceapp-engine.exe, _internal\, rvc\models\
```

Check an engine build without the window:
`engine\voiceapp-engine.exe --selftest path\to\voice.pth`.

The engine's log is in `%APPDATA%\com.colbyjacks.voiceapp\logs\engine.log`;
if the engine stops, the window shows the end of it with a restart button.

## Develop

```powershell
npm install
$env:VOICEAPP_ENGINE_PYTHON = "E:\Voice stuff\env\python.exe"   # runs the engine from ../voiceapp/engine/src
npm run dev
```

`npm run preview` serves the interface in a browser with a mock engine
(add `?firstrun`, `?empty` or `?crash` to the URL to see those screens).

Engine tests: `python -m pytest voiceapp/engine/tests` from the repo root.

## Talking to the engine

One JSON object per line. Requests `{"id", "method", "params"}` get
`{"id", "result"}` or `{"id", "error"}`; the engine also pushes
`{"event": "state" | "progress" | "hotkey" | "ready", "data"}`. Methods:
`hello`, `status`, `devices`, `set_devices`, `list_models`, `load_model`,
`import_model`, `open_models_folder`, `set`, `set_latency`, `set_fx`,
`toggle_bypass`, `toggle_mute`, `start`, `stop`, `download_base_models`.
See `../voiceapp/engine/src/voiceapp_engine/protocol.py`.
