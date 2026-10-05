"""The conversion interface both apps program against.

Voice App runs a Converter on live microphone blocks; Studio uses the same one
to preview a freshly exported model, so a model behaves the same in both.
Converters take and return mono float32 audio at the device rate
(``DEVICE_RATE``); any resampling to the model's rate happens inside.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from voiceapp_core.model import ModelInfo, load_model_info

DEVICE_RATE = 48000
# 96 * 128 = 12,288 samples (~256 ms at 48 kHz), the block size the tray app used.
DEFAULT_BLOCK_SIZE = 96 * 128


@runtime_checkable
class Converter(Protocol):
    sample_rate: int

    def set_pitch(self, semitones: float) -> None: ...

    def process(self, block: np.ndarray) -> np.ndarray:
        """Convert one mono float32 block at ``sample_rate``; returns the same length."""
        ...


class PassthroughConverter:
    """Returns audio unchanged. Used when no model is loaded, and in tests."""

    def __init__(self, sample_rate: int = DEVICE_RATE) -> None:
        self.sample_rate = sample_rate
        self.pitch = 0.0

    def set_pitch(self, semitones: float) -> None:
        self.pitch = float(semitones)

    def process(self, block: np.ndarray) -> np.ndarray:
        return np.asarray(block, dtype=np.float32)


class RvcConverter:
    """Runs an RVC voice model through the realtime VoiceChanger.

    Settings match the original tray app: RMVPE pitch, 0.1 s crossfade,
    0.5 s extra context, -60 dB silence gate.
    """

    sample_rate = DEVICE_RATE

    def __init__(
        self,
        info: ModelInfo,
        index_path: str | Path | None = None,
        block_size: int = DEFAULT_BLOCK_SIZE,
        f0_method: str = "rmvpe",
    ) -> None:
        # Deferred: pulls in torch and the RVC networks, which takes seconds.
        from rvc.realtime.core import VoiceChanger

        self.info = info
        self.index_path = Path(index_path) if index_path else None
        self.pitch = 0.0
        self.index_rate = 0.75
        self.volume_envelope = 1.0
        self._vc = VoiceChanger(
            read_chunk_size=block_size // 128,
            cross_fade_overlap_size=0.1,
            extra_convert_size=0.5,
            model_path=str(info.path),
            index_path=str(self.index_path) if self.index_path else None,
            f0_method=f0_method,
            silent_threshold=-60,
        )

    def set_pitch(self, semitones: float) -> None:
        self.pitch = float(semitones)

    def process(self, block: np.ndarray) -> np.ndarray:
        out, _vol = self._vc.process_audio(
            block,
            f0_up_key=int(round(self.pitch)),
            index_rate=self.index_rate,
            volume_envelope=self.volume_envelope,
        )
        return out


def find_index(model_path: str | Path) -> Path | None:
    """The .index file that belongs to a model: same folder, same name.

    The tray app fell back to the first .index in the folder, which could pair
    a model with another voice's index; that fallback is gone on purpose.
    """
    candidate = Path(model_path).with_suffix(".index")
    return candidate if candidate.is_file() else None


def load_converter(model_path: str | Path | None, block_size: int = DEFAULT_BLOCK_SIZE) -> Converter:
    """Converter for a .pth path, or a passthrough when no model is chosen."""
    if model_path is None:
        return PassthroughConverter()
    info = load_model_info(model_path)
    return RvcConverter(info, index_path=find_index(model_path), block_size=block_size)
