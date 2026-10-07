r"""Streams and the conversion worker.

    mic --(input stream, one block per callback)--> queue --> worker
    worker: gain -> mute | real voice | AI voice -> effects -> volume -> limiter
    worker --> output FIFO --(output stream, small callbacks)--> CABLE / speakers
           \-> monitor FIFO --> headphones (optional)

The output side reads from a FIFO in small chunks instead of whole blocks, and
waits for a little extra audio ("cushion") before playing, so a block that
converts a few ms late doesn't cause a gap.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

import numpy as np
import sounddevice as sd

from voiceapp_engine import devices
from voiceapp_engine.converter import RATE
from voiceapp_engine.fx import build_board, soft_limit


class Fifo:
    """Thread-safe mono float32 ring buffer that plays only once primed."""

    def __init__(self, capacity: int, cushion: int):
        self.buf = np.zeros(capacity, dtype=np.float32)
        self.cap = capacity
        self.cushion = cushion
        self.start = 0
        self.size = 0
        self.primed = False
        self.underruns = 0
        self.lock = threading.Lock()

    def clear(self) -> None:
        with self.lock:
            self.start = self.size = 0
            self.primed = False

    def write(self, x: np.ndarray, max_fill: int) -> None:
        with self.lock:
            x = x[-self.cap:]
            n = len(x)
            end = (self.start + self.size) % self.cap
            first = min(n, self.cap - end)
            self.buf[end:end + first] = x[:first]
            self.buf[:n - first] = x[first:]
            self.size += n
            # Drop the oldest audio if we're too far ahead (device clocks
            # drift), so latency can't creep up over a long session.
            excess = self.size - max_fill
            if excess > 0:
                self.start = (self.start + excess) % self.cap
                self.size -= excess

    def read_into(self, out: np.ndarray) -> None:
        frames = len(out)
        with self.lock:
            if not self.primed:
                if self.size < self.cushion:
                    out.fill(0)
                    return
                self.primed = True
            n = min(frames, self.size)
            first = min(n, self.cap - self.start)
            out[:first] = self.buf[self.start:self.start + first]
            out[first:n] = self.buf[:n - first]
            self.start = (self.start + n) % self.cap
            self.size -= n
            if n < frames:
                out[n:] = 0
                self.primed = False
                self.underruns += 1


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


class AudioEngine:
    def __init__(self, on_error: Callable[[str], None]):
        self.on_error = on_error
        self.converter = None  # VoiceConverter or None (real voice only)
        self.converter_lock = threading.Lock()

        self.params: dict[str, float] = {
            "pitch": 0.0, "index_rate": 0.75, "protect": 0.33, "envelope": 1.0,
            "in_gain": 1.0, "out_vol": 1.0, "monitor_vol": 0.8, "gate_db": -50.0,
        }
        self.fx: dict[str, Any] = {}
        self._board = None
        self._board_dirty = True
        self.bypass = False
        self.mute = False
        self.monitor_enabled = False

        self.block = 8192
        self.running = False
        self._streams: list[sd._StreamBase] = []
        self._inq: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.out_fifo: Fifo | None = None
        self.mon_fifo: Fifo | None = None

        # Live stats.
        self.in_level = self.out_level = 0.0
        self.in_peak = self.out_peak = 0.0
        self.proc_ms = 0.0
        self.dropped = 0
        self.output_latency_ms = 0.0
        self.last_error: str | None = None

    # ---- settings -----------------------------------------------------

    def set_fx(self, fx: dict[str, Any]) -> None:
        self.fx = dict(fx)
        self._board_dirty = True

    def set_converter(self, converter) -> None:
        if converter is not None:
            converter.set_gate(self.params["gate_db"])
            converter.reset()
        with self.converter_lock:
            self.converter = converter

    def set_params(self, **params: float) -> None:
        self.params.update({k: float(v) for k, v in params.items()})
        if "gate_db" in params and self.converter is not None:
            self.converter.set_gate(self.params["gate_db"])

    # ---- processing ---------------------------------------------------

    def _current_board(self):
        if self._board_dirty:
            self._board_dirty = False
            try:
                self._board = build_board(self.fx) if self.fx else None
            except Exception as exc:  # a bad effect must never stop the voice
                self._board = None
                self.on_error(f"Effects disabled: {exc}")
        return self._board

    def process_block(self, raw: np.ndarray) -> np.ndarray:
        p = self.params
        x = raw * p["in_gain"]
        level = _rms(x)
        self.in_level = level
        self.in_peak = max(level, self.in_peak * 0.9)

        if self.mute:
            out = np.zeros_like(x)
        elif self.bypass or self.converter is None:
            out = x
        else:
            with self.converter_lock:
                conv = self.converter
                try:
                    if conv is None or conv.block != len(x):
                        out = x  # voice is reloading for a new block size
                    else:
                        out = conv.process(x, p["pitch"], p["index_rate"], p["protect"], p["envelope"])
                except Exception as exc:
                    self.last_error = str(exc)
                    self.on_error(f"Conversion failed, passing your real voice through: {exc}")
                    out = x
            out = np.asarray(out, dtype=np.float32)
            if out.shape != x.shape:
                out = np.resize(out, x.shape)

        if not self.mute:
            board = self._current_board()
            if board is not None:
                try:
                    out = board(out.astype(np.float32), RATE, reset=False)
                except Exception as exc:
                    self.on_error(f"Effects failed: {exc}")
                    self._board, self._board_dirty, self.fx = None, False, {}
            out = soft_limit(out * p["out_vol"])

        level = _rms(out)
        self.out_level = level
        self.out_peak = max(level, self.out_peak * 0.9)
        return out.astype(np.float32, copy=False)

    def _work(self) -> None:
        max_fill = self.block * 2 + self.out_fifo.cushion
        while not self._stop.is_set():
            try:
                raw = self._inq.get(timeout=0.1)
            except queue.Empty:
                continue
            # If conversion fell behind, skip stale blocks rather than letting
            # the delay grow.
            while self._inq.qsize() > 1:
                raw = self._inq.get_nowait()
                self.dropped += 1
            start = time.perf_counter()
            out = self.process_block(raw)
            ms = (time.perf_counter() - start) * 1000
            self.proc_ms = ms if self.proc_ms == 0 else self.proc_ms * 0.8 + ms * 0.2
            self.out_fifo.write(out, max_fill)
            if self.mon_fifo is not None and self.monitor_enabled:
                self.mon_fifo.write(out * self.params["monitor_vol"], max_fill)

    # ---- streams ------------------------------------------------------

    @devices.on_audio_thread
    def start(self, input_id: str, output_id: str, monitor_id: str | None, block: int) -> None:
        if self.running:
            self.stop()
        self.block = block
        cushion = int(0.04 * RATE)  # 40 ms margin against conversion jitter
        cap = block * 4 + cushion
        self.out_fifo = Fifo(cap, cushion)
        self.mon_fifo = Fifo(cap, cushion) if monitor_id else None
        self.dropped = 0
        self.proc_ms = 0.0
        while not self._inq.empty():
            self._inq.get_nowait()
        if self.converter is not None:
            self.converter.reset()

        in_idx, in_dev = devices.resolve(input_id, "input")
        out_idx, out_dev = devices.resolve(output_id, "output")
        in_api = input_id.split("::")[0]
        out_api = output_id.split("::")[0]
        in_ch = min(2, in_dev["max_input_channels"])

        def on_input(indata, frames, time_info, status):
            mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
            try:
                self._inq.put_nowait(mono.astype(np.float32, copy=True))
            except queue.Full:
                self.dropped += 1

        def make_output(fifo: Fifo, channels: int):
            mono = np.zeros(RATE, dtype=np.float32)

            def on_output(outdata, frames, time_info, status):
                buf = mono[:frames]
                fifo.read_into(buf)
                outdata[:] = buf[:, None]

            return on_output

        streams: list[sd._StreamBase] = []
        try:
            out_ch = min(2, out_dev["max_output_channels"])
            out_stream = sd.OutputStream(
                device=out_idx, samplerate=RATE, channels=out_ch, dtype="float32",
                latency="low", extra_settings=devices.extra_settings(out_api),
                callback=make_output(self.out_fifo, out_ch),
            )
            streams.append(out_stream)
            if monitor_id:
                mon_idx, mon_dev = devices.resolve(monitor_id, "output")
                mon_ch = min(2, mon_dev["max_output_channels"])
                streams.append(sd.OutputStream(
                    device=mon_idx, samplerate=RATE, channels=mon_ch, dtype="float32",
                    latency="low", extra_settings=devices.extra_settings(monitor_id.split("::")[0]),
                    callback=make_output(self.mon_fifo, mon_ch),
                ))
            streams.append(sd.InputStream(
                device=in_idx, samplerate=RATE, channels=in_ch, dtype="float32", blocksize=block,
                latency="low", extra_settings=devices.extra_settings(in_api), callback=on_input,
            ))
        except Exception as exc:
            for s in streams:
                s.close()
            raise RuntimeError(f"Couldn't open the audio devices: {exc}") from exc

        self._stop.clear()
        self._worker = threading.Thread(target=self._work, name="convert", daemon=True)
        self._worker.start()
        for s in streams:
            s.start()
        self._streams = streams
        self.output_latency_ms = out_stream.latency * 1000
        self.running = True

    @devices.on_audio_thread
    def stop(self) -> None:
        self._stop.set()
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams = []
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None
        self.running = False
        self.in_level = self.out_level = self.in_peak = self.out_peak = 0.0

    def stats(self) -> dict[str, Any]:
        block_ms = self.block / RATE * 1000
        cushion_ms = (self.out_fifo.cushion / RATE * 1000) if self.out_fifo else 0
        return {
            "in": self.in_level, "out": self.out_level,
            "in_peak": self.in_peak, "out_peak": self.out_peak,
            "proc_ms": round(self.proc_ms, 1),
            "load": round(self.proc_ms / block_ms, 2) if block_ms else 0,
            # Mic block + conversion + cushion + output device buffer.
            "latency_ms": round(block_ms + self.proc_ms + cushion_ms + self.output_latency_ms),
            "underruns": self.out_fifo.underruns if self.out_fifo else 0,
            "dropped": self.dropped,
        }
