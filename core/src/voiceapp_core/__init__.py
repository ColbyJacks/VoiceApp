"""Shared core for Voice App and VoiceAppStudio.

Importing this package must stay cheap: heavy libraries such as torch are
imported inside the functions that need them, never at module level, so the
Voice App engine boots quickly.
"""

from voiceapp_core.audio import semitones_to_ratio
from voiceapp_core.converter import Converter, PassthroughConverter, load_converter
from voiceapp_core.model import ModelInfo, ModelLoadError, load_model_info, parse_checkpoint

__all__ = [
    "Converter",
    "ModelInfo",
    "ModelLoadError",
    "PassthroughConverter",
    "load_converter",
    "load_model_info",
    "parse_checkpoint",
    "semitones_to_ratio",
]

__version__ = "0.1.0"
