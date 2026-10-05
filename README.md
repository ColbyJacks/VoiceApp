# VoiceApp

Voice modulation app. 1 .pth is all you need to get started.

This repository holds two Windows apps that share one small core:

| Folder | What it is | Who needs it |
| --- | --- | --- |
| `voiceapp/` | **Voice App**: real-time voice changing with an RVC `.pth` model | Everyone. Easy install, no training libraries. |
| `studio/` | **VoiceAppStudio**: prepares recordings and trains `.pth` models | Only people making their own voices. |
| `core/` | `voiceapp-core`: model loading, audio helpers, the `Converter` interface | Both apps |

Each app is a Tauri UI (added later in `voiceapp/ui` and `studio/ui`) that talks to
a bundled Python engine (`voiceapp/engine`, `studio/engine`) running as a sidecar.

```
core/                    shared Python package (numpy only; torch optional)
voiceapp/engine/         Voice App sidecar: stdio JSON protocol + live audio
studio/engine/           Studio: training projects + CLI (heavy deps live here)
tests/test_boundaries.py keeps training deps out of Voice App and checks boot imports
```

## Rules that keep Voice App easy

- Voice App and core never import or depend on training libraries (librosa, faiss,
  tensorboard, scikit-learn, torchaudio). `tests/test_boundaries.py` fails if they do.
- Heavy imports (torch, sounddevice) happen inside functions, not at module level,
  so the engine starts instantly and loads them only when audio or a model is needed.
- Core never imports either app.

## Development

```
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements-dev.txt
pytest
```

Install only `./core` and `./voiceapp/engine` if you are not working on Studio.

### Voice App engine protocol

The engine reads one JSON request per line on stdin and answers on stdout:

```
{"id": 1, "method": "load_model", "params": {"path": "C:/models/alice.pth"}}
{"id": 1, "result": {"running": false, "model": "alice", "pitch": 0.0, ...}}
```

Methods: `hello`, `list_devices`, `set_devices(input, output)`, `load_model(path)`,
`set_pitch(semitones)`, `start`, `stop`, `status`.

### Studio CLI

```
voiceapp-studio new projects/alice --name alice
voiceapp-studio inspect alice.pth
```

The training steps (`preprocess`, `extract`, `train`, `index`, `export`) are
scaffolded and not implemented yet; neither is RVC inference in `core`
(`RvcConverter.process`). Voice App falls back to dry audio until it is.
