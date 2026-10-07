"""Global hotkeys (work while a game or Discord has focus). Optional: if the
keyboard package is missing or blocked, the app works without them."""

from __future__ import annotations

from typing import Callable


def register(bindings: dict[str, Callable[[], None]]) -> bool:
    try:
        import keyboard

        for key, fn in bindings.items():
            keyboard.add_hotkey(key, fn)
        return True
    except Exception:
        return False


def unregister() -> None:
    try:
        import keyboard

        keyboard.unhook_all()
    except Exception:
        pass
