"""Sound card access.

Windows lists every device up to four times (MME, DirectSound, WASAPI and
WDM-KS). Only WASAPI is offered: it runs at 48 kHz, shares the device with
other apps, and opens reliably. The old tray app also offered WDM-KS devices
labelled as MME, and opening those crashed with PaErrorCode -9996.

sounddevice is imported lazily so the engine starts fast and so the protocol
can be tested on machines without audio hardware.
"""

from __future__ import annotations

import queue
from typing import Any, Callable

import numpy as np


def _host_name(sd, dev) -> str:
    return sd.query_hostapis(dev["hostapi"])["name"]


def _usable_host(name: str) -> bool:
    return "WASAPI" in name


def list_devices() -> list[dict[str, Any]]:
    """Input and output devices worth offering, deduplicated across host APIs."""
    import sounddevice as sd

    all_devs = list(enumerate(sd.query_devices()))
    has_wasapi = any(_usable_host(_host_name(sd, d)) for _, d in all_devs)
    devices = []
    for index, dev in all_devs:
        host = _host_name(sd, dev)
        # Off Windows (or with no WASAPI at all) fall back to whatever exists.
        if has_wasapi and not _usable_host(host):
            continue
        devices.append(
            {
                "index": index,
                "name": dev["name"],
                "host": host,
                "inputs": dev["max_input_channels"],
                "outputs": dev["max_output_channels"],
                "default_rate": dev["default_samplerate"],
            }
        )
    return devices


def _system_default_names() -> tuple[str | None, str | None]:
    import sounddevice as sd

    names = []
    for idx in sd.default.device:
        try:
            names.append(sd.query_devices(idx)["name"] if idx is not None and idx >= 0 else None)
        except Exception:
            names.append(None)
    return names[0], names[1]


def _match(devices: list[dict[str, Any]], name: str | None) -> dict[str, Any] | None:
    """Find the device whose name matches `name`. MME truncates names to 31
    characters, so a prefix match is accepted."""
    if not name:
        return None
    for d in devices:
        if d["name"] == name:
            return d
    for d in devices:
        if d["name"].startswith(name) or name.startswith(d["name"]):
            return d
    return None


def default_devices(devices: list[dict[str, Any]], default_names: tuple[str | None, str | None] | None = None) -> tuple[int | None, int | None]:
    """Sensible first-run picks: the Windows default mic, and a virtual cable
    (so Discord and games hear the voice) if there is one, else the Windows
    default output."""
    if default_names is None:
        try:
            default_names = _system_default_names()
        except Exception:
            default_names = (None, None)
    inputs = [d for d in devices if d["inputs"] > 0]
    outputs = [d for d in devices if d["outputs"] > 0]
    # A cable's *output* end is an input device; never pick it as the mic.
    mics = [d for d in inputs if "cable" not in d["name"].lower()] or inputs
    mic = _match(mics, default_names[0]) or (mics[0] if mics else None)
    cables = [d for d in outputs if d["name"].lower().startswith("cable input")]
    out = (cables[0] if cables else None) or _match(outputs, default_names[1]) or (outputs[0] if outputs else None)
    return (mic["index"] if mic else None, out["index"] if out else None)


def find_by_name(devices: list[dict[str, Any]], name: str | None, kind: str) -> int | None:
    """Device index for a saved device name, or None if it's gone."""
    pool = [d for d in devices if d["inputs" if kind == "input" else "outputs"] > 0]
    found = _match(pool, name)
    return found["index"] if found else None


class Streams:
    """Mic input, main output and an optional ear-monitor output.

    The input callback hands raw blocks to ``on_input``; the engine's worker
    thread turns them into output blocks and calls ``play``; output callbacks
    drain their queues and play silence when nothing is ready.
    """

    def __init__(
        self,
        sample_rate: int,
        block_size: int,
        input_device: int | None,
        output_device: int | None,
        monitor_device: int | None = None,
        on_input: Callable[[np.ndarray], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.devices = (input_device, output_device, monitor_device)
        self.on_input = on_input
        self.out_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=4)
        self.mon_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=4)
        self._streams: list[Any] = []

    def start(self) -> None:
        import sounddevice as sd

        in_id, out_id, mon_id = self.devices
        in_id = sd.default.device[0] if in_id is None else in_id
        out_id = sd.default.device[1] if out_id is None else out_id

        def extra(dev_id):
            dev = sd.query_devices(dev_id)
            if "WASAPI" in _host_name(sd, dev):
                return sd.WasapiSettings(exclusive=False, auto_convert=True)
            return None

        def in_cb(indata, frames, time_info, status):  # noqa: ARG001
            if self.on_input is not None:
                self.on_input(indata[:, 0].copy())

        def make_out_cb(q: queue.Queue, channels: int):
            def out_cb(outdata, frames, time_info, status):  # noqa: ARG001
                try:
                    chunk = q.get_nowait()
                except queue.Empty:
                    outdata.fill(0)
                    return
                if len(chunk) != frames:
                    outdata.fill(0)
                elif channels == 1:
                    outdata[:, 0] = chunk
                else:
                    outdata[:] = np.repeat(chunk[:, np.newaxis], channels, axis=1)

            return out_cb

        try:
            self._streams.append(
                sd.InputStream(device=in_id, samplerate=self.sample_rate, blocksize=self.block_size, channels=1,
                               dtype="float32", extra_settings=extra(in_id), callback=in_cb)
            )
            for dev_id, q in ((out_id, self.out_queue), (mon_id, self.mon_queue)):
                if dev_id is None:
                    continue
                # VB-Cable's WASAPI end is mono, most speakers are stereo or more.
                channels = min(2, max(1, sd.query_devices(dev_id)["max_output_channels"]))
                self._streams.append(
                    sd.OutputStream(device=dev_id, samplerate=self.sample_rate, blocksize=self.block_size,
                                    channels=channels, dtype="float32", extra_settings=extra(dev_id),
                                    callback=make_out_cb(q, channels))
                )
            for stream in self._streams:
                stream.start()
        except Exception:
            self.stop()
            raise

    def play(self, block: np.ndarray, monitor_block: np.ndarray | None = None) -> None:
        for q, b in ((self.out_queue, block), (self.mon_queue, monitor_block)):
            if b is None:
                continue
            try:
                q.put_nowait(b)
            except queue.Full:
                pass

    def stop(self) -> None:
        for stream in self._streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._streams = []
