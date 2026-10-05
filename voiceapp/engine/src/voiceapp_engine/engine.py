"""Engine state: which model is loaded, pitch, devices, and the live stream."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from voiceapp_core import Converter, PassthroughConverter, load_converter
from voiceapp_core.audio import resample, rms_db

DEVICE_RATE = 48000
BLOCK_SIZE = 1024


class Engine:
    def __init__(self, stream_factory: Callable[..., Any] | None = None) -> None:
        self.converter: Converter = PassthroughConverter()
        self.model_name: str | None = None
        self.pitch = 0.0
        self.input_device: int | None = None
        self.output_device: int | None = None
        self.input_level_db = -96.0
        self.last_error: str | None = None
        self._stream: Any = None
        self._stream_factory = stream_factory

    @property
    def running(self) -> bool:
        return self._stream is not None

    def load_model(self, path: str | None) -> dict[str, Any]:
        converter = load_converter(path)
        converter.set_pitch(self.pitch)
        self.converter = converter
        info = getattr(converter, "info", None)
        self.model_name = info.name if info else None
        return self.status()

    def set_pitch(self, semitones: float) -> None:
        self.pitch = max(-24.0, min(24.0, float(semitones)))
        self.converter.set_pitch(self.pitch)

    def set_devices(self, input_device: int | None, output_device: int | None) -> None:
        self.input_device = input_device
        self.output_device = output_device

    def process_block(self, block: np.ndarray) -> np.ndarray:
        """Device-rate block in, device-rate block out. Never raises: an audio
        callback that throws kills the stream, so failures fall back to dry audio."""
        self.input_level_db = rms_db(block)
        try:
            model_in = resample(block, DEVICE_RATE, self.converter.sample_rate)
            model_out = self.converter.process(model_in)
            out = resample(model_out, self.converter.sample_rate, DEVICE_RATE)
        except Exception as exc:
            self.last_error = str(exc)
            return np.asarray(block, dtype=np.float32)
        if out.size < block.size:
            out = np.pad(out, (0, block.size - out.size))
        return out[: block.size]

    def start(self) -> None:
        if self.running:
            return
        if self._stream_factory is None:
            from voiceapp_engine.audio_io import DuplexStream

            self._stream_factory = DuplexStream
        stream = self._stream_factory(
            self.process_block, DEVICE_RATE, BLOCK_SIZE, self.input_device, self.output_device
        )
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "model": self.model_name,
            "pitch": self.pitch,
            "input_device": self.input_device,
            "output_device": self.output_device,
            "input_level_db": round(self.input_level_db, 1),
            "last_error": self.last_error,
        }
