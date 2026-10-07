"""One loaded RVC voice, wrapped around rvc.realtime.core.VoiceChanger."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

RATE = 48000

# Block size (samples at 48 kHz), extra context (s) and pitch detector per
# latency preset. Measured on an RTX 3090 Ti: Balanced uses ~40% of each block
# for conversion, Low ~60%.
PRESETS = {
    "low": {"block": 4096, "extra": 0.35, "f0": "fcpe"},
    "balanced": {"block": 8192, "extra": 0.5, "f0": "rmvpe"},
    "safe": {"block": 12288, "extra": 0.5, "f0": "rmvpe"},
}


class VoiceConverter:
    def __init__(self, model: Path, index: Path | None, block: int, extra: float, f0_method: str):
        from rvc.realtime.core import VoiceChanger

        self.model = model
        self.index = index
        self.block = block
        self.f0_method = f0_method
        self.vc = VoiceChanger(
            read_chunk_size=block // 128,
            cross_fade_overlap_size=0.05,
            extra_convert_size=extra,
            model_path=str(model),
            index_path=str(index) if index else None,
            f0_method=f0_method,
            silent_threshold=-60,
        )
        pipeline = self.vc.vc_model.pipeline
        self.sample_rate = pipeline.tgt_sr
        self.version = pipeline.version
        self.device = str(self.vc.device)

    def warmup(self, seconds: float = 1.0) -> float:
        """Run a synthetic voice through every stage so the first real block
        isn't slowed by CUDA start-up, then clear the buffers. Returns ms/block."""
        n = max(3, int(seconds * RATE / self.block))
        t = np.arange(self.block * n) / RATE
        f0 = 170 + 40 * np.sin(2 * np.pi * 0.7 * t)
        phase = 2 * np.pi * np.cumsum(f0) / RATE
        tone = (sum(np.sin(k * phase) / k for k in range(1, 8)) * 0.1).astype(np.float32)
        times = []
        for i in range(n):
            start = time.perf_counter()
            self.vc.process_audio(tone[i * self.block:(i + 1) * self.block])
            times.append((time.perf_counter() - start) * 1000)
        self.reset()
        return float(np.mean(times[1:]))

    def reset(self) -> None:
        """Empty the context buffers. Conversion then starts immediately
        (against silence) instead of after ~1 s of warm-up blocks."""
        m = self.vc.vc_model
        for buf in (m.audio_buffer, m.convert_buffer, m.pitch_buffer, m.pitchf_buffer):
            buf.zero_()
        m.warmup_blocks = 0
        self.vc.sola_buffer.zero_()

    def set_gate(self, db: float) -> None:
        """Input level (dBFS) below which the voice is silenced."""
        self.vc.vc_model.input_sensitivity = 10 ** (db / 20)

    def process(self, block: np.ndarray, pitch: float, index_rate: float, protect: float, envelope: float) -> np.ndarray:
        out, _ = self.vc.process_audio(
            block,
            f0_up_key=pitch,
            index_rate=index_rate,
            protect=protect,
            volume_envelope=envelope,
        )
        return out
