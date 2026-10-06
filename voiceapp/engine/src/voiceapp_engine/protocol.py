"""Line-delimited JSON protocol between the Tauri UI and this sidecar.

Request:  {"id": 1, "method": "load_model", "params": {"model": "AnimeYan"}}
Response: {"id": 1, "result": {...status...}}  or  {"id": 1, "error": "message"}

Every method except hello, list_devices and list_models answers with the
full engine status, so the UI can redraw from a single reply.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from voiceapp_core import ModelLoadError, __version__ as core_version
from voiceapp_engine import __version__
from voiceapp_engine.engine import Engine


class Dispatcher:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or Engine()
        e = self.engine
        self._methods: dict[str, Callable[..., Any]] = {
            "hello": lambda: {"engine": __version__, "core": core_version},
            "list_devices": self._list_devices,
            "list_models": e.list_models,
            "status": e.status,
            "set_devices": self._with_status(e.set_devices),
            "load_model": self._with_status(lambda model=None: e.load_model(model)),
            "set": self._with_status(e.set_params),
            "set_fx": self._with_status(e.set_fx),
            "toggle_bypass": self._with_status(e.toggle_bypass),
            "toggle_mute": self._with_status(e.toggle_mute),
            "start": self._with_status(e.start),
            "stop": self._with_status(e.stop),
        }

    def _with_status(self, fn: Callable[..., Any]) -> Callable[..., dict[str, Any]]:
        def call(**params: Any) -> dict[str, Any]:
            fn(**params)
            return self.engine.status()

        return call

    def _list_devices(self) -> dict[str, Any]:
        from voiceapp_engine.audio_io import default_devices, list_devices

        devices = list_devices()
        inp, out = default_devices(devices)
        return {"devices": devices, "default_input": inp, "default_output": out}

    def handle_line(self, line: str) -> str:
        req_id = None
        try:
            request = json.loads(line)
            req_id = request.get("id")
            method = self._methods.get(request.get("method", ""))
            if method is None:
                raise LookupError(f"unknown method {request.get('method')!r}")
            result = method(**(request.get("params") or {}))
            return json.dumps({"id": req_id, "result": result})
        except (ModelLoadError, LookupError, TypeError, ValueError) as exc:
            return json.dumps({"id": req_id, "error": str(exc)})
        except Exception as exc:  # keep the sidecar alive whatever happens
            return json.dumps({"id": req_id, "error": f"{type(exc).__name__}: {exc}"})
