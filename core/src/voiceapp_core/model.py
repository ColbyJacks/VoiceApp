"""Reading RVC-style .pth voice models.

An RVC inference checkpoint is a torch-saved dict with these keys:

    weight   state dict of the synthesizer network
    config   list of synthesizer hyperparameters; the last entry is the sample rate
    f0       1 if the model uses pitch (f0) guidance, else 0
    version  "v1" (256-dim features) or "v2" (768-dim features)
    sr       sample rate label such as "40k" (optional, older exports omit it)
    info     free-form text written at export time (optional)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SUPPORTED_VERSIONS = ("v1", "v2")


class ModelLoadError(ValueError):
    """The file is missing or is not a usable RVC voice model."""


@dataclass(frozen=True)
class ModelInfo:
    name: str
    sample_rate: int
    version: str
    uses_pitch: bool
    info: str = ""
    path: Path | None = None
    config: tuple[Any, ...] = field(default=(), repr=False)

    @property
    def feature_dim(self) -> int:
        return 256 if self.version == "v1" else 768


_SR_LABELS = {"32k": 32000, "40k": 40000, "48k": 48000}


def parse_checkpoint(ckpt: Mapping[str, Any], name: str = "model", path: Path | None = None) -> ModelInfo:
    """Validate an already-loaded checkpoint dict and describe it."""
    if not isinstance(ckpt, Mapping):
        raise ModelLoadError(f"{name}: expected a checkpoint dict, got {type(ckpt).__name__}")
    if "weight" not in ckpt:
        if "model" in ckpt or "optimizer" in ckpt:
            raise ModelLoadError(
                f"{name}: this looks like a training checkpoint (G_*.pth/D_*.pth). "
                "Export it to an inference model in VoiceAppStudio first."
            )
        raise ModelLoadError(f"{name}: no 'weight' entry, not an RVC voice model")

    config = tuple(ckpt.get("config") or ())
    sample_rate = _sample_rate(ckpt, config, name)

    version = str(ckpt.get("version", "v1"))
    if version not in SUPPORTED_VERSIONS:
        raise ModelLoadError(f"{name}: unsupported model version {version!r}")

    return ModelInfo(
        name=name,
        sample_rate=sample_rate,
        version=version,
        uses_pitch=bool(int(ckpt.get("f0", 1))),
        info=str(ckpt.get("info", "")),
        path=path,
        config=config,
    )


def _sample_rate(ckpt: Mapping[str, Any], config: tuple[Any, ...], name: str) -> int:
    if config and isinstance(config[-1], int) and config[-1] > 0:
        return config[-1]
    label = ckpt.get("sr")
    if isinstance(label, int) and label > 0:
        return label
    if isinstance(label, str) and label in _SR_LABELS:
        return _SR_LABELS[label]
    raise ModelLoadError(f"{name}: could not determine the model's sample rate")


def load_checkpoint(path: str | Path) -> dict[str, Any]:
    """Load a .pth file onto the CPU. Imports torch on first use."""
    path = Path(path)
    if not path.is_file():
        raise ModelLoadError(f"{path}: file not found")
    import torch  # deferred so importing voiceapp_core stays fast

    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:  # torch raises a variety of types for bad files
        raise ModelLoadError(f"{path.name}: could not read file ({exc})") from exc


def load_model_info(path: str | Path) -> ModelInfo:
    path = Path(path)
    return parse_checkpoint(load_checkpoint(path), name=path.stem, path=path)
