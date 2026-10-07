"""Engine state and the realtime loop.

Audio path per block: mic -> input gain -> (mute | real voice | voice model)
-> volume -> optional effects -> clip to [-1, 1] -> output (+ ear monitor).
"""

from __future__ import annotations

import math
import os
import queue
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

from voiceapp_core import Converter, PassthroughConverter, load_converter
from voiceapp_core.converter import DEVICE_RATE
from voiceapp_core.paths import data_dir
from voiceapp_engine import settings as settings_store
from voiceapp_engine.fx import FxSettings, build_board

# Block sizes (samples at 48 kHz). Smaller blocks mean less delay but more GPU
# work per second; the tray app always used 12,288 (256 ms).
LATENCY = {"low": 48 * 128, "balanced": 72 * 128, "safe": 96 * 128}

LIMITS = {
    "pitch": (-24.0, 24.0),
    "in_gain": (0.0, 3.0),
    "out_vol": (0.0, 3.0),
    "index_rate": (0.0, 1.0),
    "monitor_vol": (0.0, 3.0),
}
# The converter's context: 0.5 s extra + 0.1 s crossfade + 10 ms search window.
_CONTEXT_SAMPLES = int(0.61 * DEVICE_RATE)


def _level(block: np.ndarray) -> float:
    """0..1 meter value on a dB scale (-60 dB .. 0 dB)."""
    if block.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(block))))
    if rms <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, (20 * math.log10(rms) + 60) / 60))


def find_index_for(pth: Path) -> Path | None:
    """The .index that belongs to a voice: same name, or (as Applio exports
    them, e.g. added_IVF256_Flat_nprobe_1_Name_v2.index) one containing it."""
    exact = pth.with_suffix(".index")
    if exact.is_file():
        return exact
    stem = pth.stem.lower()
    for cand in sorted(pth.parent.glob("*.index")):
        if stem in cand.stem.lower():
            return cand
    return None


class Engine:
    def __init__(
        self,
        data_folder: Path | None = None,
        stream_factory: Callable[..., Any] | None = None,
        converter_factory: Callable[..., Converter] = load_converter,
        devices_provider: Callable[[], list[dict[str, Any]]] | None = None,
        notify: Callable[[str, dict[str, Any]], None] | None = None,
        persist: bool = True,
    ) -> None:
        self.data_folder = Path(data_folder) if data_folder else data_dir("VoiceApp")
        self.models_folder = self.data_folder / "models"
        self.settings_path = self.data_folder / "settings.json"
        self._persist = persist
        self.notify = notify or (lambda event, data: None)

        s = settings_store.load(self.settings_path) if persist else dict(settings_store.DEFAULTS)
        self.latency = s["latency"] if s["latency"] in LATENCY else "low"
        self.pitch = float(s["pitch"])
        self.index_rate = float(s["index_rate"])
        self.in_gain = float(s["in_gain"])
        self.out_vol = float(s["out_vol"])
        self.monitor_vol = float(s["monitor_vol"])
        self.use_monitor = bool(s["use_monitor"])
        self.fx = FxSettings()
        try:
            self.fx.update(**(s["fx"] or {}))
        except (ValueError, TypeError):
            pass
        self.saved_model: str | None = s["model"]
        self.input_name: str | None = s["input_name"]
        self.output_name: str | None = s["output_name"]
        self.monitor_name: str | None = s["monitor_name"]

        self.converter: Converter = PassthroughConverter()
        self.model_name: str | None = None
        self.loading = False
        self.bypassed = False  # True = your real voice
        self.muted = False
        self._board: Any = None
        self._board_dirty = True  # built on first use so startup stays fast

        self.in_level = 0.0
        self.out_level = 0.0
        self.blocks_done = 0
        self.last_error: str | None = None
        self.load_ms: float | None = None
        self.block_ms: float | None = None

        self._stream_factory = stream_factory
        self._converter_factory = converter_factory
        self._devices_provider = devices_provider
        self._streams: Any = None
        self._in_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    # ---- persistence ----------------------------------------------------

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            settings_store.save(self.settings_path, {
                "model": self.model_name or self.saved_model,
                "input_name": self.input_name,
                "output_name": self.output_name,
                "monitor_name": self.monitor_name,
                "use_monitor": self.use_monitor,
                "latency": self.latency,
                "pitch": self.pitch,
                "index_rate": self.index_rate,
                "in_gain": self.in_gain,
                "out_vol": self.out_vol,
                "monitor_vol": self.monitor_vol,
                "fx": self.fx.to_dict(),
            })
        except OSError as exc:
            self.last_error = f"Couldn't save settings: {exc}"

    # ---- devices --------------------------------------------------------

    @property
    def block_size(self) -> int:
        return LATENCY[self.latency]

    def devices(self) -> dict[str, Any]:
        from voiceapp_engine import audio_io

        devs = (self._devices_provider or audio_io.list_devices)()
        default_in, default_out = audio_io.default_devices(devs)
        names = {d["index"]: d["name"] for d in devs}
        # First run: adopt the defaults so the app works without any setup.
        if self.input_name is None and default_in is not None:
            self.input_name = names[default_in]
        if self.output_name is None and default_out is not None:
            self.output_name = names[default_out]
        return {
            "inputs": [d["name"] for d in devs if d["inputs"] > 0],
            "outputs": [d["name"] for d in devs if d["outputs"] > 0],
            "input": self.input_name,
            "output": self.output_name,
            "monitor": self.monitor_name,
            "use_monitor": self.use_monitor,
        }

    def set_devices(self, input: str | None = None, output: str | None = None,
                    monitor: str | None = None, use_monitor: bool | None = None) -> None:
        if input is not None:
            self.input_name = input
        if output is not None:
            self.output_name = output
        if monitor is not None:
            self.monitor_name = monitor
        if use_monitor is not None:
            self.use_monitor = bool(use_monitor)
        self._save()
        self._restart_if_running()

    # ---- models ---------------------------------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        if not self.models_folder.is_dir():
            return []
        out = []
        for p in sorted(self.models_folder.glob("*.pth"), key=lambda p: p.stem.lower()):
            out.append({
                "name": p.stem,
                "has_index": find_index_for(p) is not None,
                "size_mb": round(p.stat().st_size / 1e6, 1),
            })
        return out

    def load_model(self, model: str | None) -> None:
        """Load a voice by name (from the models folder); None = no voice."""
        import time

        if model is None:
            with self._lock:
                self.converter = PassthroughConverter()
                self.model_name = None
            self._save()
            return
        path = self.models_folder / f"{model}.pth"
        if not path.is_file():
            raise ValueError(f"voice '{model}' isn't in the models folder")
        self.loading = True
        self.notify("state", self.status())
        t0 = time.perf_counter()
        try:
            converter = self._converter_factory(path, block_size=self.block_size,
                                                index_path=find_index_for(path))
        finally:
            self.loading = False
        self.load_ms = round((time.perf_counter() - t0) * 1000)
        self._apply_converter_settings(converter)
        with self._lock:
            self.converter = converter
            self.model_name = path.stem
            self.blocks_done = 0
        self.saved_model = path.stem
        self.last_error = None
        self._save()

    def import_model(self, path: str) -> dict[str, Any]:
        """Copy a .pth (and its .index if one sits next to it) into the models folder."""
        src = Path(path)
        if src.suffix.lower() != ".pth" or not src.is_file():
            raise ValueError("drop a .pth voice file")
        from voiceapp_core import load_model_info

        load_model_info(src)  # refuses training checkpoints and non-RVC files
        self.models_folder.mkdir(parents=True, exist_ok=True)
        dest = self.models_folder / src.name
        shutil.copy2(src, dest)
        index = find_index_for(src)
        if index is not None:
            shutil.copy2(index, dest.with_suffix(".index"))
        return {"name": dest.stem, "has_index": index is not None}

    def open_models_folder(self) -> None:
        self.models_folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(self.models_folder)  # noqa: S606

    def _apply_converter_settings(self, converter: Converter) -> None:
        converter.set_pitch(self.pitch)
        if hasattr(converter, "index_rate"):
            converter.index_rate = self.index_rate

    # ---- settings -------------------------------------------------------

    def set_params(self, **params: float) -> None:
        unknown = set(params) - set(LIMITS)
        if unknown:
            raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
        for name, value in params.items():
            lo, hi = LIMITS[name]
            setattr(self, name, max(lo, min(hi, float(value))))
        self._apply_converter_settings(self.converter)
        self._save()

    def set_latency(self, latency: str) -> None:
        if latency not in LATENCY:
            raise ValueError(f"latency must be one of {', '.join(LATENCY)}")
        if latency == self.latency:
            return
        self.latency = latency
        self._save()
        # The converter's buffers are sized for the block, so reload it.
        was_running = self.running
        if was_running:
            self.stop()
        if self.model_name:
            self.load_model(self.model_name)
        if was_running:
            self.start()

    def set_fx(self, **changes: Any) -> None:
        self.fx.update(**changes)
        self._board_dirty = True  # takes effect on the next block, no restart needed
        self._save()

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
        self.notify("state", self.status())
        return self.bypassed

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        self.notify("state", self.status())
        return self.muted

    # ---- audio ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._streams is not None

    @property
    def warming_up(self) -> bool:
        """The voice model outputs silence until its context buffer is full."""
        if not self.running or self.model_name is None or self.bypassed:
            return False
        needed = math.ceil((self.block_size + _CONTEXT_SAMPLES) / self.block_size) + 1
        return self.blocks_done < needed

    def process_block(self, raw: np.ndarray) -> np.ndarray:
        """One mic block in, one output block out. Never raises: a failing
        model falls back to the dry voice so the stream keeps going."""
        import time

        block = np.asarray(raw, dtype=np.float32) * self.in_gain
        self.in_level = _level(block)

        if self.muted:
            self.out_level = 0.0
            return np.zeros_like(block)

        out = block
        if not self.bypassed:
            t0 = time.perf_counter()
            try:
                with self._lock:
                    out = np.asarray(self.converter.process(block), dtype=np.float32)
                self.blocks_done += 1
            except Exception as exc:
                self.last_error = str(exc)
                out = block
            self.block_ms = round((time.perf_counter() - t0) * 1000, 1)

        out = out * self.out_vol
        board = self._current_board()
        if board is not None and out.size:
            try:
                out = board(out.astype(np.float32), DEVICE_RATE)
            except Exception as exc:
                self.last_error = f"Effects: {exc}"

        if out.size < block.size:
            out = np.pad(out, (0, block.size - out.size))
        out = np.clip(out[: block.size], -1.0, 1.0).astype(np.float32)
        self.out_level = _level(out)
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

    def _resolve(self) -> tuple[int | None, int | None, int | None]:
        from voiceapp_engine import audio_io

        devs = (self._devices_provider or audio_io.list_devices)()
        if self.input_name is None or self.output_name is None:
            self.devices()
        inp = audio_io.find_by_name(devs, self.input_name, "input")
        out = audio_io.find_by_name(devs, self.output_name, "output")
        mon = audio_io.find_by_name(devs, self.monitor_name, "output") if self.use_monitor else None
        if inp is None:
            raise ValueError(f"microphone '{self.input_name}' isn't connected; pick another one")
        if out is None:
            raise ValueError(f"output '{self.output_name}' isn't connected; pick another one")
        return inp, out, mon

    def start(self) -> None:
        if self.running:
            return
        if self.model_name is None and self.saved_model and (self.models_folder / f"{self.saved_model}.pth").is_file():
            self.load_model(self.saved_model)
        inp, out, mon = self._resolve()
        if self._stream_factory is None:
            from voiceapp_engine.audio_io import Streams

            self._stream_factory = Streams
        while not self._in_queue.empty():
            self._in_queue.get_nowait()
        streams = self._stream_factory(DEVICE_RATE, self.block_size, inp, out, mon, on_input=self._on_input)
        self.blocks_done = 0
        self._stop.clear()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        try:
            streams.start()
        except Exception as exc:
            self._stop.set()
            raise ValueError(f"couldn't open the audio devices: {exc}") from exc
        self._streams = streams
        self.last_error = None

    def stop(self) -> None:
        self._stop.set()
        if self._streams is not None:
            self._streams.stop()
            self._streams = None
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        self.in_level = self.out_level = 0.0

    def _restart_if_running(self) -> None:
        if self.running:
            self.stop()
            self.start()

    def status(self) -> dict[str, Any]:
        if self.loading:
            phase = "loading"
        elif not self.running:
            phase = "off"
        elif self.muted:
            phase = "muted"
        elif self.bypassed:
            phase = "real"
        elif self.warming_up:
            phase = "warming"
        else:
            phase = "live"
        return {
            "phase": phase,
            "running": self.running,
            "model": self.model_name,
            "saved_model": self.saved_model,
            "latency": self.latency,
            "latency_ms": round(self.block_size / DEVICE_RATE * 1000),
            "pitch": self.pitch,
            "index_rate": self.index_rate,
            "in_gain": self.in_gain,
            "out_vol": self.out_vol,
            "monitor_vol": self.monitor_vol,
            "use_monitor": self.use_monitor,
            "bypassed": self.bypassed,
            "muted": self.muted,
            "devices": {"input": self.input_name, "output": self.output_name, "monitor": self.monitor_name},
            "fx": self.fx.to_dict(),
            "levels": {"in": round(self.in_level, 3), "out": round(self.out_level, 3)},
            "block_ms": self.block_ms,
            "load_ms": self.load_ms,
            "last_error": self.last_error,
        }
