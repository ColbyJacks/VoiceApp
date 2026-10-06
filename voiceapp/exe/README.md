# Voice App as a Windows .exe

Builds `dist\VoiceApp\VoiceApp.exe`, a one-folder PyInstaller build of the
tray app (`voiceapp/tray/voice_tray_app.py`) with GPU torch bundled. No Python
install is needed to run it.

## Build

1. Make a Python 3.12 environment with the Voice App requirements and PyInstaller:

   ```bat
   py -3.12 -m venv build-venv
   build-venv\Scripts\python -m pip install -r ..\requirements.txt pyinstaller --extra-index-url https://download.pytorch.org/whl/cu128
   ```

2. Run the build, pointing at a folder that already has `rvc\models` (the base
   models) so the exe works offline on first run:

   ```bat
   build.bat build-venv\Scripts\python.exe "E:\Voice stuff"
   ```

The result is about 5 GB, mostly CUDA torch.

## Folder layout

```
VoiceApp.exe
models\        your .pth and .index voices
rvc\models\    base models (contentvec, rmvpe); downloaded on first run if missing
voiceapp.log   console output (the exe has no console window)
_internal\     Python, torch and the app code
```

## Check a build

`VoiceApp.exe --selftest` loads the first voice in `models\`, converts a
synthetic voice on the GPU without opening the window, writes the results to
`voiceapp.log` and exits with 0 on success.

## Build notes

- `hooks/hook-webrtcvad.py` replaces the stock PyInstaller hook, which looks
  for the `webrtcvad` package; Voice App installs `webrtcvad-wheels`.
- `rvc` is shipped as `.py` source as well as bytecode because
  `torch.jit.script` in `rvc/lib/algorithm/commons.py` compiles from source
  when it is imported.
