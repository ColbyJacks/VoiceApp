"""Small numpy audio helpers shared by both apps."""

from __future__ import annotations

import numpy as np


def semitones_to_ratio(semitones: float) -> float:
    """Frequency ratio for a pitch shift, e.g. +12 -> 2.0."""
    return float(2.0 ** (semitones / 12.0))


def to_mono(block: np.ndarray) -> np.ndarray:
    """Collapse (frames, channels) audio to float32 mono (frames,)."""
    block = np.asarray(block, dtype=np.float32)
    if block.ndim == 1:
        return block
    return block.mean(axis=1, dtype=np.float32)


def resample(block: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear-interpolation resample of mono audio.

    Good enough for moving between device and model rates in the live path;
    Studio's preprocessing can use a higher-quality resampler.
    """
    block = np.asarray(block, dtype=np.float32)
    if src_rate == dst_rate or block.size == 0:
        return block
    n_out = int(round(block.size * dst_rate / src_rate))
    x_src = np.arange(block.size, dtype=np.float64) / src_rate
    x_dst = np.arange(n_out, dtype=np.float64) / dst_rate
    return np.interp(x_dst, x_src, block).astype(np.float32)


def rms_db(block: np.ndarray, floor_db: float = -96.0) -> float:
    """Level of a block in dBFS, used for input meters and silence gating."""
    block = np.asarray(block, dtype=np.float32)
    if block.size == 0:
        return floor_db
    rms = float(np.sqrt(np.mean(np.square(block))))
    if rms <= 0.0:
        return floor_db
    return max(floor_db, 20.0 * np.log10(rms))
