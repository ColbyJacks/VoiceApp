"""Optional voice effects: reverb, echo, robot (chorus) and radio."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def any_on(self) -> bool:
        return self.reverb or self.delay or self.chorus or self.radio


def build_board(fx: FxSettings):
    """A pedalboard chain for the enabled effects, or None when all are off.

    There is deliberately no always-on limiter: pedalboard's Limiter adds about
    4 dB of make-up gain, which made the old tray app louder than intended.
    The engine clips to [-1, 1] at the very end instead.
    """
    if not fx.any_on:
        return None
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
    return pedalboard.Pedalboard(plugins)
