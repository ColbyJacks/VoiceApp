"""Guards the split: Voice App must stay light enough for an easy install."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Libraries only training (or the old Gradio UI) needs. None may reach the
# Voice App engine or core. torchaudio and faiss are NOT here: realtime
# inference uses them for resampling and the .index lookup.
TRAINING_ONLY = {
    "tensorboard", "sklearn", "scikit-learn", "matplotlib", "gradio",
    "yt_dlp", "yt-dlp", "edge_tts", "edge-tts", "voiceapp_studio", "voiceapp-studio",
}


def imported_modules(package_dir: Path) -> set[str]:
    found = set()
    for path in package_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def declared_deps(pyproject: Path) -> set[str]:
    text = pyproject.read_text()
    return {m.lower() for m in re.findall(r'"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*(?:[<>=!~].*)?"', text)}


def test_voiceapp_and_core_never_import_training_libraries():
    for pkg in (ROOT / "core/src/voiceapp_core", ROOT / "voiceapp/engine/src/voiceapp_engine"):
        assert not imported_modules(pkg) & TRAINING_ONLY, pkg


def test_voiceapp_and_core_do_not_declare_training_dependencies():
    for pyproject in (ROOT / "core/pyproject.toml", ROOT / "voiceapp/engine/pyproject.toml"):
        assert not declared_deps(pyproject) & TRAINING_ONLY, pyproject


def test_core_does_not_depend_on_either_app():
    assert not imported_modules(ROOT / "core/src/voiceapp_core") & {"voiceapp_engine", "voiceapp_studio"}


def test_engine_imports_without_torch_or_sounddevice():
    """Quick boot: importing the engine must not pull in heavy libraries."""
    code = (
        "import sys, voiceapp_engine.protocol, voiceapp_engine.__main__;"
        "heavy = {'torch', 'sounddevice', 'pedalboard', 'rvc'} & set(sys.modules);"
        "assert not heavy, heavy"
    )
    paths = [str(ROOT / p) for p in ("core/src", "voiceapp/engine/src")]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
