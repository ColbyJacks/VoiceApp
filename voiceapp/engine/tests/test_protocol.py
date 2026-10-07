import json
import subprocess
import sys

import numpy as np
import pytest

from voiceapp_engine.engine import LATENCY, Engine, find_index_for
from voiceapp_engine.protocol import Dispatcher

DEVICES = [
    {"index": 0, "name": "Microphone (HyperX SoloCast)", "host": "Windows WASAPI", "inputs": 1, "outputs": 0, "default_rate": 48000},
    {"index": 1, "name": "CABLE Output (VB-Audio Virtual Cable)", "host": "Windows WASAPI", "inputs": 1, "outputs": 0, "default_rate": 48000},
    {"index": 2, "name": "Speakers (Realtek(R) Audio)", "host": "Windows WASAPI", "inputs": 0, "outputs": 2, "default_rate": 48000},
    {"index": 3, "name": "CABLE Input (VB-Audio Virtual Cable)", "host": "Windows WASAPI", "inputs": 0, "outputs": 1, "default_rate": 48000},
]


class FakeStreams:
    last = None

    def __init__(self, rate, block, inp, out, mon, on_input=None):
        self.args = (rate, block, inp, out, mon)
        self.on_input, self.started, self.played = on_input, False, []
        FakeStreams.last = self

    def start(self):
        self.started = True

    def play(self, block, monitor=None):
        self.played.append((block, monitor))

    def stop(self):
        self.started = False


class FakeConverter:
    sample_rate = 48000

    def __init__(self, path, block_size, index_path=None):
        self.path, self.block_size, self.index_path = path, block_size, index_path
        self.pitch, self.index_rate = 0.0, None

    def set_pitch(self, s):
        self.pitch = s

    def process(self, block):
        return block * 0.5


def make_engine(folder, **kw):
    e = Engine(data_folder=folder, stream_factory=FakeStreams, converter_factory=FakeConverter,
               devices_provider=lambda: DEVICES, **kw)
    e._board_dirty = False  # keep pedalboard out of protocol tests
    return e


class Client:
    def __init__(self, engine):
        self.lines = []
        self.d = Dispatcher(engine, self.lines.append, base_folder=engine.data_folder)

    def call(self, method, **params):
        self.lines.clear()
        self.d.handle_line(json.dumps({"id": 7, "method": method, "params": params}), wait=True)
        replies = [json.loads(l) for l in self.lines if '"id"' in l]
        assert len(replies) == 1, self.lines
        return replies[0]

    def events(self, name):
        return [json.loads(l)["data"] for l in self.lines if json.loads(l).get("event") == name]


@pytest.fixture
def client(tmp_path):
    return Client(make_engine(tmp_path))


def add_voice(folder, name, index=None):
    models = folder / "models"
    models.mkdir(exist_ok=True)
    (models / f"{name}.pth").write_bytes(b"x")
    if index:
        (models / index).touch()


def test_hello_and_status(client):
    hello = client.call("hello")["result"]
    assert hello["engine"] == "0.1.0" and hello["base_models_ready"] is False
    status = client.call("status")["result"]
    assert status["phase"] == "off" and status["model"] is None
    assert status["out_vol"] == 1.0 and status["latency"] == "low" and status["latency_ms"] == 128


def test_first_run_picks_mic_and_cable(client):
    devs = client.call("devices")["result"]
    assert devs["input"] == "Microphone (HyperX SoloCast)"
    assert devs["output"] == "CABLE Input (VB-Audio Virtual Cable)"
    assert "Speakers (Realtek(R) Audio)" in devs["outputs"]


def test_start_stop_and_clamping(client):
    status = client.call("start")["result"]
    assert status["running"] is True and status["phase"] == "live"
    assert FakeStreams.last.args[2:4] == (0, 3)
    status = client.call("set", pitch=40, out_vol=-1, index_rate=0.5)["result"]
    assert (status["pitch"], status["out_vol"], status["index_rate"]) == (24.0, 0.0, 0.5)
    assert client.call("stop")["result"]["running"] is False


def test_missing_device_is_a_friendly_error(client):
    client.call("set_devices", input="USB Mic that got unplugged")
    err = client.call("start")["error"]
    assert "isn't connected" in err


def test_models_load_with_index_and_settings(client, tmp_path):
    add_voice(tmp_path, "AnimeYan", index="added_IVF256_Flat_nprobe_1_AnimeYan_v2.index")
    add_voice(tmp_path, "AM")
    models = client.call("list_models")["result"]
    assert [m["name"] for m in models] == ["AM", "AnimeYan"]
    assert [m["has_index"] for m in models] == [False, True]
    client.call("set", pitch=5, index_rate=0.3)
    status = client.call("load_model", model="AnimeYan")["result"]
    assert status["model"] == "AnimeYan" and status["load_ms"] is not None
    conv = client.d.engine.converter
    assert conv.path == tmp_path / "models" / "AnimeYan.pth"
    assert conv.index_path.name.endswith("AnimeYan_v2.index")
    assert conv.pitch == 5 and conv.index_rate == 0.3
    assert client.call("load_model", model="Nope")["error"]
    assert client.call("load_model")["result"]["model"] is None


def test_settings_survive_restart(tmp_path):
    add_voice(tmp_path, "AM")
    c = Client(make_engine(tmp_path))
    c.call("load_model", model="AM")
    c.call("set", pitch=-3)
    c.call("set_fx", reverb=True)
    c.call("set_devices", output="Speakers (Realtek(R) Audio)")
    c.call("set_latency", latency="safe")

    c2 = Client(make_engine(tmp_path))
    s = c2.call("status")["result"]
    assert (s["pitch"], s["latency"], s["fx"]["reverb"], s["saved_model"]) == (-3, "safe", True, "AM")
    assert s["devices"]["output"] == "Speakers (Realtek(R) Audio)"
    # Start loads the saved voice by itself.
    assert c2.call("start")["result"]["model"] == "AM"
    assert c2.d.engine.converter.block_size == LATENCY["safe"]


def test_latency_reloads_voice(client, tmp_path):
    add_voice(tmp_path, "AM")
    client.call("load_model", model="AM")
    client.call("start")
    status = client.call("set_latency", latency="balanced")["result"]
    assert status["running"] and status["latency_ms"] == 192
    assert client.d.engine.converter.block_size == LATENCY["balanced"]
    assert "error" in client.call("set_latency", latency="instant")


def test_modes_and_events(client):
    client.call("start")
    r = client.call("toggle_bypass")
    assert r["result"]["phase"] == "real"
    assert client.events("state")  # pushed so F8 from a game updates the UI
    assert client.call("toggle_mute")["result"]["phase"] == "muted"
    assert client.call("set_fx", reverb=True, radio_bits=6)["result"]["fx"]["reverb"] is True
    assert "error" in client.call("set_fx", wobble=True)


def test_process_block_volume_and_clip(tmp_path):
    e = make_engine(tmp_path, persist=False)
    block = np.full(256, 0.4, dtype=np.float32)
    assert np.allclose(e.process_block(block), 0.4)  # passthrough, out_vol 1.0, no boost
    e.set_params(out_vol=3.0)
    assert e.process_block(block).max() == pytest.approx(1.0)  # clipped, never past full scale
    e.muted = True
    assert not e.process_block(block).any()


def test_audio_loop_plays_converted_blocks(tmp_path):
    import time

    add_voice(tmp_path, "AM")
    e = make_engine(tmp_path, persist=False)
    e.load_model("AM")
    e.start()
    FakeStreams.last.on_input(np.full(128, 0.8, dtype=np.float32))
    for _ in range(100):
        if FakeStreams.last.played:
            break
        time.sleep(0.01)
    e.stop()
    out, monitor = FakeStreams.last.played[0]
    assert np.allclose(out, 0.4) and monitor is None


def test_import_model_rejects_junk(client, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("hi")
    assert "pth" in client.call("import_model", path=str(junk))["error"]


def test_find_index_prefers_exact(tmp_path):
    pth = tmp_path / "Voice.pth"
    pth.touch()
    (tmp_path / "added_Voice_v2.index").touch()
    assert find_index_for(pth).name == "added_Voice_v2.index"
    (tmp_path / "Voice.index").touch()
    assert find_index_for(pth).name == "Voice.index"


def test_bad_lines_dont_kill_the_engine(client):
    client.lines.clear()
    client.d.handle_line("not json")
    client.d.handle_line(json.dumps({"id": 1, "method": "explode"}))
    assert all("error" in json.loads(l) for l in client.lines)


def test_sidecar_process_round_trip(tmp_path):
    import os

    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    proc = subprocess.run(
        [sys.executable, "-m", "voiceapp_engine", "--data", str(tmp_path), "--no-hotkeys"],
        input=json.dumps({"id": 1, "method": "hello"}) + "\n",
        capture_output=True, text=True, timeout=60, env=env,
    )
    lines = [json.loads(l) for l in proc.stdout.splitlines()]
    assert lines[0] == {"event": "ready", "data": {}}
    assert lines[1]["id"] == 1 and lines[1]["result"]["engine"] == "0.1.0"
