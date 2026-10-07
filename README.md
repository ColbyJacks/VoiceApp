# Voice App

Real-time AI voice changer for Windows. Pick an RVC voice (`.pth`), talk, and
Discord, games or OBS hear the converted voice.

**Start it:** double-click `Start Voice App.bat`.

## Using it

1. Pick a voice on the left. It loads onto the GPU in a few seconds.
2. Under **Audio**, choose your microphone and where to send the voice:
   - **CABLE Input** (VB-Audio Virtual Cable), then set Discord or your game's
     microphone to **CABLE Output**.
   - Or your speakers or headphones to just hear it yourself.
3. Press the big power button. The meters show your mic and the converted voice.

| | |
| --- | --- |
| **F8** | Switch between the AI voice and your real voice (works in any app) |
| **F7** | Mute |
| **Pitch** | +12 = one octave up (male voice → female model), −12 = one octave down |
| **Voice likeness** | How strongly to pull toward the voice's training data (needs its `.index`) |
| **Noise gate** | Raise it if keyboard or fan noise gets converted |
| **Hear myself** | Plays the converted voice in your headphones too |
| **Low delay / Balanced / Smooth** | Less delay vs. more headroom for slower GPUs or heavy games |

Double-click any slider to reset it. Closing the window keeps Voice App running
in the tray (switch that off under **Performance**). Right-click the tray icon
to quit.

**Adding voices:** drop `.pth` and `.index` files onto the window, click **＋**,
or put them in `voices\`. An index is matched to its voice by name, for example
`Markiplier-V2.index` goes with `Markiplier-V2_320e_16960s.pth`.

## Folders

```
Start Voice App.bat   starts the app
voices\               your .pth and .index files
settings.json         your choices (devices, voice, sliders), saved automatically
logs\engine.log       the engine's output, for troubleshooting
app\                  the window (Electron: main.js, preload.js, renderer\)
engine\               the voice engine (Python)
  voiceapp_engine\    audio streams, conversion, effects, JSON protocol
  rvc\                RVC inference code (from Applio, MIT licensed)
  rvc\models\         base models: contentvec, rmvpe, fcpe
```

## Requirements

- **Node.js** (for the window). The first start runs `npm install` in `app\`.
- **Python 3.12 with PyTorch (CUDA)** and the voice libraries. Voice App looks for,
  in order: `"python"` in `settings.json`, the `VOICEAPP_PYTHON` environment
  variable, `python\python.exe` or `env\python.exe` next to this README, then
  `E:\Voice stuff\env\python.exe`. The engine needs: torch, torchaudio,
  numpy, scipy, sounddevice, soundfile, pedalboard, noisereduce, faiss-cpu,
  transformers, torchcrepe, torchfcpe, einops, webrtcvad-wheels, librosa.
- An NVIDIA GPU. It runs on the CPU without one, but probably won't keep up.

## How it works

The window (Electron) starts the engine (`python -m voiceapp_engine` in
`engine\`) and talks to it with one JSON message per line over stdin/stdout. The
methods and events are listed at the top of `engine/voiceapp_engine/server.py`.

Audio path:

```
mic ─▶ input stream (one block) ─▶ converter thread ─▶ output buffer ─▶ CABLE / speakers
        gain · noise gate            RVC voice · effects · volume · limiter   └▶ headphones (Hear myself)
```

Delay ≈ one block (Balanced: 171 ms) + conversion time (~60 ms on an RTX 3090 Ti)
+ a 40 ms safety buffer + the output device's buffer. The app shows the live
figure under the meters.

Fixes compared with the old tray app (`voice_tray_app.py`):

- **Devices:** only WASAPI devices are listed by default (MME/DirectSound
  optional). WDM-KS devices are never offered: the old app mislabeled them as MME,
  and opening them failed with "Invalid device".
- **Devices are remembered by name**, not by an index that changes whenever
  something is plugged in.
- **About half the delay:** smaller blocks, a small output buffer instead of a
  whole extra block, and no ~1 s of silence each time it starts.
- **No first-block stall:** each voice is warmed up on the GPU when it loads.
- **Voices pair only with their own index.** The old app fell back to the first
  `.index` in the folder, which blended voices.
- The limiter no longer adds ~4 dB of hidden gain.
- Switching voices, effects, Hear myself or delay settings works while live.
- Device and stream calls run on one thread with Windows COM set up. WASAPI
  streams fail to start from other threads.
