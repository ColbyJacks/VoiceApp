"""The conversion interface both apps program against.

Voice App runs a Converter on live microphone blocks; Studio uses the same one
to preview a freshly exported model, so a model behaves the same in both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from voiceapp_core.model import ModelInfo, load_model_info


@runtime_checkable
class Converter(Protocol):
    sample_rate: int

    def set_pitch(self, semitones: float) -> None: ...

    def process(self, block: np.ndarray) -> np.ndarray:
        """Convert one mono float32 block at ``sample_rate``; returns the same length."""
        ...


class PassthroughConverter:
    """Returns audio unchanged. Used when no model is loaded, and in tests."""

    def __init__(self, sample_rate: int = 48000) -> None:
        self.sample_rate = sample_rate
        self.pitch = 0.0

    def set_pitch(self, semitones: float) -> None:
        self.pitch = float(semitones)

    def process(self, block: np.ndarray) -> np.ndarray:
        return np.asarray(block, dtype=np.float32)


class RvcConverter:
    """Runs an RVC voice model.

    Holds the model description now; the inference network (content encoder,
    pitch extractor, synthesizer) is ported in a later step.
    """

    def __init__(self, info: ModelInfo) -> None:
        self.info = info
        self.sample_rate = info.sample_rate
        self.pitch = 0.0

    def set_pitch(self, semitones: float) -> None:
        self.pitch = float(semitones)

    def process(self, block: np.ndarray) -> np.ndarray:
        raise NotImplementedError("RVC inference is not wired up yet")


def load_converter(model_path: str | Path | None) -> Converter:
    """Converter for a .pth path, or a passthrough when no model is chosen."""
    if model_path is None:
        return PassthroughConverter()
    return RvcConverter(load_model_info(model_path))
