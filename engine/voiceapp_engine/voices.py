"""The voices folder: .pth models and their .index files."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# Applio names trained models like "Name_320e_16960s.pth" and indexes
# "Name.index" or "added_IVF1234_Flat_nprobe_1_Name_v2.index".
_EPOCH_SUFFIX = re.compile(r"_\d+e_\d+s$", re.IGNORECASE)


def base_name(pth: Path) -> str:
    return _EPOCH_SUFFIX.sub("", pth.stem)


def find_index(pth: Path) -> Path | None:
    """The index that belongs to this model, or None.

    Never falls back to an unrelated index: pairing a model with another
    voice's index makes it sound like a blend of the two.
    """
    exact = pth.with_suffix(".index")
    if exact.is_file():
        return exact
    base = base_name(pth).lower()
    matches = [
        p
        for p in pth.parent.glob("*.index")
        if re.search(rf"(^|_){re.escape(base)}(_|$)", p.stem.lower()) or base_name(p).lower() == base
    ]
    if not matches:
        return None
    # Prefer the closest name, then Applio's "added_" index over "trained_".
    return sorted(matches, key=lambda p: (abs(len(p.stem) - len(base)), "trained" in p.stem.lower()))[0]


def list_voices(folder: Path) -> list[dict]:
    voices = []
    for pth in sorted(folder.glob("*.pth"), key=lambda p: p.stem.lower()):
        index = find_index(pth)
        voices.append(
            {
                "name": pth.stem,
                "label": base_name(pth),
                "file": pth.name,
                "index": index.name if index else None,
                "size_mb": round(pth.stat().st_size / 1e6, 1),
            }
        )
    return voices


def resolve(folder: Path, name: str) -> Path:
    pth = folder / (name if name.lower().endswith(".pth") else f"{name}.pth")
    if not pth.is_file():
        raise FileNotFoundError(f"Voice \"{name}\" isn't in {folder}.")
    return pth


def import_files(folder: Path, paths: list[str]) -> list[str]:
    """Copy .pth/.index files into the voices folder. Returns the copied names."""
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in map(Path, paths):
        if p.suffix.lower() not in (".pth", ".index") or not p.is_file():
            continue
        target = folder / p.name
        if p.resolve() != target.resolve():
            shutil.copy2(p, target)
        copied.append(p.name)
    return copied
