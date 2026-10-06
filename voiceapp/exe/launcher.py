"""Entry point for the packaged Voice App (VoiceApp.exe).

The tray app and the rvc code find their data relative to the working
directory (models\, rvc\models\), so the exe switches to its own folder
before importing them. Those folders sit next to VoiceApp.exe:

    VoiceApp.exe
    models\          your .pth / .index voices
    rvc\models\      base models (contentvec embedder, rmvpe pitch model)
    voiceapp.log     console output (the exe has no console window)
"""

import multiprocessing as mp
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def app_dir() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1] / "tray"


def redirect_output(folder: Path) -> None:
    # A windowed exe has no stdout/stderr; tqdm and print would fail or vanish.
    if sys.stdout is None or sys.stderr is None:
        log = open(folder / "voiceapp.log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def ensure_base_models(root) -> bool:
    if (Path("rvc") / "models" / "predictors" / "rmvpe.pt").is_file():
        return True
    from tkinter import messagebox

    if not messagebox.askyesno(
        "Voice App",
        "The base voice models (about 600 MB) are missing from rvc\\models.\n\n"
        "Download them now? The window may stop responding until it finishes.",
        parent=root,
    ):
        return False
    try:
        from rvc.lib.tools.prerequisites_download import prequisites_download_pipeline

        prequisites_download_pipeline(False, True, False)
        return True
    except Exception as exc:
        messagebox.showerror("Voice App", f"Download failed:\n{exc}", parent=root)
        return False


def selftest(folder: Path) -> int:
    """VoiceApp.exe --selftest: convert a synthetic voice with the first model,
    no window or audio devices. Results go to voiceapp.log; exit code 0 = ok."""
    import time

    import numpy as np

    models = sorted((folder / "models").glob("*.pth"))
    if not models:
        print("selftest: no .pth in models\\")
        return 2
    model = models[0]
    index = model.with_suffix(".index")
    print(f"selftest: model={model.name} index={index.name if index.is_file() else None}")

    import torch
    from rvc.realtime.core import VoiceChanger

    print(f"selftest: torch {torch.__version__}, cuda={torch.cuda.is_available()}")
    t0 = time.perf_counter()
    vc = VoiceChanger(read_chunk_size=96, cross_fade_overlap_size=0.1, extra_convert_size=0.5,
                      model_path=str(model), index_path=str(index) if index.is_file() else None,
                      f0_method="rmvpe", silent_threshold=-60)
    print(f"selftest: loaded in {time.perf_counter() - t0:.1f}s on {vc.device}")

    # A gliding 140-220 Hz tone with harmonics stands in for a voice.
    rate, block, n = 48000, 96 * 128, 10
    t = np.arange(block * n) / rate
    f0 = 180 + 40 * np.sin(2 * np.pi * 0.5 * t)
    phase = 2 * np.pi * np.cumsum(f0) / rate
    voice = sum(np.sin(k * phase) / k for k in range(1, 8)).astype(np.float32) * 0.1

    rms = []
    for i in range(n):
        start = time.perf_counter()
        out, _ = vc.process_audio(voice[i * block:(i + 1) * block])
        rms.append(float(np.sqrt(np.mean(out ** 2))))
        print(f"selftest: block {i} shape={out.shape} rms={rms[-1]:.4f} "
              f"{(time.perf_counter() - start) * 1000:.0f} ms")
    ok = max(rms[5:]) > 1e-3
    print("selftest: PASS" if ok else "selftest: FAIL (output stayed silent)")
    return 0 if ok else 1


def main() -> None:
    mp.freeze_support()
    folder = app_dir()
    os.chdir(folder)
    redirect_output(folder)
    (folder / "models").mkdir(exist_ok=True)

    if "--selftest" in sys.argv:
        sys.exit(selftest(folder))

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    if not ensure_base_models(root):
        root.destroy()
        return

    import voice_tray_app

    # The tray app looks for models next to its own source file, which in the
    # exe is inside _internal\. Point it at the folder next to the exe instead.
    voice_tray_app.MODELS_DIR = folder / "models"

    root.deiconify()
    voice_tray_app.VoiceTrayApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
