# PyInstaller spec for engine\voiceapp-engine.exe (one-folder build).
# Run through ..\scripts\build-windows.ps1.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

HERE = Path(SPECPATH)
REPO = HERE.parents[1]
CORE = REPO / "core" / "src"
ENGINE = REPO / "voiceapp" / "engine" / "src"

datas = [(str(CORE / "rvc" / "configs" / "*.json"), "rvc/configs")]
datas += collect_data_files("torchfcpe")
for dist in ("transformers", "tokenizers", "huggingface-hub", "safetensors", "tqdm",
             "regex", "requests", "packaging", "filelock", "numpy", "pyyaml", "torch"):
    datas += copy_metadata(dist)

a = Analysis(
    [str(HERE / "entry.py")],
    pathex=[str(CORE), str(ENGINE)],
    datas=datas,
    hiddenimports=["keyboard", "pedalboard", "sounddevice", "requests"],
    # Voice App never trains or serves a web UI; keep those out of the bundle.
    excludes=["rvc.train", "gradio", "tensorboard", "matplotlib", "IPython", "tkinter",
              "jupyter", "notebook", "pytest", "torch.utils.tensorboard", "pystray"],
    hookspath=[str(HERE / "hooks")],
    # TorchScript (torch.jit.script in rvc.lib.algorithm.commons) compiles from
    # source at import time, so ship rvc as .py files as well as bytecode.
    module_collection_mode={"rvc": "pyz+py"},
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voiceapp-engine",
    # A console exe so stdin/stdout work; the window starts it hidden.
    console=True,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="voiceapp-engine", upx=False)
