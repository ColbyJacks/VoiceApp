"""Effects rack (pedalboard) and the output safety limiter."""

from __future__ import annotations

from typing import Any

import numpy as np

DEFAULT_FX: dict[str, Any] = {
    "reverb": False, "reverb_mix": 0.3, "reverb_room": 0.5,
    "echo": False, "echo_mix": 0.3, "echo_time": 0.3, "echo_feedback": 0.3,
    "robot": False, "robot_mix": 0.5,
    "radio": False,
    "deep": False,
}


def build_board(fx: dict[str, Any]):
    """A pedalboard chain for the enabled effects, or None if none are on."""
    import pedalboard as pb

    plugins = []
    if fx["deep"]:
        plugins += [pb.LowShelfFilter(cutoff_frequency_hz=180, gain_db=5), pb.HighShelfFilter(cutoff_frequency_hz=6000, gain_db=-3)]
    if fx["radio"]:
        plugins += [
            pb.HighpassFilter(cutoff_frequency_hz=350),
            pb.LowpassFilter(cutoff_frequency_hz=3200),
            pb.Distortion(drive_db=8),
            pb.Gain(gain_db=-6),
        ]
    if fx["robot"]:
        plugins.append(pb.Chorus(rate_hz=40.0, depth=0.6, centre_delay_ms=4, feedback=0.4, mix=fx["robot_mix"]))
    if fx["echo"]:
        plugins.append(pb.Delay(delay_seconds=fx["echo_time"], feedback=fx["echo_feedback"], mix=fx["echo_mix"]))
    if fx["reverb"]:
        mix = fx["reverb_mix"]
        plugins.append(pb.Reverb(room_size=fx["reverb_room"], wet_level=mix, dry_level=1.0 - mix * 0.5))
    return pb.Pedalboard(plugins) if plugins else None


def soft_limit(x: np.ndarray, knee: float = 0.8) -> np.ndarray:
    """Leaves audio below `knee` untouched and bends peaks smoothly under 1.0,
    so the volume booster can't clip. (pedalboard's Limiter adds ~4 dB of
    make-up gain, so it isn't transparent.)"""
    over = np.abs(x) > knee
    if not over.any():
        return x
    y = x.copy()
    head = 1.0 - knee
    y[over] = np.sign(x[over]) * (knee + head * np.tanh((np.abs(x[over]) - knee) / head))
    return y
