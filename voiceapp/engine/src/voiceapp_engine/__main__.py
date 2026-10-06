"""Sidecar entry point: read requests on stdin, write responses on stdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from voiceapp_engine.engine import Engine
from voiceapp_engine.protocol import Dispatcher


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="voiceapp-engine")
    parser.add_argument("--models", type=Path, help="folder of .pth/.index files (default: %%APPDATA%%\\VoiceApp\\models)")
    args = parser.parse_args(argv)

    dispatcher = Dispatcher(Engine(models_folder=args.models))
    try:
        for line in sys.stdin:
            if line.strip():
                print(dispatcher.handle_line(line), flush=True)
    finally:
        dispatcher.engine.stop()


if __name__ == "__main__":
    main()
