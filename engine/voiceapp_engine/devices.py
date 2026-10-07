"""Audio device listing.

Devices are identified by "API::name" rather than PortAudio's index, because
indexes shift whenever a device is plugged in or out. WDM-KS and ASIO devices
are never offered: PortAudio lists them, but opening them the way this app
does fails ("Invalid device").
"""

from __future__ import annotations

import functools
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import sounddevice as sd


def _com_init() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED


# WASAPI streams only open from a thread with COM initialised, and PortAudio
# isn't safe to re-scan while another thread opens a stream, so every
# PortAudio call goes through this one thread.
_audio_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="portaudio", initializer=_com_init)
_audio_thread_ident: list[int] = []
_audio_thread.submit(lambda: _audio_thread_ident.append(threading.get_ident())).result()


def on_audio_thread(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if threading.get_ident() in _audio_thread_ident:
            return fn(*args, **kwargs)
        return _audio_thread.submit(fn, *args, **kwargs).result()

    return wrapper


API_NAMES = {
    "Windows WASAPI": "WASAPI",
    "MME": "MME",
    "Windows DirectSound": "DirectSound",
}


@on_audio_thread
def refresh() -> None:
    """Re-scan devices. Only call while no stream is open."""
    sd._terminate()
    sd._initialize()


def _key(api: str, name: str) -> str:
    return f"{api}::{name}"


@on_audio_thread
def list_devices(include_legacy: bool = False) -> dict[str, Any]:
    apis = sd.query_hostapis()
    inputs, outputs = [], []
    defaults: dict[str, str | None] = {"input": None, "output": None, "cable": None}

    for index, dev in enumerate(sd.query_devices()):
        api = API_NAMES.get(apis[dev["hostapi"]]["name"])
        if api is None or (api != "WASAPI" and not include_legacy):
            continue
        entry = {
            "id": _key(api, dev["name"]),
            "name": dev["name"],
            "api": api,
            "rate": int(dev["default_samplerate"]),
        }
        if dev["max_input_channels"] > 0:
            inputs.append({**entry, "channels": dev["max_input_channels"]})
        if dev["max_output_channels"] > 0:
            outputs.append({**entry, "channels": dev["max_output_channels"]})
            if api == "WASAPI" and "cable input" in dev["name"].lower() and not defaults["cable"]:
                defaults["cable"] = entry["id"]

    for api_info in apis:
        if api_info["name"] == "Windows WASAPI":
            all_devs = sd.query_devices()
            if api_info["default_input_device"] >= 0:
                defaults["input"] = _key("WASAPI", all_devs[api_info["default_input_device"]]["name"])
            if api_info["default_output_device"] >= 0:
                defaults["output"] = _key("WASAPI", all_devs[api_info["default_output_device"]]["name"])

    return {"inputs": inputs, "outputs": outputs, "defaults": defaults}


@on_audio_thread
def resolve(device_id: str | None, kind: str) -> tuple[int, dict[str, Any]]:
    """PortAudio index and info for an "API::name" id ("input" or "output")."""
    if not device_id:
        raise ValueError(f"No {kind} device selected.")
    api, _, name = device_id.partition("::")
    apis = sd.query_hostapis()
    channels = "max_input_channels" if kind == "input" else "max_output_channels"
    for index, dev in enumerate(sd.query_devices()):
        if (
            API_NAMES.get(apis[dev["hostapi"]]["name"]) == api
            and dev["name"] == name
            and dev[channels] > 0
        ):
            return index, dev
    raise ValueError(f"The {kind} device \"{name}\" ({api}) isn't connected.")


def extra_settings(api: str):
    if api == "WASAPI":
        # Shared mode with Windows doing any sample-rate conversion.
        return sd.WasapiSettings(exclusive=False, auto_convert=True)
    return None
