"""Engine state and the realtime loop, ported from the tray app's DirectAudioEngine.

Audio path per block: mic -> input gain -> (mute | bypass | voice model)
-> volume booster -> FX rack + limiter -> main output (+ ear monitor).
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

from voiceapp_core import Converter, PassthroughConverter, load_converter
from voiceapp_core.converter import DEFAULT_BLOCK_SIZE, DEVICE_RATE
from voiceapp_core.paths import models_dir
from voiceapp_engine.fx import FxSettings, build_board

# Slider ranges from the tray app.
LIMITS = {
    "pitch": (-24.0, 24.0),
    "in_gain": (0.0, 3.0),
    "out_vol": (0.0, 4.0),
    "index_rate": (0.0, 1.0),
    "volume_envelope": (0.0, 1.0),
    "monitor_vol": (0.0, 4.0),
}


def _level(block: np.ndarray, scale: float) -> float:
    """0..1 meter value, using the tray app's meter scaling."""
    if block.size == 0:
        return 0.0
    return min(1.0, float(np.sqrt(np.mean(np.square(block)))) * scale)


class Engine:
    def __init__(
        self,
        stream_factory: Callable[..., Any] | None = None,
        converter_factory: Callable[..., Converter] = load_converter,
        models_folder: Path | None = None,
        block_size: int = DEFAULT_BLOCK_SIZE,
    ) -> None:
        self.models_folder = Path(models_folder) if models_folder else models_dir()
        self.block_size = block_size
        self.converter: Converter = PassthroughConverter()
        self.model_name: str | None = None

        self.pitch = 0.0
        self.index_rate = 0.75
        self.volume_envelope = 1.0
        self.in_gain = 1.0
        self.out_vol = 1.5  # the tray app's default volume boost
        self.monitor_vol = 1.0
        self.use_monitor = False
        self.bypassed = False  # True = your real voice
        self.muted = False
        self.fx = FxSettings()
        self._board: Any = None
        self._board_dirty = True  # built on first use so startup stays fast

        self.input_device: int | None = None
        self.output_device: int | None = None
        self.monitor_device: int | None = None

        self.in_level = 0.0
        self.out_level = 0.0
        self.last_error: str | None = None

        self._stream_factory = stream_factory
        self._converter_factory = converter_factory
        self._streams: Any = None
        self._in_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=6)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    # ---- settings -------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._streams is not None

    def list_models(self) -> list[str]:
        if not self.models_folder.is_dir():
            return []
        return sorted(p.stem for p in self.models_folder.glob("*.pth"))

    def resolve_model(self, name_or_path: str) -> Path:
        path = Path(name_or_path)
        if path.suffix != ".pth" and not path.is_absolute():
            path = self.models_folder / f"{name_or_path}.pth"
        elif not path.is_absolute():
            path = self.models_folder / path
        return path

    def load_model(self, model: str | None) -> None:
        """Load a model by name (from the models folder) or path; None = passthrough."""
        path = self.resolve_model(model) if model else None
        converter = self._converter_factory(path, block_size=self.block_size) if path else PassthroughConverter()
        self._apply_converter_settings(converter)
        with self._lock:
            self.converter = converter
            self.model_name = path.stem if path else None

    def _apply_converter_settings(self, converter: Converter) -> None:
        converter.set_pitch(self.pitch)
        for name in ("index_rate", "volume_envelope"):
            if hasattr(converter, name):
                setattr(converter, name, getattr(self, name))

    def set_params(self, **params: float) -> None:
        unknown = set(params) - set(LIMITS)
        if unknown:
            raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
        for name, value in params.items():
            lo, hi = LIMITS[name]
            setattr(self, name, max(lo, min(hi, float(value))))
        self._apply_converter_settings(self.converter)

    def set_fx(self, **changes: Any) -> None:
        self.fx.update(**changes)
        self._board_dirty = True  # takes effect on the next block, no restart needed

    def _current_board(self) -> Any:
        if self._board_dirty:
            self._board_dirty = False
            try:
                self._board = build_board(self.fx)
            except ImportError:
                self._board = None
        return self._board

    def toggle_bypass(self) -> bool:
        self.bypassed = not self.bypassed
        return self.bypassed

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def set_devices(self, input: int | None = None, output: int | None = None,
                    monitor: int | None = None, use_monitor: bool | None = None) -> None:
        self.input_device, self.output_device, self.monitor_device = input, output, monitor
        if use_monitor is not None:
            self.use_monitor = bool(use_monitor)
        if self.running:
            self.stop()
            self.start()

    # ---- audio ----------------------------------------------------------

    def process_block(self, raw: np.ndarray) -> np.ndarray:
        """One mic block in, one output block out. Never raises: a failing
        model falls back to the dry voice so the stream keeps going."""
        block = np.asarray(raw, dtype=np.float32) * self.in_gain
        self.in_level = _level(block, 4.0)

        if self.muted:
            self.out_level = 0.0
            return np.zeros_like(block)

        out = block
        if not self.bypassed:
            try:
                with self._lock:
                    out = np.asarray(self.converter.process(block), dtype=np.float32)
            except Exception as exc:
                self.last_error = str(exc)
                out = block

        # Boost before the FX rack so its limiter catches the boost. (The tray
        # app boosted after the limiter, which could clip at high volume.)
        out = out * self.out_vol
        board = self._current_board()
        if board is not None and out.size:
            try:
                out = board(out.astype(np.float32), DEVICE_RATE)
            except Exception as exc:
                self.last_error = f"FX: {exc}"

        if out.size < block.size:
            out = np.pad(out, (0, block.size - out.size))
        out = out[: block.size].astype(np.float32)
        self.out_level = _level(out, 3.5)
        return out

    def _on_input(self, block: np.ndarray) -> None:
        try:
            self._in_queue.put_nowait(block)
        except queue.Full:
            pass

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._in_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            out = self.process_block(raw)
            monitor = out * self.monitor_vol if self.use_monitor else None
            if self._streams is not None:
                self._streams.play(out, monitor)

    def start(self) -> None:
        if self.running:
            return
        if self._stream_factory is None:
            from voiceapp_engine.audio_io import Streams

            self._stream_factory = Streams
        while not self._in_queue.empty():
            self._in_queue.get_nowait()
        streams = self._stream_factory(
            DEVICE_RATE,
            self.block_size,
            self.input_device,
            self.output_device,
            self.monitor_device if self.use_monitor else None,
            on_input=self._on_input,
        )
        self._stop.clear()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        try:
            streams.start()
        except Exception:
            self._stop.set()
            raise
        self._streams = streams

    def stop(self) -> None:
        self._stop.set()
        if self._streams is not None:
            self._streams.stop()
            self._streams = None
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        self.in_level = self.out_level = 0.0

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "model": self.model_name,
            "mode": "muted" if self.muted else ("real" if self.bypassed else "voice"),
            "pitch": self.pitch,
            "index_rate": self.index_rate,
            "volume_envelope": self.volume_envelope,
            "in_gain": self.in_gain,
            "out_vol": self.out_vol,
            "monitor_vol": self.monitor_vol,
            "use_monitor": self.use_monitor,
            "devices": {"input": self.input_device, "output": self.output_device, "monitor": self.monitor_device},
            "fx": vars(self.fx).copy(),
            "levels": {"in": round(self.in_level, 3), "out": round(self.out_level, 3)},
            "last_error": self.last_error,
        }
