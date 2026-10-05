"""Line-delimited JSON protocol between the Tauri UI and this sidecar.

Request:  {"id": 1, "method": "load_model", "params": {"path": "C:/.../voice.pth"}}
Response: {"id": 1, "result": {...}}  or  {"id": 1, "error": "message"}
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
        self._methods: dict[str, Callable[..., Any]] = {
            "hello": self._hello,
            "list_devices": self._list_devices,
            "set_devices": self._set_devices,
            "load_model": self._load_model,
            "set_pitch": self._set_pitch,
            "start": self._start,
            "stop": self._stop,
            "status": self.engine.status,
        }

    def _hello(self) -> dict[str, Any]:
        return {"engine": __version__, "core": core_version}

    def _list_devices(self) -> list[dict[str, Any]]:
        from voiceapp_engine.audio_io import list_devices

        return list_devices()

    def _set_devices(self, input: int | None = None, output: int | None = None) -> dict[str, Any]:
        self.engine.set_devices(input, output)
        return self.engine.status()

    def _load_model(self, path: str | None = None) -> dict[str, Any]:
        return self.engine.load_model(path)

    def _set_pitch(self, semitones: float) -> dict[str, Any]:
        self.engine.set_pitch(semitones)
        return self.engine.status()

    def _start(self) -> dict[str, Any]:
        self.engine.start()
        return self.engine.status()

    def _stop(self) -> dict[str, Any]:
        self.engine.stop()
        return self.engine.status()

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
