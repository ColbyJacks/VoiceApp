"""Remembers the user's setup between launches (settings.json in the data folder)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "model": None,
    "input_name": None,
    "output_name": None,
    "monitor_name": None,
    "use_monitor": False,
    "latency": "low",
    "pitch": 0.0,
    "index_rate": 0.75,
    "in_gain": 1.0,
    "out_vol": 1.0,
    "monitor_vol": 1.0,
    "fx": {},
}


def load(path: Path) -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            data.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
