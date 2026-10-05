"""Per-user folders, shared so both apps agree on where models live."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir(app: str = "VoiceApp") -> Path:
    """%APPDATA%\\<app> on Windows, ~/.local/share/<app> elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / app


def models_dir() -> Path:
    """Where Voice App looks for .pth files and where Studio exports them."""
    return data_dir("VoiceApp") / "models"
