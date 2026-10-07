"""Sidecar entry point: read requests on stdin, write replies and events on stdout.

The RVC code loads its shared networks from rvc/models/... relative to the
working directory, so we chdir to a "base folder": the folder next to the
bundled exe when the installer shipped them there, else %APPDATA%\\VoiceApp
(where the first-run download puts them).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from voiceapp_core.paths import data_dir
from voiceapp_engine import basemodels, hotkeys
from voiceapp_engine.engine import Engine
from voiceapp_engine.protocol import Dispatcher, Ticker


def pick_base_folder(data_folder: Path) -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent
        if basemodels.has_all(bundled):
            return bundled
    return data_folder


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="voiceapp-engine")
    parser.add_argument("--data", type=Path,
                        help="settings + models folder (default: %%APPDATA%%\\VoiceApp)")
    parser.add_argument("--no-hotkeys", action="store_true")
    args = parser.parse_args(argv)

    # stdout carries the protocol only; anything the RVC code prints goes to stderr.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")  # voice names can be any language
        except (AttributeError, ValueError):
            pass
    out = sys.stdout
    sys.stdout = sys.stderr

    def write(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    data_folder = args.data or data_dir("VoiceApp")
    data_folder.mkdir(parents=True, exist_ok=True)
    base = pick_base_folder(data_folder)
    os.chdir(base)

    engine = Engine(data_folder=data_folder)
    dispatcher = Dispatcher(engine, write, base_folder=base)
    ticker = Ticker(dispatcher)
    ticker.start()

    if not args.no_hotkeys:
        def hotkey(name: str, toggle) -> None:
            toggle()
            dispatcher.event("hotkey", {"key": name})

        hotkeys.register({
            "f8": lambda: hotkey("f8", engine.toggle_bypass),
            "f7": lambda: hotkey("f7", engine.toggle_mute),
        })

    dispatcher.event("ready", {})
    try:
        for line in sys.stdin:
            if line.strip():
                dispatcher.handle_line(line)
    finally:
        ticker.stop()
        hotkeys.unregister()
        engine.stop()


if __name__ == "__main__":
    main()
