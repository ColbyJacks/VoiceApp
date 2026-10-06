import json

import numpy as np
import pytest

from voiceapp_engine.engine import Engine
from voiceapp_engine.protocol import Dispatcher


class FakeStreams:
    def __init__(self, rate, block, inp, out, mon, on_input=None):
        self.on_input, self.started, self.played = on_input, False, []

    def start(self):
        self.started = True

    def play(self, block, monitor=None):
        self.played.append((block, monitor))

    def stop(self):
        self.started = False


class FakeConverter:
    sample_rate = 48000

    def __init__(self, path, block_size):
        self.path, self.pitch, self.index_rate = path, 0.0, None

    def set_pitch(self, s):
        self.pitch = s

    def process(self, block):
        return block * 0.5


@pytest.fixture
def engine(tmp_path):
    e = Engine(stream_factory=FakeStreams, converter_factory=FakeConverter, models_folder=tmp_path)
    e._board_dirty = False  # keep pedalboard out of protocol tests
    return e


def call(d, method, **params):
    return json.loads(d.handle_line(json.dumps({"id": 7, "method": method, "params": params})))


def test_hello_and_status(engine):
    d = Dispatcher(engine)
    assert call(d, "hello")["result"]["engine"] == "0.1.0"
    status = call(d, "status")["result"]
    assert status["running"] is False and status["model"] is None and status["mode"] == "voice"
    assert status["out_vol"] == 1.5


def test_start_stop_and_clamping(engine):
    d = Dispatcher(engine)
    assert call(d, "start")["result"]["running"] is True
    status = call(d, "set", pitch=40, out_vol=-1, index_rate=0.5)["result"]
    assert (status["pitch"], status["out_vol"], status["index_rate"]) == (24.0, 0.0, 0.5)
    assert call(d, "stop")["result"]["running"] is False


def test_models_by_name(engine, tmp_path):
    (tmp_path / "AnimeYan.pth").touch()
    (tmp_path / "AM.pth").touch()
    d = Dispatcher(engine)
    assert call(d, "list_models")["result"] == ["AM", "AnimeYan"]
    call(d, "set", pitch=5, index_rate=0.3)
    assert call(d, "load_model", model="AnimeYan")["result"]["model"] == "AnimeYan"
    assert engine.converter.path == tmp_path / "AnimeYan.pth"
    assert engine.converter.pitch == 5 and engine.converter.index_rate == 0.3
    assert call(d, "load_model")["result"]["model"] is None


def test_modes_and_fx(engine):
    d = Dispatcher(engine)
    assert call(d, "toggle_bypass")["result"]["mode"] == "real"
    assert call(d, "toggle_mute")["result"]["mode"] == "muted"
    assert call(d, "set_fx", reverb=True, radio_bits=6)["result"]["fx"]["reverb"] is True
    assert "unknown FX" in call(d, "set_fx", wah=True)["error"]


def test_errors_are_returned_not_raised(engine):
    d = Dispatcher(engine)
    assert "unknown method" in call(d, "explode")["error"]
    assert "unknown settings" in call(d, "set", loudness=3)["error"]
    assert json.loads(d.handle_line("not json"))["error"]


def test_audio_path(engine):
    engine.load_model(None)
    engine.converter = FakeConverter(None, 0)
    block = np.full(1024, 0.2, dtype=np.float32)
    engine.out_vol = 1.0
    assert np.allclose(engine.process_block(block), 0.1)  # through the model
    engine.toggle_bypass()
    assert np.allclose(engine.process_block(block), 0.2)  # real voice
    engine.toggle_mute()
    assert not engine.process_block(block).any()
    assert engine.in_level > 0 and engine.out_level == 0.0


def test_failing_model_falls_back_to_dry_voice(engine):
    class Broken(FakeConverter):
        def process(self, block):
            raise RuntimeError("boom")

    engine.converter = Broken(None, 0)
    engine.out_vol = 1.0
    block = np.full(1024, 0.1, dtype=np.float32)
    assert np.allclose(engine.process_block(block), block)
    assert engine.last_error == "boom"


def test_worker_feeds_streams(engine):
    import time

    engine.use_monitor = True
    engine.start()
    engine._streams.on_input(np.full(256, 0.1, dtype=np.float32))
    for _ in range(100):
        if engine._streams.played:
            break
        time.sleep(0.01)
    out, mon = engine._streams.played[0]
    assert out.shape == (256,) and mon is not None
    engine.stop()
