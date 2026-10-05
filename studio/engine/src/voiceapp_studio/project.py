"""A training project on disk and the steps that build a model from it."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

STEPS = ("preprocess", "extract", "train", "index", "export")
SAMPLE_RATES = (32000, 40000, 48000)


@dataclass
class TrainingConfig:
    name: str
    sample_rate: int = 40000
    version: str = "v2"
    uses_pitch: bool = True
    epochs: int = 200
    batch_size: int = 8
    save_every: int = 25

    def validate(self) -> None:
        if not self.name or any(c in self.name for c in '\\/:*?"<>|'):
            raise ValueError(f"invalid project name {self.name!r}")
        if self.sample_rate not in SAMPLE_RATES:
            raise ValueError(f"sample rate must be one of {SAMPLE_RATES}")
        if self.version not in ("v1", "v2"):
            raise ValueError("version must be 'v1' or 'v2'")
        if self.epochs < 1 or self.batch_size < 1 or self.save_every < 1:
            raise ValueError("epochs, batch size and save interval must be positive")


class Project:
    """Folder layout:

        <root>/project.json   training settings
        <root>/dataset/       the user's raw recordings
        <root>/work/          sliced audio, features, pitch curves
        <root>/checkpoints/   G_*.pth / D_*.pth training checkpoints
        <root>/export/        the finished inference .pth and .index
    """

    SUBDIRS = ("dataset", "work", "checkpoints", "export")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def config_path(self) -> Path:
        return self.root / "project.json"

    @classmethod
    def create(cls, root: str | Path, config: TrainingConfig) -> "Project":
        config.validate()
        project = cls(root)
        if project.config_path.exists():
            raise FileExistsError(f"{project.root} already has a project")
        for sub in cls.SUBDIRS:
            (project.root / sub).mkdir(parents=True, exist_ok=True)
        project.save_config(config)
        return project

    def save_config(self, config: TrainingConfig) -> None:
        self.config_path.write_text(json.dumps(asdict(config), indent=2))

    def load_config(self) -> TrainingConfig:
        return TrainingConfig(**json.loads(self.config_path.read_text()))
