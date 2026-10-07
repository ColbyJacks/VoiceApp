"""Line-delimited JSON protocol between the Tauri UI and this sidecar.

Request:  {"id": 1, "method": "load_model", "params": {"model": "AnimeYan"}}
Response: {"id": 1, "result": {...}}  or  {"id": 1, "error": "message"}
Event:    {"event": "state", "data": {...status...}}   (no id; pushed any time)

Events: "state" (status changed, also ~10x/s while running for the meters),
"progress" (base model download), "hotkey" (F7/F8 pressed).

Slow methods (loading a voice, starting audio, downloading) run on a worker
thread so status polls and meters keep flowing while they work. Their reply
arrives when they finish.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from voiceapp_core import ModelLoadError, __version__ as core_version
from voiceapp_engine import __version__, basemodels
from voiceapp_engine.engine import Engine

SLOW = {"load_model", "start", "set_latency", "download_base_models", "import_model"}


class Dispatcher:
    def __init__(self, engine: Engine, write: Callable[[str], None],
                 base_folder: Path | None = None) -> None:
        self.engine = engine
        self._write_raw = write
        self._write_lock = threading.Lock()
        self._slow_lock = threading.Lock()  # one slow job at a time, in order
        self.base_folder = Path(base_folder) if base_folder else Path.cwd()
        engine.notify = self.event
        e = engine
        self._methods: dict[str, Callable[..., Any]] = {
            "hello": self._hello,
            "status": e.status,
            "devices": e.devices,
            "set_devices": self._with_status(e.set_devices),
            "list_models": e.list_models,
            "load_model": self._with_status(lambda model=None: e.load_model(model)),
            "import_model": e.import_model,
            "open_models_folder": self._with_status(e.open_models_folder),
            "set": self._with_status(e.set_params),
            "set_latency": self._with_status(e.set_latency),
            "set_fx": self._with_status(e.set_fx),
            "toggle_bypass": self._with_status(e.toggle_bypass),
            "toggle_mute": self._with_status(e.toggle_mute),
            "start": self._with_status(e.start),
            "stop": self._with_status(e.stop),
            "download_base_models": self._download_base_models,
        }

    # ---- output ---------------------------------------------------------

    def write(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj)
        with self._write_lock:
            self._write_raw(line)

    def event(self, name: str, data: dict[str, Any]) -> None:
        self.write({"event": name, "data": data})

    # ---- methods --------------------------------------------------------

    def _hello(self) -> dict[str, Any]:
        return {
            "engine": __version__,
            "core": core_version,
            "base_models_ready": basemodels.has_all(self.base_folder),
            "models_folder": str(self.engine.models_folder),
        }

    def _with_status(self, fn: Callable[..., Any]) -> Callable[..., dict[str, Any]]:
        def call(**params: Any) -> dict[str, Any]:
            fn(**params)
            return self.engine.status()

        return call

    def _download_base_models(self) -> dict[str, Any]:
        def progress(done: int, total: int) -> None:
            self.event("progress", {"done": done, "total": total})

        basemodels.download(self.base_folder, progress)
        return {"base_models_ready": basemodels.has_all(self.base_folder)}

    # ---- dispatch -------------------------------------------------------

    def _run(self, req_id: Any, method: Callable[..., Any], params: dict[str, Any]) -> None:
        try:
            result = method(**params)
            self.write({"id": req_id, "result": result})
        except (ModelLoadError, LookupError, TypeError, ValueError) as exc:
            self.write({"id": req_id, "error": str(exc)})
        except Exception as exc:  # keep the sidecar alive whatever happens
            self.write({"id": req_id, "error": f"{type(exc).__name__}: {exc}"})

    def _run_slow(self, req_id: Any, method: Callable[..., Any], params: dict[str, Any]) -> None:
        with self._slow_lock:
            self._run(req_id, method, params)
        self.event("state", self.engine.status())

    def handle_line(self, line: str, wait: bool = False) -> threading.Thread | None:
        """Answer one request line. Slow methods return their worker thread
        (joined first when `wait` is set, which tests use)."""
        try:
            request = json.loads(line)
        except ValueError as exc:
            self.write({"id": None, "error": f"bad request: {exc}"})
            return None
        req_id = request.get("id")
        name = request.get("method", "")
        params = request.get("params") or {}
        method = self._methods.get(name)
        if method is None:
            self.write({"id": req_id, "error": f"unknown method {name!r}"})
            return None
        if name not in SLOW:
            self._run(req_id, method, params)
            return None
        t = threading.Thread(target=self._run_slow, args=(req_id, method, params), daemon=True)
        t.start()
        if wait:
            t.join()
        return t


class Ticker:
    """Pushes a "state" event ~10 times a second while audio runs, so the
    meters move without the UI polling."""

    def __init__(self, dispatcher: Dispatcher, interval: float = 0.1) -> None:
        self.dispatcher = dispatcher
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            if self.dispatcher.engine.running:
                self.dispatcher.event("state", self.dispatcher.engine.status())
