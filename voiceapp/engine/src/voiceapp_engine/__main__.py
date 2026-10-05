"""Sidecar entry point: read requests on stdin, write responses on stdout."""

from __future__ import annotations

import sys

from voiceapp_engine.protocol import Dispatcher


def main() -> None:
    dispatcher = Dispatcher()
    try:
        for line in sys.stdin:
            if line.strip():
                print(dispatcher.handle_line(line), flush=True)
    finally:
        dispatcher.engine.stop()


if __name__ == "__main__":
    main()
