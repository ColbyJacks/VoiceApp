"""Sound card access, ported from the tray app's DirectAudioEngine.

sounddevice is imported lazily so the engine starts fast and so the protocol
can be tested on machines without audio hardware.
"""

from __future__ import annotations

import queue
from typing import Any, Callable

import numpy as np


def _host_tag(sd, dev) -> str:
    host = sd.query_hostapis(dev["hostapi"])["name"]
    return "WASAPI" if "WASAPI" in host else ("DS" if "DirectSound" in host else "MME")


def list_devices() -> list[dict[str, Any]]:
    import sounddevice as sd

    devices = []
    for index, dev in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": index,
                "name": dev["name"],
                "host": _host_tag(sd, dev),
                "inputs": dev["max_input_channels"],
                "outputs": dev["max_output_channels"],
                "default_rate": dev["default_samplerate"],
            }
        )
    return devices


def default_devices(devices: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """The tray app's picks: first WASAPI mic, and a WASAPI virtual cable
    (for Discord etc.) if there is one, else the first WASAPI output."""
    wasapi = [d for d in devices if d["host"] == "WASAPI"]
    inputs = [d for d in wasapi if d["inputs"] > 0] or [d for d in devices if d["inputs"] > 0]
    outputs = [d for d in wasapi if d["outputs"] > 0] or [d for d in devices if d["outputs"] > 0]
    cables = [d for d in outputs if "cable" in d["name"].lower()]
    out = (cables or outputs or [None])[0]
    inp = (inputs or [None])[0]
    return (inp["index"] if inp else None, out["index"] if out else None)


class Streams:
    """Mic input, main output and an optional ear-monitor output.

    The input callback queues raw blocks; ``on_block`` (run by the engine's
    worker thread) turns them into output blocks; output callbacks drain their
    queues and play silence when nothing is ready.
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
        self.out_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=6)
        self.mon_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=6)
        self._streams: list[Any] = []

    def start(self) -> None:
        import sounddevice as sd

        all_devs = sd.query_devices()
        in_id, out_id, mon_id = self.devices
        in_id = sd.default.device[0] if in_id is None else in_id
        out_id = sd.default.device[1] if out_id is None else out_id

        def extra(dev):
            return sd.WasapiSettings(exclusive=False, auto_convert=True) if _host_tag(sd, dev) == "WASAPI" else None

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
            in_dev = all_devs[in_id]
            self._streams.append(
                sd.InputStream(device=in_id, samplerate=self.sample_rate, blocksize=self.block_size, channels=1,
                               dtype="float32", extra_settings=extra(in_dev), callback=in_cb)
            )
            for dev_id, q in ((out_id, self.out_queue), (mon_id, self.mon_queue)):
                if dev_id is None:
                    continue
                dev = all_devs[dev_id]
                channels = min(2, max(1, dev["max_output_channels"]))
                self._streams.append(
                    sd.OutputStream(device=dev_id, samplerate=self.sample_rate, blocksize=self.block_size,
                                    channels=channels, dtype="float32", extra_settings=extra(dev),
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
