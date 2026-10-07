# VoiceApp

Voice modulation app. 1 .pth is all you need to get started.

This repository holds two Windows apps that share one voice engine. It started
as a customized [Applio](https://github.com/IAHispano/Applio) install (MIT licensed,
see `LICENSE`), split so the voice changer installs without any training tools.

| Folder | What it is | Who needs it |
| --- | --- | --- |
| `voiceapp/` | **Voice App**: real-time voice changing with an RVC `.pth` model | Everyone. Light install, no training libraries. |
| `studio/` | **VoiceAppStudio**: records, cleans and trains `.pth` voices | Only people making their own voices. |
| `core/` | The shared engine: Applio's RVC inference (`rvc` package) plus `voiceapp_core` | Both apps |

```
core/src/rvc/            RVC inference: configs, synthesizer networks, pitch
                         predictors, the realtime VoiceChanger
core/src/voiceapp_core/  model info, audio helpers, the Converter interface
voice-app/               the new Voice App window (Tauri) and its Windows build
voiceapp/engine/         Voice App's audio engine, run by the window (stdio JSON)
voiceapp/tray/           the old Tkinter tray window (voice_tray_app.py)
studio/engine/src/rvc/   training (rvc.train) and Studio-only tools, in the same
                         rvc namespace as core so Applio's imports still work
studio/applio/           Voice Trainer Studio window, Applio's web UI and CLI
tests/                   checks that Voice App never pulls in training code
```

Voice App's Tauri window is in `voice-app/` (see `voice-app/README.md` to build
it). Studio still uses its Tkinter window.

## Running on Windows

```
run-install.bat            # both apps (or: run-install.bat voiceapp)
run-voice-app.bat          # the real-time voice tray
run-studio.bat             # Voice Trainer Studio
run-applio.bat             # Applio's web UI
run-tensorboard.bat        # training graphs
```

Each app keeps its own data, next to its code, so the two can be installed apart:

| | Voice App (`voiceapp/tray/`) | Studio (`studio/applio/`) |
| --- | --- | --- |
| Your voices (`.pth` + `.index`) | `models/` | `models/`, `exported_models/` |
| Base models (contentvec, rmvpe) | `rvc/models/`, downloaded on first run | `rvc/models/` |
| Training data | | `raw_recordings/`, `cleaned_for_rvc/`, `logs/` |

**Moving from `E:\Voice stuff`:** copy `models\` into `voiceapp\tray\models\` for
Voice App, and copy `rvc\models\`, `models\`, `logs\`, `raw_recordings\`,
`cleaned_for_rvc\` and `exported_models\` into `studio\applio\` for Studio. Copying
`rvc\models\` into `voiceapp\tray\rvc\models\` too skips Voice App's first download.

## Rules that keep Voice App easy

- Voice App and core never import training or web UI libraries (tensorboard,
  scikit-learn, matplotlib, gradio, yt-dlp, edge-tts) or Studio code (`rvc.train`,
  Applio's `tabs`, `assets`, `core.py`). `tests/test_boundaries.py` fails if they do,
  and checks that every `rvc` module core imports lives in core.
- `voiceapp/requirements.txt` is Voice App's whole dependency list;
  `studio/requirements.txt` adds training on top.
- The new engine imports torch, sounddevice and the RVC engine only when it needs
  them, so it starts instantly.

## Development

```
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements-dev.txt
pytest
```

The tests need only numpy and pytest; the full voice engine needs `requirements.txt`.

### Voice App engine protocol

See `voice-app/README.md` ("Talking to the engine") and
`voiceapp/engine/src/voiceapp_engine/protocol.py`.

### Studio CLI

```
voiceapp-studio new projects/alice --name alice
voiceapp-studio inspect alice.pth
```

The training steps (`preprocess`, `extract`, `train`, `index`, `export`) are
scaffolded and not implemented yet.
