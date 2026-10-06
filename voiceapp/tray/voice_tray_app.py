import os
import sys
import json
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import numpy as np
import sounddevice as sd
from PIL import Image, ImageDraw
import pystray
import pedalboard

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

# Ensure workspace root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rvc.realtime.core import VoiceChanger

# ================= CONFIGURATION =================
MODELS_DIR = (BASE_DIR / "models").resolve()
MODELS_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_RATE = 48000
CHUNK_SIZE_FACTOR = 96  # 96 * 128 = 12,288 samples (~256ms)
# =================================================


class DirectAudioEngine:
    """High-performance direct GPU voice conversion engine with zero-IPC overhead."""

    def __init__(self):
        self.vc = None
        self.is_running = False
        self.in_gain = 1.0
        self.out_vol = 1.5           # Default 1.5x volume booster
        self.pitch_shift = 0
        self.index_rate = 0.75
        self.volume_envelope = 1.0
        self.current_model_name = "None"

        # Devices
        self.input_dev_idx = None
        self.output_dev_idx = None

        # Ear Monitor (Hear Myself)
        self.use_monitor = False
        self.monitor_dev_idx = None
        self.monitor_vol = 1.0

        # State
        self.is_bypassed = False     # False = Modulated AI Voice, True = Real Voice
        self.is_muted = False

        # Live VU Meter levels (0.0 to 1.0)
        self.in_level = 0.0
        self.out_level = 0.0

        # Streams and Threads
        self.in_stream = None
        self.out_stream = None
        self.mon_stream = None
        self.in_queue = queue.Queue(maxsize=6)
        self.out_queue = queue.Queue(maxsize=6)
        self.mon_queue = queue.Queue(maxsize=6)
        self.stop_event = threading.Event()
        self.worker_thread = None

        # FX Pedalboard
        self.fx_reverb_on = False
        self.fx_reverb_room = 0.5
        self.fx_reverb_wet = 0.3

        self.fx_delay_on = False
        self.fx_delay_time = 0.35
        self.fx_delay_feedback = 0.3

        self.fx_chorus_on = False
        self.fx_chorus_depth = 0.3
        self.fx_chorus_rate = 1.2

        self.fx_radio_on = False
        self.fx_radio_depth = 8

        self._lock = threading.Lock()

    def set_model(self, model_name: str):
        self.current_model_name = model_name
        print(f"[AudioEngine] Selected model: {model_name}")

    def update_gain(self, gain: float):
        self.in_gain = float(gain)

    def update_vol(self, vol: float):
        self.out_vol = float(vol)

    def update_pitch(self, pitch: int):
        self.pitch_shift = int(pitch)

    def update_index_rate(self, rate: float):
        self.index_rate = float(rate)

    def update_volume_envelope(self, env: float):
        self.volume_envelope = float(env)

    def update_monitor_vol(self, vol: float):
        self.monitor_vol = float(vol)

    def toggle_bypass(self):
        self.is_bypassed = not self.is_bypassed
        print(f"[AudioEngine] Mode: {'REAL VOICE (Bypass)' if self.is_bypassed else 'MODULATED AI VOICE'}")
        return self.is_bypassed

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        print(f"[AudioEngine] Muted: {self.is_muted}")
        return self.is_muted

    def build_pedalboard(self):
        plugins = []
        if self.fx_reverb_on:
            plugins.append(pedalboard.Reverb(
                room_size=self.fx_reverb_room,
                wet_level=self.fx_reverb_wet,
                dry_level=1.0 - self.fx_reverb_wet * 0.5
            ))
        if self.fx_delay_on:
            plugins.append(pedalboard.Delay(
                delay_seconds=self.fx_delay_time,
                feedback=self.fx_delay_feedback,
                mix=0.35
            ))
        if self.fx_chorus_on:
            plugins.append(pedalboard.Chorus(
                rate_hz=self.fx_chorus_rate,
                depth=self.fx_chorus_depth,
                mix=0.4
            ))
        if self.fx_radio_on:
            plugins.append(pedalboard.Bitcrush(bit_depth=self.fx_radio_depth))
            plugins.append(pedalboard.HighpassFilter(cutoff_frequency_hz=300))
            plugins.append(pedalboard.LowpassFilter(cutoff_frequency_hz=3400))

        # Always add transparent soft limiter
        plugins.append(pedalboard.Limiter(threshold_db=-0.5, release_ms=50))
        return pedalboard.Pedalboard(plugins)

    def start_stream(self, status_callback=None):
        with self._lock:
            self.stop_stream()
            try:
                is_passthrough = (
                    self.is_bypassed
                    or not self.current_model_name
                    or self.current_model_name in ["None", "None (Pass-through)"]
                )

                model_path = None
                index_path = None

                if not is_passthrough:
                    candidate_pth = MODELS_DIR / self.current_model_name
                    if not candidate_pth.exists():
                        candidate_pth = MODELS_DIR / f"{self.current_model_name}.pth"
                    if candidate_pth.exists():
                        model_path = str(candidate_pth)
                        candidate_idx = MODELS_DIR / f"{candidate_pth.stem}.index"
                        if candidate_idx.exists():
                            index_path = str(candidate_idx)
                        else:
                            indexes = list(MODELS_DIR.glob("*.index"))
                            if indexes:
                                index_path = str(indexes[0])
                    else:
                        print(f"[AudioEngine Warning] Model file not found: {candidate_pth}")
                        is_passthrough = True

                if status_callback:
                    status_callback("Loading voice model on GPU...")

                # Initialize direct VoiceChanger if not passthrough
                if not is_passthrough and model_path:
                    self.vc = VoiceChanger(
                        read_chunk_size=CHUNK_SIZE_FACTOR,
                        cross_fade_overlap_size=0.1,
                        extra_convert_size=0.5,
                        model_path=model_path,
                        index_path=index_path,
                        f0_method="rmvpe",
                        silent_threshold=-60
                    )
                else:
                    self.vc = None

                if status_callback:
                    status_callback("Configuring audio devices...")

                block_samples = CHUNK_SIZE_FACTOR * 128  # 12,288 samples
                all_devs = sd.query_devices()

                in_dev_id = self.input_dev_idx if self.input_dev_idx is not None else sd.default.device[0]
                out_dev_id = self.output_dev_idx if self.output_dev_idx is not None else sd.default.device[1]

                in_info = all_devs[in_dev_id] if in_dev_id < len(all_devs) else all_devs[0]
                out_info = all_devs[out_dev_id] if out_dev_id < len(all_devs) else all_devs[1]

                in_ch = min(1, max(1, in_info.get("max_input_channels", 1)))
                out_ch = min(2, max(1, out_info.get("max_output_channels", 1)))

                in_host = sd.query_hostapis(in_info["hostapi"])["name"]
                out_host = sd.query_hostapis(out_info["hostapi"])["name"]

                in_extra = sd.WasapiSettings(exclusive=False, auto_convert=True) if "WASAPI" in in_host else None
                out_extra = sd.WasapiSettings(exclusive=False, auto_convert=True) if "WASAPI" in out_host else None

                print(f"[AudioEngine] In: [{in_dev_id}] {in_info['name']} (Ch:{in_ch}) -> Out: [{out_dev_id}] {out_info['name']} (Ch:{out_ch})")

                # Reset Queues and Worker
                self.stop_event.clear()
                while not self.in_queue.empty():
                    self.in_queue.get_nowait()
                while not self.out_queue.empty():
                    self.out_queue.get_nowait()
                while not self.mon_queue.empty():
                    self.mon_queue.get_nowait()

                board = self.build_pedalboard()

                def _convert_worker():
                    while not self.stop_event.is_set():
                        try:
                            audio_chunk = self.in_queue.get(timeout=0.05)
                        except queue.Empty:
                            continue

                        if self.is_muted:
                            zero_block = np.zeros(len(audio_chunk), dtype=np.float32)
                            try:
                                self.out_queue.put_nowait(zero_block)
                            except queue.Full:
                                pass
                            continue

                        # If bypassed or no model, pass raw mic audio directly
                        if self.is_bypassed or self.vc is None:
                            out_audio = audio_chunk.copy()
                        else:
                            try:
                                out_audio, _ = self.vc.process_audio(
                                    audio_chunk,
                                    f0_up_key=self.pitch_shift,
                                    index_rate=self.index_rate,
                                    volume_envelope=self.volume_envelope
                                )
                            except Exception as ex:
                                print(f"[Conversion Worker Error] {ex}")
                                out_audio = audio_chunk.copy()

                        # Apply Audio FX & Soft Limiter
                        if len(board) > 0 and len(out_audio) > 0:
                            try:
                                out_audio = board(out_audio.astype(np.float32), SAMPLE_RATE)
                            except Exception:
                                pass

                        # Apply Output Volume Booster
                        out_audio = out_audio * self.out_vol
                        rms_out = float(np.sqrt(np.mean(out_audio**2)))
                        self.out_level = min(1.0, rms_out * 3.5)

                        # Send to main output
                        try:
                            self.out_queue.put_nowait(out_audio)
                        except queue.Full:
                            pass

                        # Send to ear monitor if enabled
                        if self.use_monitor:
                            try:
                                self.mon_queue.put_nowait(out_audio * self.monitor_vol)
                            except queue.Full:
                                pass

                self.worker_thread = threading.Thread(target=_convert_worker, daemon=True)
                self.worker_thread.start()

                # Sounddevice Stream Callbacks
                def _in_cb(indata, frames, time_info, status):
                    raw_mono = indata[:, 0].copy() * self.in_gain
                    rms_in = float(np.sqrt(np.mean(raw_mono**2)))
                    self.in_level = min(1.0, rms_in * 4.0)

                    try:
                        self.in_queue.put_nowait(raw_mono)
                    except queue.Full:
                        pass

                def _out_cb(outdata, frames, time_info, status):
                    try:
                        chunk = self.out_queue.get_nowait()
                        if len(chunk) == frames:
                            if out_ch == 1:
                                outdata[:, 0] = chunk
                            else:
                                outdata[:] = np.repeat(chunk[:, np.newaxis], out_ch, axis=1)
                        else:
                            outdata.fill(0)
                    except queue.Empty:
                        outdata.fill(0)

                self.in_stream = sd.InputStream(
                    device=in_dev_id,
                    samplerate=SAMPLE_RATE,
                    blocksize=block_samples,
                    channels=in_ch,
                    dtype="float32",
                    extra_settings=in_extra,
                    callback=_in_cb
                )

                self.out_stream = sd.OutputStream(
                    device=out_dev_id,
                    samplerate=SAMPLE_RATE,
                    blocksize=block_samples,
                    channels=out_ch,
                    dtype="float32",
                    extra_settings=out_extra,
                    callback=_out_cb
                )

                self.in_stream.start()
                self.out_stream.start()

                # Ear Monitor Stream (Headphones)
                if self.use_monitor and self.monitor_dev_idx is not None:
                    mon_info = all_devs[self.monitor_dev_idx]
                    mon_ch = min(2, max(1, mon_info.get("max_output_channels", 1)))
                    mon_host = sd.query_hostapis(mon_info["hostapi"])["name"]
                    mon_extra = sd.WasapiSettings(exclusive=False, auto_convert=True) if "WASAPI" in mon_host else None

                    def _mon_cb(outdata, frames, time_info, status):
                        try:
                            chunk = self.mon_queue.get_nowait()
                            if len(chunk) == frames:
                                if mon_ch == 1:
                                    outdata[:, 0] = chunk
                                else:
                                    outdata[:] = np.repeat(chunk[:, np.newaxis], mon_ch, axis=1)
                            else:
                                outdata.fill(0)
                        except queue.Empty:
                            outdata.fill(0)

                    self.mon_stream = sd.OutputStream(
                        device=self.monitor_dev_idx,
                        samplerate=SAMPLE_RATE,
                        blocksize=block_samples,
                        channels=mon_ch,
                        dtype="float32",
                        extra_settings=mon_extra,
                        callback=_mon_cb
                    )
                    self.mon_stream.start()

                self.is_running = True
                print(f"[AudioEngine] Stream active! (Pass-through: {is_passthrough})")
                if status_callback:
                    status_callback("Active (Modulating)" if not is_passthrough else "Active (Real Voice)")
                return True

            except Exception as e:
                print(f"[AudioEngine Error] {e}")
                import traceback
                traceback.print_exc()
                self.stop_stream()
                if status_callback:
                    status_callback(f"Error: {str(e)[:30]}")
                raise e

    def stop_stream(self):
        try:
            self.stop_event.set()
            if self.in_stream:
                self.in_stream.stop()
                self.in_stream.close()
                self.in_stream = None
            if self.out_stream:
                self.out_stream.stop()
                self.out_stream.close()
                self.out_stream = None
            if self.mon_stream:
                self.mon_stream.stop()
                self.mon_stream.close()
                self.mon_stream = None
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=1.0)
                self.worker_thread = None
            self.vc = None
        except Exception as e:
            print(f"[AudioEngine Stop Error] {e}")
        finally:
            self.is_running = False
            self.in_level = 0.0
            self.out_level = 0.0
            print("[AudioEngine] Stream stopped.")


class VoiceTrayApp:
    def __init__(self, root):
        self.root = root
        self.audio = DirectAudioEngine()

        # Full Size Studio Mode (920x680)
        self.root.title("Mic Modulator Studio Pro (RVC)")
        self.root.geometry("920x680")
        self.root.minsize(820, 600)
        self.root.configure(bg="#18191c")

        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self._query_devices()
        self._init_styles()
        self._build_ui()
        self._init_tray()
        self._setup_global_hotkeys()
        self._start_vu_meter_loop()

    def _query_devices(self):
        self.input_devices = {}
        self.output_devices = {}
        try:
            for idx, dev in enumerate(sd.query_devices()):
                host_name = sd.query_hostapis(dev["hostapi"])["name"]
                tag = "WASAPI" if "WASAPI" in host_name else ("DS" if "DirectSound" in host_name else "MME")
                name = f"[{tag}] {dev['name'][:34]} (ID: {idx})"

                if dev["max_input_channels"] > 0:
                    self.input_devices[name] = idx
                if dev["max_output_channels"] > 0:
                    self.output_devices[name] = idx
        except Exception as e:
            print(f"[Devices Error] {e}")

    def _init_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        bg_main = "#18191c"
        bg_card = "#232428"
        bg_entry = "#2f3136"
        fg_text = "#e0e0e0"
        accent = "#7289da"

        style.configure("TFrame", background=bg_main)
        style.configure("Card.TFrame", background=bg_card, relief="flat")
        style.configure("TLabel", background=bg_main, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=bg_card, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=bg_card, foreground="#ffffff", font=("Segoe UI", 11, "bold"))
        style.configure("Header.TLabel", background=bg_card, foreground=accent, font=("Segoe UI", 9, "bold"))
        style.configure("TCombobox", fieldbackground=bg_entry, foreground="#ffffff", background=bg_card)

    def _build_ui(self):
        fg_col = "#e0e0e0"
        bg_card = "#232428"
        bg_col = "#18191c"
        accent = "#7289da"

        # Top Bar (Mode Banner + Tray Minimize Button)
        top_bar = tk.Frame(self.root, bg="#2f3136", padx=14, pady=8)
        top_bar.pack(fill=tk.X)

        self.mode_badge = tk.Label(
            top_bar, text="🟢 MODULATED AI VOICE ACTIVE", font=("Segoe UI", 10, "bold"),
            fg="#43b581", bg="#2f3136"
        )
        self.mode_badge.pack(side=tk.LEFT)

        btn_tray = tk.Button(
            top_bar, text="🔻 MINIMIZE TO TRAY", font=("Segoe UI", 8, "bold"), bg="#4f545c", fg="white",
            relief="flat", cursor="hand2", command=self.hide_to_tray, padx=8, pady=3
        )
        btn_tray.pack(side=tk.RIGHT, padx=(6, 0))

        lbl_hint = tk.Label(
            top_bar, text="[Hotkey: F8 = Voice Toggle | F7 = Mute]", font=("Segoe UI", 8),
            fg="#99aab5", bg="#2f3136"
        )
        lbl_hint.pack(side=tk.RIGHT, padx=10)

        # Dual Column Layout
        content_frame = tk.Frame(self.root, bg=bg_col, padx=12, pady=10)
        content_frame.pack(fill=tk.BOTH, expand=True)

        left_col = tk.Frame(content_frame, bg=bg_col)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        right_col = tk.Frame(content_frame, bg=bg_col)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

        # ================= LEFT COLUMN =================
        # 1. Voice Model Selector
        m_card = ttk.Frame(left_col, style="Card.TFrame", padding=12)
        m_card.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(m_card, text="1. VOICE MODEL SELECTOR", style="Header.TLabel").pack(anchor="w", pady=(0, 4))
        model_files = [f.name for f in MODELS_DIR.glob("*.pth")]
        models = model_files + ["None (Pass-through)"] if model_files else ["None (Pass-through)"]
        self.model_var = tk.StringVar(value=models[0])
        self.model_cb = ttk.Combobox(m_card, textvariable=self.model_var, values=models, state="readonly", font=("Segoe UI", 9))
        self.model_cb.pack(fill=tk.X, pady=(0, 4))
        self.model_cb.bind("<<ComboboxSelected>>", self._on_model_selected)

        btn_refresh_models = tk.Button(
            m_card, text="🔄 Refresh Models Folder", bg="#2f3136", fg="#99aab5", font=("Segoe UI", 8),
            relief="flat", cursor="hand2", command=self._refresh_models_list
        )
        btn_refresh_models.pack(anchor="e")

        # 2. Audio Device Routing
        dev_card = ttk.Frame(left_col, style="Card.TFrame", padding=12)
        dev_card.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(dev_card, text="2. AUDIO DEVICE ROUTING", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        # Input Mic (Pre-select WASAPI microphone)
        ttk.Label(dev_card, text="Microphone Input (Mic):", style="Card.TLabel").pack(anchor="w")
        wasapi_inputs = [k for k in self.input_devices.keys() if "[WASAPI]" in k]
        default_in = wasapi_inputs[0] if wasapi_inputs else (list(self.input_devices.keys())[0] if self.input_devices else "Default")
        self.in_dev_var = tk.StringVar(value=default_in)
        self.in_cb = ttk.Combobox(dev_card, textvariable=self.in_dev_var, values=list(self.input_devices.keys()), state="readonly", font=("Segoe UI", 8))
        self.in_cb.pack(fill=tk.X, pady=(2, 6))

        # Output Cable (Pre-select CABLE Input)
        ttk.Label(dev_card, text="Audio Output (Cable Input / Discord):", style="Card.TLabel").pack(anchor="w")
        wasapi_cables = [k for k in self.output_devices.keys() if "[WASAPI]" in k and "cable" in k.lower()]
        wasapi_outputs = [k for k in self.output_devices.keys() if "[WASAPI]" in k]
        default_out = wasapi_cables[0] if wasapi_cables else (wasapi_outputs[0] if wasapi_outputs else (list(self.output_devices.keys())[0] if self.output_devices else "Default"))
        self.out_dev_var = tk.StringVar(value=default_out)
        self.out_cb = ttk.Combobox(dev_card, textvariable=self.out_dev_var, values=list(self.output_devices.keys()), state="readonly", font=("Segoe UI", 8))
        self.out_cb.pack(fill=tk.X, pady=(2, 6))

        # Ear Monitor
        mon_row = tk.Frame(dev_card, bg=bg_card)
        mon_row.pack(fill=tk.X, pady=(4, 0))

        self.mon_chk_var = tk.BooleanVar(value=False)
        self.mon_chk = tk.Checkbutton(
            mon_row, text="🎧 Hear Myself (Ear Monitor)", variable=self.mon_chk_var, font=("Segoe UI", 9, "bold"),
            fg=fg_col, bg=bg_card, selectcolor="#2f3136", activebackground=bg_card, activeforeground="#ffffff",
            command=self._on_toggle_monitor
        )
        self.mon_chk.pack(side=tk.LEFT)

        self.mon_dev_var = tk.StringVar(value=list(self.output_devices.keys())[0] if self.output_devices else "Default")
        self.mon_cb = ttk.Combobox(dev_card, textvariable=self.mon_dev_var, values=list(self.output_devices.keys()), state="readonly", font=("Segoe UI", 8))
        self.mon_cb.pack(fill=tk.X, pady=(2, 2))

        # 3. Voice Sliders
        sliders_card = ttk.Frame(left_col, style="Card.TFrame", padding=12)
        sliders_card.pack(fill=tk.BOTH, expand=True)

        ttk.Label(sliders_card, text="3. GAIN & VOICE TUNING", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        # Pitch Shift
        ttk.Label(sliders_card, text="Pitch Shift:", style="Card.TLabel").grid(row=1, column=0, sticky="w")
        self.pitch_slider = tk.Scale(
            sliders_card, from_=-24, to=24, resolution=1, orient=tk.HORIZONTAL,
            showvalue=True, bg=bg_card, fg=fg_col, highlightthickness=0, command=self._update_pitch
        )
        self.pitch_slider.set(0)
        self.pitch_slider.grid(row=1, column=1, sticky="ew", padx=6)

        # Output Volume Booster
        ttk.Label(sliders_card, text="Volume Booster:", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        self.vol_slider = tk.Scale(
            sliders_card, from_=0.0, to=4.0, resolution=0.1, orient=tk.HORIZONTAL,
            showvalue=True, bg=bg_card, fg=fg_col, highlightthickness=0, command=self._update_vol
        )
        self.vol_slider.set(1.5)
        self.vol_slider.grid(row=2, column=1, sticky="ew", padx=6)

        # Mic Gain Pre-Amp
        ttk.Label(sliders_card, text="Mic Gain Pre-Amp:", style="Card.TLabel").grid(row=3, column=0, sticky="w")
        self.gain_slider = tk.Scale(
            sliders_card, from_=0.0, to=3.0, resolution=0.1, orient=tk.HORIZONTAL,
            showvalue=True, bg=bg_card, fg=fg_col, highlightthickness=0, command=self._update_gain
        )
        self.gain_slider.set(1.0)
        self.gain_slider.grid(row=3, column=1, sticky="ew", padx=6)

        # Volume Dynamics Envelope
        ttk.Label(sliders_card, text="Dynamic Envelope:", style="Card.TLabel").grid(row=4, column=0, sticky="w")
        self.env_slider = tk.Scale(
            sliders_card, from_=0.0, to=1.0, resolution=0.05, orient=tk.HORIZONTAL,
            showvalue=True, bg=bg_card, fg=fg_col, highlightthickness=0, command=self._update_envelope
        )
        self.env_slider.set(1.0)
        self.env_slider.grid(row=4, column=1, sticky="ew", padx=6)

        sliders_card.columnconfigure(1, weight=1)

        # ================= RIGHT COLUMN =================
        # 4. Live VU Meters Card
        vu_card = ttk.Frame(right_col, style="Card.TFrame", padding=12)
        vu_card.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(vu_card, text="LIVE AUDIO VISUALIZER", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        tk.Label(vu_card, text="MICROPHONE INPUT LEVEL (MIC IN):", font=("Segoe UI", 8, "bold"), fg="#99aab5", bg=bg_card).pack(anchor="w")
        self.canvas_in = tk.Canvas(vu_card, height=18, bg="#18191c", highlightthickness=0)
        self.canvas_in.pack(fill=tk.X, pady=(2, 8))

        tk.Label(vu_card, text="MODULATED VOICE OUTPUT (VOICE OUT):", font=("Segoe UI", 8, "bold"), fg="#99aab5", bg=bg_card).pack(anchor="w")
        self.canvas_out = tk.Canvas(vu_card, height=18, bg="#18191c", highlightthickness=0)
        self.canvas_out.pack(fill=tk.X, pady=(2, 4))

        # 5. Real-Time Audio FX Studio
        fx_card = ttk.Frame(right_col, style="Card.TFrame", padding=12)
        fx_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        ttk.Label(fx_card, text="REAL-TIME FX RACK (PEDALBOARD)", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        # Reverb
        self.reverb_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fx_card, text="🌌 Reverb (Ambiance & Space)", variable=self.reverb_var, font=("Segoe UI", 9, "bold"),
            fg=fg_col, bg=bg_card, selectcolor="#2f3136", activebackground=bg_card, activeforeground="#ffffff",
            command=self._on_fx_toggle
        ).pack(anchor="w", pady=2)

        # Echo / Delay
        self.delay_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fx_card, text="⏱️ Echo / Delay", variable=self.delay_var, font=("Segoe UI", 9, "bold"),
            fg=fg_col, bg=bg_card, selectcolor="#2f3136", activebackground=bg_card, activeforeground="#ffffff",
            command=self._on_fx_toggle
        ).pack(anchor="w", pady=2)

        # Cyberpunk / Chorus
        self.chorus_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fx_card, text="🤖 Cyberpunk Robot / Chorus", variable=self.chorus_var, font=("Segoe UI", 9, "bold"),
            fg=fg_col, bg=bg_card, selectcolor="#2f3136", activebackground=bg_card, activeforeground="#ffffff",
            command=self._on_fx_toggle
        ).pack(anchor="w", pady=2)

        # Walkie Talkie / Radio
        self.radio_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fx_card, text="📻 Walkie-Talkie / Radio Filter", variable=self.radio_var, font=("Segoe UI", 9, "bold"),
            fg=fg_col, bg=bg_card, selectcolor="#2f3136", activebackground=bg_card, activeforeground="#ffffff",
            command=self._on_fx_toggle
        ).pack(anchor="w", pady=2)

        # Bottom Control Deck
        deck_frame = tk.Frame(self.root, bg=bg_card, padx=14, pady=10)
        deck_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_lbl = tk.Label(deck_frame, text="Status: Ready", font=("Segoe UI", 9), fg="#99aab5", bg=bg_card)
        self.status_lbl.pack(side=tk.LEFT)

        self.btn_bypass = tk.Button(
            deck_frame, text="🔄 BYPASS VOICE (F8)", font=("Segoe UI", 9, "bold"), bg="#5865f2", fg="white",
            relief="flat", cursor="hand2", command=self._on_press_bypass, padx=12, pady=6
        )
        self.btn_bypass.pack(side=tk.LEFT, padx=(20, 6))

        self.btn_mute = tk.Button(
            deck_frame, text="🎙️ MUTE MIC (F7)", font=("Segoe UI", 9, "bold"), bg="#4f545c", fg="white",
            relief="flat", cursor="hand2", command=self._on_press_mute, padx=12, pady=6
        )
        self.btn_mute.pack(side=tk.LEFT, padx=6)

        self.toggle_btn = tk.Button(
            deck_frame, text="START ENGINE", font=("Segoe UI", 10, "bold"), bg="#43b581", fg="white",
            relief="flat", cursor="hand2", command=self._toggle_stream, padx=20, pady=6
        )
        self.toggle_btn.pack(side=tk.RIGHT)

    def _refresh_models_list(self):
        model_files = [f.name for f in MODELS_DIR.glob("*.pth")]
        models = model_files + ["None (Pass-through)"] if model_files else ["None (Pass-through)"]
        self.model_cb.config(values=models)
        if models:
            self.model_var.set(models[0])

    def _setup_global_hotkeys(self):
        if not KEYBOARD_AVAILABLE:
            return
        try:
            keyboard.add_hotkey("F8", self._on_press_bypass)
            keyboard.add_hotkey("F7", self._on_press_mute)
            print("[Hotkeys] Global hotkeys registered: F8 (Toggle Voice), F7 (Mute)")
        except Exception as e:
            print(f"[Hotkeys Error] {e}")

    def _on_press_bypass(self):
        self.audio.toggle_bypass()
        self._update_badge()

    def _on_press_mute(self):
        self.audio.toggle_mute()
        self._update_badge()

    def _update_badge(self):
        def _ui():
            if self.audio.is_muted:
                self.mode_badge.config(text="🔴 MICROPHONE MUTED", fg="#f04747")
                self.btn_mute.config(bg="#f04747", text="🔇 MUTED (F7)")
            elif self.audio.is_bypassed:
                self.mode_badge.config(text="🔵 REAL VOICE (BYPASS)", fg="#7289da")
                self.btn_mute.config(bg="#4f545c", text="🎙️ MUTE MIC (F7)")
            else:
                self.mode_badge.config(text="🟢 MODULATED AI VOICE ACTIVE", fg="#43b581")
                self.btn_mute.config(bg="#4f545c", text="🎙️ MUTE MIC (F7)")
        self.root.after(0, _ui)

    def _on_fx_toggle(self):
        self.audio.fx_reverb_on = self.reverb_var.get()
        self.audio.fx_delay_on = self.delay_var.get()
        self.audio.fx_chorus_on = self.chorus_var.get()
        self.audio.fx_radio_on = self.radio_var.get()

    def _on_toggle_monitor(self):
        self.audio.use_monitor = self.mon_chk_var.get()
        if self.audio.is_running:
            threading.Thread(target=self._restart_stream, daemon=True).start()

    def _on_model_selected(self, event=None):
        model = self.model_var.get()
        self.audio.set_model(model)
        if self.audio.is_running:
            threading.Thread(target=self._restart_stream, daemon=True).start()

    def _update_pitch(self, val):
        self.audio.update_pitch(int(float(val)))

    def _update_gain(self, val):
        self.audio.update_gain(float(val))

    def _update_vol(self, val):
        self.audio.update_vol(float(val))

    def _update_envelope(self, val):
        self.audio.update_volume_envelope(float(val))

    def _restart_stream(self):
        self._set_status("Updating audio stream...")
        self.audio.start_stream(status_callback=self._set_status)

    def _set_status(self, text):
        def _update():
            self.status_lbl.config(text=f"Status: {text}")
            if "Active" in text:
                self.toggle_btn.config(text="STOP ENGINE", bg="#f04747", state="normal")
            elif "Ready" in text or "Stopped" in text:
                self.toggle_btn.config(text="START ENGINE", bg="#43b581", state="normal")
            elif "Error" in text:
                self.toggle_btn.config(text="START ENGINE", bg="#f04747", state="normal")
        self.root.after(0, _update)

    def _toggle_stream(self):
        if not self.audio.is_running:
            self.audio.input_dev_idx = self.input_devices.get(self.in_dev_var.get())
            self.audio.output_dev_idx = self.output_devices.get(self.out_dev_var.get())
            self.audio.monitor_dev_idx = self.output_devices.get(self.mon_dev_var.get())
            self.audio.use_monitor = self.mon_chk_var.get()
            self.audio.set_model(self.model_var.get())
            self.toggle_btn.config(text="INITIALIZING...", bg="#faa61a", state="disabled")

            def _worker():
                try:
                    self.audio.start_stream(status_callback=self._set_status)
                except Exception as e:
                    self._set_status(f"Error: {str(e)[:25]}")

            threading.Thread(target=_worker, daemon=True).start()
        else:
            self.toggle_btn.config(text="STOPPING...", bg="#faa61a", state="disabled")
            def _stop_worker():
                self.audio.stop_stream()
                self._set_status("Ready")
            threading.Thread(target=_stop_worker, daemon=True).start()

    def _start_vu_meter_loop(self):
        def _loop():
            # Update Mic IN canvas
            w_in = self.canvas_in.winfo_width()
            if w_in > 1:
                self.canvas_in.delete("all")
                fill_w = int(w_in * self.audio.in_level)
                color = "#43b581" if self.audio.in_level < 0.65 else ("#faa61a" if self.audio.in_level < 0.88 else "#f04747")
                self.canvas_in.create_rectangle(0, 0, fill_w, 18, fill=color, outline="")
                for pct in [0.25, 0.5, 0.75]:
                    x = int(w_in * pct)
                    self.canvas_in.create_line(x, 0, x, 18, fill="#2f3136")

            # Update Voice OUT canvas
            w_out = self.canvas_out.winfo_width()
            if w_out > 1:
                self.canvas_out.delete("all")
                fill_w = int(w_out * self.audio.out_level)
                color = "#7289da" if self.audio.out_level < 0.65 else ("#faa61a" if self.audio.out_level < 0.88 else "#f04747")
                self.canvas_out.create_rectangle(0, 0, fill_w, 18, fill=color, outline="")
                for pct in [0.25, 0.5, 0.75]:
                    x = int(w_out * pct)
                    self.canvas_out.create_line(x, 0, x, 18, fill="#2f3136")

            self.root.after(33, _loop)  # ~30 FPS

        self.root.after(100, _loop)

    # ================= SYSTEM TRAY =================
    def _create_tray_icon(self):
        img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#7289da")
        d.ellipse([20, 20, 44, 44], fill="#ffffff")
        return img

    def _init_tray(self):
        menu = (
            pystray.MenuItem("Show Studio", self.show_from_tray, default=True),
            pystray.MenuItem("Toggle Voice (F8)", self._on_press_bypass),
            pystray.MenuItem("Mute Mic (F7)", self._on_press_mute),
            pystray.MenuItem("Exit", self.quit_app),
        )
        self.tray_icon = pystray.Icon("MicModStudio", self._create_tray_icon(), "Mic Modulator Studio Pro", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_to_tray(self):
        self.root.withdraw()

    def show_from_tray(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon=None, item=None):
        self.audio.stop_stream()
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)


if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    root = tk.Tk()
    app = VoiceTrayApp(root)
    root.mainloop()