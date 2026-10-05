import json

import numpy as np

from voiceapp_engine.engine import Engine
from voiceapp_engine.protocol import Dispatcher


class FakeStream:
    def __init__(self, process, rate, block, inp, out):
        self.process, self.started = process, False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False


def call(d, method, **params):
    return json.loads(d.handle_line(json.dumps({"id": 7, "method": method, "params": params})))


def test_hello_and_status():
    d = Dispatcher(Engine(stream_factory=FakeStream))
    assert call(d, "hello")["result"]["engine"] == "0.1.0"
    status = call(d, "status")["result"]
    assert status["running"] is False and status["model"] is None


def test_start_stop_and_pitch_clamp():
    d = Dispatcher(Engine(stream_factory=FakeStream))
    assert call(d, "start")["result"]["running"] is True
    assert call(d, "set_pitch", semitones=40)["result"]["pitch"] == 24.0
    assert call(d, "stop")["result"]["running"] is False


def test_errors_are_returned_not_raised(tmp_path):
    d = Dispatcher(Engine(stream_factory=FakeStream))
    assert "unknown method" in call(d, "explode")["error"]
    assert "not found" in call(d, "load_model", path=str(tmp_path / "x.pth"))["error"]
    assert json.loads(d.handle_line("not json"))["error"]
    assert call(d, "set_pitch")["error"]  # missing param


def test_process_block_falls_back_to_dry_audio_on_failure():
    engine = Engine()

    class Broken:
        sample_rate = 40000

        def set_pitch(self, s):
            pass

        def process(self, block):
            raise RuntimeError("boom")

    engine.converter = Broken()
    block = np.full(1024, 0.1, dtype=np.float32)
    assert np.array_equal(engine.process_block(block), block)
    assert engine.last_error == "boom"


def test_passthrough_keeps_block_length():
    engine = Engine()
    block = np.random.default_rng(0).standard_normal(1024).astype(np.float32)
    assert engine.process_block(block).shape == block.shape
