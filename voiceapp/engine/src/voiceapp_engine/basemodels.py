"""The two shared networks every RVC voice needs: ContentVec (speech features)
and RMVPE (pitch). The RVC code loads them from rvc/models/... relative to the
working directory, so the engine runs from a folder that has them."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

URL_BASE = "https://huggingface.co/IAHispano/Applio/resolve/main/Resources"
FILES = {
    "rvc/models/predictors/rmvpe.pt": "predictors/rmvpe.pt",
    "rvc/models/embedders/contentvec/pytorch_model.bin": "embedders/contentvec/pytorch_model.bin",
    "rvc/models/embedders/contentvec/config.json": "embedders/contentvec/config.json",
}


def missing(base: Path) -> list[str]:
    return [rel for rel in FILES if not (base / rel).is_file()]


def has_all(base: Path) -> bool:
    return not missing(base)


def download(base: Path, progress: Callable[[int, int], None] | None = None) -> None:
    """Fetch whatever is missing into `base`, reporting (done_bytes, total_bytes)."""
    import requests

    todo = missing(base)
    if not todo:
        return
    sizes = {}
    for rel in todo:
        head = requests.head(f"{URL_BASE}/{FILES[rel]}", allow_redirects=True, timeout=30)
        sizes[rel] = int(head.headers.get("content-length", 0))
    total, done = sum(sizes.values()), 0
    for rel in todo:
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with requests.get(f"{URL_BASE}/{FILES[rel]}", stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        os.replace(tmp, dest)  # only complete files ever get the real name
