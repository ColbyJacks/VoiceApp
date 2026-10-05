"""The FX rack from the tray app: reverb, echo, chorus, radio, always-on limiter."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass
class FxSettings:
    reverb: bool = False
    reverb_room: float = 0.5
    reverb_wet: float = 0.3
    delay: bool = False
    delay_time: float = 0.35
    delay_feedback: float = 0.3
    chorus: bool = False
    chorus_depth: float = 0.3
    chorus_rate: float = 1.2
    radio: bool = False
    radio_bits: int = 8

    def update(self, **changes: Any) -> None:
        names = {f.name for f in fields(self)}
        unknown = set(changes) - names
        if unknown:
            raise ValueError(f"unknown FX settings: {', '.join(sorted(unknown))}")
        for name, value in changes.items():
            setattr(self, name, type(getattr(self, name))(value))


def build_board(fx: FxSettings):
    """A pedalboard chain for the current settings. Imports pedalboard lazily."""
    import pedalboard

    plugins = []
    if fx.reverb:
        plugins.append(
            pedalboard.Reverb(room_size=fx.reverb_room, wet_level=fx.reverb_wet, dry_level=1.0 - fx.reverb_wet * 0.5)
        )
    if fx.delay:
        plugins.append(pedalboard.Delay(delay_seconds=fx.delay_time, feedback=fx.delay_feedback, mix=0.35))
    if fx.chorus:
        plugins.append(pedalboard.Chorus(rate_hz=fx.chorus_rate, depth=fx.chorus_depth, mix=0.4))
    if fx.radio:
        plugins.append(pedalboard.Bitcrush(bit_depth=fx.radio_bits))
        plugins.append(pedalboard.HighpassFilter(cutoff_frequency_hz=300))
        plugins.append(pedalboard.LowpassFilter(cutoff_frequency_hz=3400))
    # Transparent soft limiter, always on, so the volume booster can't clip.
    plugins.append(pedalboard.Limiter(threshold_db=-0.5, release_ms=50))
    return pedalboard.Pedalboard(plugins)
