"""Guards the split: Voice App must stay light enough for an easy install."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core/src"
STUDIO = ROOT / "studio/engine/src"

# Libraries only training or the Applio web UI need. None may reach Voice App
# or core. (torchaudio, faiss and librosa are NOT here: realtime inference
# uses them for resampling, the .index lookup and mel filters.)
TRAINING_ONLY = {
    "tensorboard", "sklearn", "scikit-learn", "matplotlib", "gradio", "resampy",
    "yt_dlp", "yt-dlp", "edge_tts", "edge-tts", "pypresence", "bs4", "beautifulsoup4",
    "voiceapp_studio", "voiceapp-studio",
}
# Studio-side code Voice App must not reach into: training, and the Applio
# UI's top-level packages (tabs/, assets/, core.py).
def is_studio_module(name: str) -> bool:
    return name == "rvc.train" or name.startswith("rvc.train.") or name.split(".")[0] in {"tabs", "assets", "core"}


VOICEAPP_CODE = [CORE, ROOT / "voiceapp/engine/src", ROOT / "voiceapp/tray"]


def imports(path: Path) -> set[str]:
    """Full dotted names of absolute imports in a file or folder."""
    files = [path] if path.is_file() else path.rglob("*.py")
    found = set()
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def top_level(names: set[str]) -> set[str]:
    return {n.split(".")[0] for n in names}


def module_exists(src: Path, dotted: str) -> bool:
    base = src.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or base.is_dir()


def requirement_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[<>=!~\[ ]", line)[0].lower())
    return names


def test_voiceapp_never_imports_training_libraries():
    for path in VOICEAPP_CODE:
        assert not top_level(imports(path)) & TRAINING_ONLY, path


def test_voiceapp_never_imports_studio_code():
    for path in VOICEAPP_CODE:
        bad = sorted(n for n in imports(path) if is_studio_module(n))
        assert not bad, (path, bad)


def test_every_rvc_import_in_core_resolves_inside_core():
    """The shared engine is complete on its own: nothing it imports lives in studio/."""
    missing = set()
    for name in imports(CORE):
        if name.startswith("rvc.") and not module_exists(CORE, name):
            parent = name.rsplit(".", 1)[0]  # `from rvc.x import Name` adds rvc.x.Name
            if not module_exists(CORE, parent):
                missing.add(name)
    assert not missing, sorted(missing)


def test_studio_rvc_imports_resolve_in_core_or_studio():
    missing = set()
    for name in imports(STUDIO) | imports(ROOT / "studio/applio"):
        if not name.startswith("rvc."):
            continue
        parent = name.rsplit(".", 1)[0]
        if not any(module_exists(src, n) for src in (CORE, STUDIO) for n in (name, parent)):
            missing.add(name)
    assert not missing, sorted(missing)


def test_no_training_dependencies_declared_for_voiceapp():
    assert not requirement_names(ROOT / "voiceapp/requirements.txt") & TRAINING_ONLY
    text = (ROOT / "core/pyproject.toml").read_text() + (ROOT / "voiceapp/engine/pyproject.toml").read_text()
    declared = {m.lower() for m in re.findall(r'"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*(?:[<>=!~].*)?"', text)}
    assert not declared & TRAINING_ONLY


def test_core_does_not_depend_on_either_app():
    assert not top_level(imports(CORE)) & {"voiceapp_engine", "voiceapp_studio"}


def test_engine_imports_without_heavy_libraries():
    """Quick boot: importing the engine must not pull in torch, audio or the RVC engine."""
    code = (
        "import sys, voiceapp_engine.protocol, voiceapp_engine.__main__;"
        "heavy = {'torch', 'sounddevice', 'pedalboard', 'rvc'} & set(sys.modules);"
        "assert not heavy, heavy"
    )
    paths = [str(ROOT / p) for p in ("core/src", "voiceapp/engine/src")]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
