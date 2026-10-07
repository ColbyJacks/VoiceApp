"""Entry point for the packaged voice engine (engine\\voiceapp-engine.exe).

Normally the Voice App window starts this and talks to it over stdin/stdout.
`voiceapp-engine.exe --selftest [voice.pth]` instead converts a synthetic voice
on the GPU without any audio devices and exits 0 on success, to check a build.
"""

import multiprocessing as mp
import sys


def selftest(argv: list[str]) -> int:
    import os
    import time
    from pathlib import Path

    import numpy as np

    from voiceapp_core import load_converter
    from voiceapp_core.paths import data_dir
    from voiceapp_engine.__main__ import pick_base_folder
    from voiceapp_engine.engine import LATENCY, find_index_for

    data = data_dir("VoiceApp")
    os.chdir(pick_base_folder(data))
    print(f"selftest: base models from {os.getcwd()}")
    paths = [Path(a) for a in argv if a.lower().endswith(".pth")]
    model = paths[0] if paths else next(iter(sorted((data / "models").glob("*.pth"))), None)
    if model is None:
        print(f"selftest: no .pth given and none in {data / 'models'}")
        return 2
    block = LATENCY["low"]
    t0 = time.perf_counter()
    conv = load_converter(model, block_size=block, index_path=find_index_for(model))
    print(f"selftest: loaded {model.name} in {time.perf_counter() - t0:.1f}s")

    rate, n = 48000, 16
    t = np.arange(block * n) / rate
    f0 = 180 + 40 * np.sin(2 * np.pi * 0.5 * t)
    phase = 2 * np.pi * np.cumsum(f0) / rate
    voice = sum(np.sin(k * phase) / k for k in range(1, 8)).astype(np.float32) * 0.1
    rms, times = [], []
    for i in range(n):
        start = time.perf_counter()
        out = conv.process(voice[i * block:(i + 1) * block])
        times.append((time.perf_counter() - start) * 1000)
        rms.append(float(np.sqrt(np.mean(np.square(out)))))
    warm = times[n // 2:]
    print(f"selftest: {block * 1000 // rate} ms blocks, {sum(warm) / len(warm):.0f} ms each when warm")
    ok = max(rms[n // 2:]) > 1e-3
    print("selftest: PASS" if ok else "selftest: FAIL (output stayed silent)")
    return 0 if ok else 1


if __name__ == "__main__":
    mp.freeze_support()
    if "--selftest" in sys.argv:
        sys.exit(selftest(sys.argv[1:]))
    from voiceapp_engine.__main__ import main

    main([a for a in sys.argv[1:]])
