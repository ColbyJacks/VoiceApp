"""Find RVC source files by module name.

Applio located its own scripts and config files relative to the working
directory ("rvc/train/train.py"). In this repo the rvc code is split between
core/ and studio/, so it is found through the import system instead, while
data (rvc/models, logs, assets/config.json) stays relative to the working
directory as before.
"""

import importlib.util
import os


def module_path(name: str) -> str:
    """Path of a module's .py file, without importing (running) it."""
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        raise ModuleNotFoundError(name)
    return spec.origin


def module_dir(name: str) -> str:
    return os.path.dirname(module_path(name))
