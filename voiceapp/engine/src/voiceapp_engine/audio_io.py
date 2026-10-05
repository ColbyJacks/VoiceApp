"""Sound card access. sounddevice is imported lazily so the engine starts fast
and so the protocol can be tested on machines without audio hardware."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np


def list_devices() -> list[dict[str, Any]]:
    import sounddevice as sd

    devices = []
    for index, dev in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": index,
                "name": dev["name"],
                "inputs": dev["max_input_channels"],
                "outputs": dev["max_output_channels"],
                "default_rate": dev["default_samplerate"],
            }
        )
    return devices


class DuplexStream:
    """Mic in, converted audio out, one callback per block."""

    def __init__(
        self,
        process: Callable[[np.ndarray], np.ndarray],
        sample_rate: int,
        block_size: int,
        input_device: int | None = None,
        output_device: int | None = None,
    ) -> None:
        self._process = process
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._devices = (input_device, output_device)
        self._stream: Any = None

    def _callback(self, indata, outdata, frames, time, status) -> None:  # noqa: ARG002
        out = self._process(indata[:, 0].copy())
        outdata[:, 0] = out[:frames]
        if outdata.shape[1] > 1:
            outdata[:, 1:] = outdata[:, :1]

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.Stream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            device=self._devices,
            channels=(1, 2),
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
