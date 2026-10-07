"""JSON-lines protocol on stdin/stdout.

Requests:  {"id": 1, "method": "load_voice", "params": {"name": "AnimeYan"}}
Replies:   {"id": 1, "result": {...}}   or   {"id": 1, "error": "message"}
Events:    {"event": "state", "data": {...}}     whenever anything changes
           {"event": "levels", "data": {...}}    ~20 times a second while live
           {"event": "log", "data": {"level": "info|warn|error", "message": "..."}}

Everything else the engine (or torch, tqdm, rvc) prints goes to stderr, which
the app saves to logs\\engine.log.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


def _take_protocol_pipes():
    """Move the protocol onto private copies of stdin/stdout.

    The process's own stdin becomes NUL and its stdout becomes stderr. On
    Windows this matters: while one thread waits on a pipe, any DLL loaded by
    another thread (torch, scipy...) blocks in its C runtime start-up, which
    queries the standard handles. It also keeps stray prints from native
    code out of the protocol stream.
    """
    in_fd, out_fd = os.dup(0), os.dup(1)
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, 0)
    os.dup2(2, 1)
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        k32 = ctypes.windll.kernel32
        k32.SetStdHandle(-10, msvcrt.get_osfhandle(0))  # STD_INPUT_HANDLE
        k32.SetStdHandle(-11, msvcrt.get_osfhandle(1))  # STD_OUTPUT_HANDLE
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.stdout = sys.stderr
    return (
        os.fdopen(in_fd, "r", encoding="utf-8"),
        os.fdopen(out_fd, "w", encoding="utf-8"),
    )


PROTOCOL_IN, PROTOCOL_OUT = _take_protocol_pipes()

from voiceapp_engine import __version__, devices, voices  # noqa: E402
from voiceapp_engine.audio import AudioEngine  # noqa: E402
from voiceapp_engine.converter import PRESETS, VoiceConverter  # noqa: E402
from voiceapp_engine.fx import DEFAULT_FX  # noqa: E402

PARAM_LIMITS = {
    "pitch": (-24, 24), "index_rate": (0, 1), "protect": (0, 0.5), "envelope": (0, 1),
    "in_gain": (0, 4), "out_vol": (0, 4), "monitor_vol": (0, 2), "gate_db": (-90, -20),
}

_out_lock = threading.Lock()


def send(obj: dict[str, Any]) -> None:
    line = json.dumps(obj, separators=(",", ":"))
    with _out_lock:
        PROTOCOL_OUT.write(line + "\n")
        PROTOCOL_OUT.flush()


def event(name: str, data: Any) -> None:
    send({"event": name, "data": data})


def log(message: str, level: str = "info") -> None:
    print(f"[{level}] {message}", file=sys.stderr, flush=True)
    event("log", {"level": level, "message": message})


class Server:
    def __init__(self, voices_dir: Path):
        self.voices_dir = voices_dir
        self.audio = AudioEngine(on_error=lambda m: log(m, "warn"))
        self.audio.set_fx(DEFAULT_FX)
        self.devices = {"input": None, "output": None, "monitor": None}
        self.preset = "balanced"
        self.f0_override: str | None = None  # "rmvpe" | "fcpe" | None (preset's)
        self.voice: dict[str, Any] = {"name": None, "status": "none", "error": None}
        self.gpu: dict[str, Any] = {"status": "loading"}
        self.starting = False
        self.error: str | None = None
        self._load_lock = threading.Lock()
        self._load_seq = 0
        self._converters: dict[str, Any] = {}

    # ---- state --------------------------------------------------------

    def state(self) -> dict[str, Any]:
        a = self.audio
        return {
            "version": __version__,
            "running": a.running,
            "starting": self.starting,
            "bypass": a.bypass,
            "mute": a.mute,
            "monitor_enabled": a.monitor_enabled,
            "params": a.params,
            "fx": a.fx,
            "devices": self.devices,
            "preset": self.preset,
            "f0": self.f0_method(),
            "block_ms": round(PRESETS[self.preset]["block"] / 48),
            "voice": self.voice,
            "gpu": self.gpu,
            "error": self.error,
            "voices_dir": str(self.voices_dir),
        }

    def push_state(self) -> None:
        event("state", self.state())

    def f0_method(self) -> str:
        return self.f0_override or PRESETS[self.preset]["f0"]

    # ---- background jobs ------------------------------------------------

    def preload(self) -> None:
        """Import torch and the RVC code up front so the first voice loads fast."""
        try:
            import torch

            import rvc.realtime.core  # noqa: F401

            if torch.cuda.is_available():
                self.gpu = {"status": "ready", "name": torch.cuda.get_device_name(0), "cuda": True}
            else:
                self.gpu = {"status": "ready", "name": "CPU (no CUDA GPU found)", "cuda": False}
                log("No CUDA GPU found; voices will run on the CPU and may not keep up.", "warn")
        except Exception as exc:
            self.gpu = {"status": "error", "name": None, "error": str(exc)}
            log(f"Couldn't load torch: {exc}", "error")
            traceback.print_exc()
        self.push_state()

    def levels_loop(self) -> None:
        while True:
            time.sleep(0.05)
            if self.audio.running:
                event("levels", self.audio.stats())

    def _load(self, name: str | None, seq: int) -> None:
        with self._load_lock:
            if seq != self._load_seq:
                return  # a newer request superseded this one
            if name is None:
                self.audio.set_converter(None)
                self.voice = {"name": None, "status": "none", "error": None}
                self.push_state()
                return
            preset = PRESETS[self.preset]
            try:
                pth = voices.resolve(self.voices_dir, name)
                index = voices.find_index(pth)
                started = time.perf_counter()
                conv = VoiceConverter(pth, index, preset["block"], preset["extra"], self.f0_method())
                ms = conv.warmup()
                if seq != self._load_seq:
                    return
                self.audio.set_converter(conv)
                self.voice = {
                    "name": name, "status": "ready", "error": None,
                    "index": index.name if index else None,
                    "sample_rate": conv.sample_rate, "version": conv.version,
                    "device": conv.device, "load_s": round(time.perf_counter() - started, 1),
                    "warm_ms": round(ms, 1),
                }
                log(f"Loaded {name} ({conv.version}, {conv.sample_rate // 1000} kHz, "
                    f"index {'yes' if index else 'none'}) in {self.voice['load_s']} s")
            except Exception as exc:
                traceback.print_exc()
                if seq == self._load_seq:
                    self.voice = {"name": name, "status": "error", "error": str(exc)}
                    log(f"Couldn't load {name}: {exc}", "error")
            self.push_state()

    def load_voice_async(self, name: str | None) -> None:
        self._load_seq += 1
        seq = self._load_seq
        if name:
            self.voice = {"name": name, "status": "loading", "error": None}
        self.push_state()
        threading.Thread(target=self._load, args=(name, seq), daemon=True).start()

    # ---- methods ----------------------------------------------------------

    def m_hello(self, **_):
        return self.state()

    def m_get_state(self, **_):
        return self.state()

    def m_list_devices(self, include_legacy: bool = False, **_):
        if not self.audio.running:
            devices.refresh()
        return devices.list_devices(include_legacy)

    def m_list_voices(self, **_):
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        return voices.list_voices(self.voices_dir)

    def m_import_voices(self, paths: list[str], **_):
        copied = voices.import_files(self.voices_dir, paths)
        log(f"Added {', '.join(copied)}" if copied else "No .pth or .index files to add.")
        return {"copied": copied, "voices": voices.list_voices(self.voices_dir)}

    def m_load_voice(self, name: str | None = None, **_):
        self.load_voice_async(name)
        return self.state()

    def m_set_devices(self, input: str | None = None, output: str | None = None,
                      monitor: str | None = None, **_):
        self.devices = {"input": input, "output": output, "monitor": monitor}
        if self.audio.running:
            self._restart()
        self.push_state()
        return self.state()

    def m_set(self, **params):
        clean = {}
        for k, v in params.items():
            if k not in PARAM_LIMITS:
                raise ValueError(f"Unknown setting {k!r}")
            lo, hi = PARAM_LIMITS[k]
            clean[k] = min(hi, max(lo, float(v)))
        self.audio.set_params(**clean)
        return self.state()  # no state event: sliders send many of these

    def m_set_fx(self, **fx):
        merged = {**self.audio.fx}
        for k, v in fx.items():
            if k not in DEFAULT_FX:
                raise ValueError(f"Unknown effect setting {k!r}")
            merged[k] = type(DEFAULT_FX[k])(v)
        self.audio.set_fx(merged)
        self.push_state()
        return self.state()

    def m_set_performance(self, preset: str | None = None, f0: str | None = "keep", **_):
        if preset is not None:
            if preset not in PRESETS:
                raise ValueError(f"Unknown latency preset {preset!r}")
            self.preset = preset
        if f0 != "keep":
            if f0 not in (None, "rmvpe", "fcpe"):
                raise ValueError(f"Unknown pitch detector {f0!r}")
            self.f0_override = f0
        was_running = self.audio.running
        if was_running:
            self.audio.stop()
        if self.voice.get("name"):
            # Block size and pitch detector are fixed per loaded voice: drop
            # to the real voice until it reloads with the new settings.
            self.audio.set_converter(None)
            self.load_voice_async(self.voice["name"])
        if was_running:
            self._restart()
        self.push_state()
        return self.state()

    def m_set_bypass(self, value: bool, **_):
        self.audio.bypass = bool(value)
        self.push_state()
        return self.state()

    def m_set_mute(self, value: bool, **_):
        self.audio.mute = bool(value)
        self.push_state()
        return self.state()

    def m_toggle_bypass(self, **_):
        return self.m_set_bypass(not self.audio.bypass)

    def m_toggle_mute(self, **_):
        return self.m_set_mute(not self.audio.mute)

    def m_set_monitor(self, enabled: bool, **_):
        self.audio.monitor_enabled = bool(enabled)
        if self.audio.running:
            self._restart()
        self.push_state()
        return self.state()

    def _restart(self) -> None:
        self.audio.stop()
        self.m_start()

    def m_start(self, **_):
        self.starting = True
        self.error = None
        self.push_state()
        try:
            monitor = self.devices["monitor"] if self.audio.monitor_enabled else None
            self.audio.start(self.devices["input"], self.devices["output"], monitor,
                             PRESETS[self.preset]["block"])
            log("Live: " + (self.voice["name"] or "your real voice"))
        except Exception as exc:
            self.error = str(exc)
            log(str(exc), "error")
        finally:
            self.starting = False
            self.push_state()
        if self.error:
            raise RuntimeError(self.error)
        return self.state()

    def m_stop(self, **_):
        self.audio.stop()
        self.push_state()
        return self.state()


def main() -> None:
    parser = argparse.ArgumentParser(prog="voiceapp_engine")
    parser.add_argument("--voices", default=str(Path(__file__).resolve().parents[2] / "voices"))
    args = parser.parse_args()

    # rvc finds rvc\models\ (base models) relative to the working directory.
    os.chdir(Path(__file__).resolve().parents[1])
    server = Server(Path(args.voices))
    threading.Thread(target=server.preload, daemon=True).start()
    threading.Thread(target=server.levels_loop, daemon=True).start()
    server.push_state()

    for line in PROTOCOL_IN:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"Bad request: {exc}", "error")
            continue
        rid, method, params = req.get("id"), req.get("method", ""), req.get("params") or {}
        handler = getattr(server, f"m_{method}", None)

        def run(handler=handler, rid=rid, method=method, params=params):
            try:
                if handler is None:
                    raise ValueError(f"Unknown method {method!r}")
                send({"id": rid, "result": handler(**params)})
            except Exception as exc:
                if not isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)):
                    traceback.print_exc()
                send({"id": rid, "error": str(exc)})

        # Slow calls (opening devices) run off the reader thread so slider
        # updates and toggles stay responsive.
        if method in ("start", "set_devices", "set_monitor", "set_performance", "list_devices"):
            threading.Thread(target=run, daemon=True).start()
        else:
            run()

    server.audio.stop()
