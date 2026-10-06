import numpy as np
import pytest

from voiceapp_core.audio import resample, rms_db, semitones_to_ratio, to_mono
from voiceapp_core.converter import Converter, PassthroughConverter, load_converter


def test_semitones():
    assert semitones_to_ratio(12) == pytest.approx(2.0)
    assert semitones_to_ratio(-12) == pytest.approx(0.5)
    assert semitones_to_ratio(0) == 1.0


def test_resample_length_and_identity():
    x = np.sin(np.linspace(0, 20, 4800)).astype(np.float32)
    assert resample(x, 48000, 40000).shape == (4000,)
    assert np.array_equal(resample(x, 48000, 48000), x)


def test_to_mono_and_levels():
    stereo = np.ones((10, 2), dtype=np.float32) * 0.5
    assert to_mono(stereo).shape == (10,)
    assert rms_db(to_mono(stereo)) == pytest.approx(-6.02, abs=0.01)
    assert rms_db(np.zeros(10)) == -96.0


def test_passthrough_is_a_converter():
    conv = load_converter(None)
    assert isinstance(conv, PassthroughConverter)
    assert isinstance(conv, Converter)
    block = np.arange(4, dtype=np.float32)
    assert np.array_equal(conv.process(block), block)


def test_find_index(tmp_path):
    from voiceapp_core.converter import find_index

    (tmp_path / "a.pth").touch()
    (tmp_path / "b.index").touch()
    assert find_index(tmp_path / "a.pth") is None  # never borrows another voice's index
    (tmp_path / "a.index").touch()
    assert find_index(tmp_path / "a.pth") == tmp_path / "a.index"
