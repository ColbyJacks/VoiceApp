import pytest

from voiceapp_core import ModelLoadError, parse_checkpoint
from voiceapp_core.model import load_model_info


def rvc_ckpt(**overrides):
    ckpt = {"weight": {}, "config": [1025, 32, 192, 40000], "f0": 1, "version": "v2", "info": "200epoch"}
    ckpt.update(overrides)
    return ckpt


def test_parses_v2_model():
    info = parse_checkpoint(rvc_ckpt(), name="alice")
    assert (info.name, info.sample_rate, info.version, info.uses_pitch) == ("alice", 40000, "v2", True)
    assert info.feature_dim == 768


def test_sample_rate_falls_back_to_label():
    info = parse_checkpoint(rvc_ckpt(config=[], sr="48k", version="v1", f0=0))
    assert info.sample_rate == 48000
    assert info.feature_dim == 256
    assert not info.uses_pitch


def test_training_checkpoint_gets_helpful_error():
    with pytest.raises(ModelLoadError, match="Export it"):
        parse_checkpoint({"model": {}, "optimizer": {}})


@pytest.mark.parametrize("bad", [{}, {"weight": {}}, rvc_ckpt(version="v9"), "nope"])
def test_rejects_bad_checkpoints(bad):
    with pytest.raises(ModelLoadError):
        parse_checkpoint(bad)


def test_missing_file(tmp_path):
    with pytest.raises(ModelLoadError, match="not found"):
        load_model_info(tmp_path / "missing.pth")
