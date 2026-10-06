import os
import sys
import time
import json
import shutil
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np
import sounddevice as sd
import soundfile as sf
import yt_dlp

# Set BASE_DIR and ensure it's in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Directories
RAW_DIR = BASE_DIR / "raw_recordings"
CLEANED_DIR = BASE_DIR / "cleaned_for_rvc"
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"
EXPORTED_DIR = BASE_DIR / "exported_models"
TEST_OUTPUTS_DIR = BASE_DIR / "test_outputs"

for d in [RAW_DIR, CLEANED_DIR, MODELS_DIR, LOGS_DIR, EXPORTED_DIR, TEST_OUTPUTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

PYTHON_EXE = str(BASE_DIR / "env" / "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = str(BASE_DIR / "env" / "Scripts" / "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

FFMPEG_PATH = str(BASE_DIR / "ffmpeg.exe") if (BASE_DIR / "ffmpeg.exe").exists() else "ffmpeg"


class AudioPlayer:
    """Simple non-blocking audio player using sounddevice."""
    def __init__(self):
        self.current_stream = None
        self.is_playing = False

    def play(self, file_path: str, on_done=None):
        self.stop()
        if not os.path.exists(file_path):
            return

        def _play_worker():
            try:
                data, sr = sf.read(file_path)
                self.is_playing = True
                sd.play(data, sr)
                sd.wait()
            except Exception as e:
                print(f"[Player Error] {e}")
            finally:
                self.is_playing = False
                if on_done:
                    on_done()

        threading.Thread(target=_play_worker, daemon=True).start()

    def stop(self):
        try:
            sd.stop()
        except Exception:
            pass
        self.is_playing = False


class AudioRecorder:
    """Simple audio recorder for testing voices."""
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.recording = []
        self.is_recording = False
        self.stream = None

    def start(self, device_idx=None):
        self.recording = []
        self.is_recording = True

        def _callback(indata, frames, time_info, status):
            if self.is_recording:
                self.recording.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=device_idx,
            callback=_callback,
        )
        self.stream.start()

    def stop(self, save_path: str):
        self.is_recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if self.recording:
            audio_data = np.concatenate(self.recording, axis=0)
            sf.write(save_path, audio_data, self.sample_rate, subtype="PCM_16")
            return save_path
        return None


class VoiceTrainerStudioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Voice Studio: Grab, Clean, Train & Test")
        self.root.geometry("820x660")
        self.root.minsize(760, 580)
        self.root.configure(bg="#18191c")

        self.player = AudioPlayer()
        self.recorder = AudioRecorder(sample_rate=48000)
        self.training_process = None

        self._init_styles()
        self._build_tabs()

    def _init_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        bg_main = "#18191c"
        bg_card = "#232428"
        bg_entry = "#2f3136"
        fg_text = "#e0e0e0"
        accent = "#7289da"

        style.configure("TNotebook", background=bg_main, borderwidth=0)
        style.configure("TNotebook.Tab", background=bg_card, foreground=fg_text, padding=[16, 8], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", "#ffffff")])

        style.configure("TFrame", background=bg_main)
        style.configure("Card.TFrame", background=bg_card, relief="flat")
        style.configure("TLabel", background=bg_main, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=bg_card, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=bg_card, foreground="#ffffff", font=("Segoe UI", 11, "bold"))
        style.configure("Header.TLabel", background=bg_card, foreground=accent, font=("Segoe UI", 9, "bold"))

        style.configure("TEntry", fieldbackground=bg_entry, foreground="#ffffff", insertcolor="#ffffff")
        style.configure("TCombobox", fieldbackground=bg_entry, foreground="#ffffff", background=bg_card)

        style.configure("Treeview", background=bg_entry, foreground="#ffffff", fieldbackground=bg_entry, font=("Segoe UI", 8), rowheight=24)
        style.configure("Treeview.Heading", background=bg_card, foreground=accent, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#5865f2")], foreground=[("selected", "#ffffff")])

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Tab 1: YouTube Grabber
        self.tab_yt = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_yt, text="1. 🎥 YouTube Grabber")
        self._build_tab_youtube()

        # Tab 2: Denoise & Cleaner
        self.tab_clean = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_clean, text="2. 🧹 Denoise & Clean")
        self._build_tab_clean()

        # Tab 3: Neural Trainer
        self.tab_train = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_train, text="3. 🧠 Neural Training")
        self._build_tab_train()

        # Tab 4: Voice Tester & Inference Preview
        self.tab_test = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_test, text="4. 🎙️ Voice Tester")
        self._build_tab_test()

    # =========================================================================
    # TAB 1: YOUTUBE GRABBER
    # =========================================================================
    def _build_tab_youtube(self):
        card = ttk.Frame(self.tab_yt, style="Card.TFrame", padding=14)
        card.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card, text="YouTube Long-Audio & Speech Extractor", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(card, text="Search for interview, podcast, or monologue clips, or paste direct URLs to grab vocal audio for your dataset.", style="Card.TLabel").pack(anchor="w", pady=(0, 12))

        # Search Bar
        search_frame = ttk.Frame(card, style="Card.TFrame")
        search_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(search_frame, text="Search Keywords or URL:", style="Header.TLabel").pack(anchor="w")
        self.yt_query_var = tk.StringVar(value="long interview talking monologue podcast")
        self.yt_query_entry = ttk.Entry(search_frame, textvariable=self.yt_query_var)
        self.yt_query_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4, padx=(0, 8))

        self.btn_yt_search = tk.Button(
            search_frame, text="SEARCH YOUTUBE", bg="#5865f2", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_yt_search, padx=12, pady=3
        )
        self.btn_yt_search.pack(side=tk.RIGHT)

        # Search Results Table
        columns = ("title", "duration", "channel", "url")
        self.yt_tree = ttk.Treeview(card, columns=columns, show="headings", height=8)
        self.yt_tree.heading("title", text="Title")
        self.yt_tree.heading("duration", text="Duration")
        self.yt_tree.heading("channel", text="Channel")
        self.yt_tree.heading("url", text="URL")

        self.yt_tree.column("title", width=340)
        self.yt_tree.column("duration", width=70, anchor="center")
        self.yt_tree.column("channel", width=140)
        self.yt_tree.column("url", width=160)

        self.yt_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.yt_tree.bind("<Double-1>", self._on_yt_select_item)

        # Download & Trimming Settings
        dl_frame = ttk.Frame(card, style="Card.TFrame")
        dl_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(dl_frame, text="Target URL:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        self.yt_target_url_var = tk.StringVar()
        self.yt_target_url_entry = ttk.Entry(dl_frame, textvariable=self.yt_target_url_var, width=45)
        self.yt_target_url_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=6, pady=2)

        ttk.Label(dl_frame, text="Trim Start (HH:MM:SS):", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        self.yt_trim_start_var = tk.StringVar(value="")
        ttk.Entry(dl_frame, textvariable=self.yt_trim_start_var, width=12).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(dl_frame, text="Trim End (HH:MM:SS):", style="Card.TLabel").grid(row=1, column=2, sticky="w", pady=2)
        self.yt_trim_end_var = tk.StringVar(value="")
        ttk.Entry(dl_frame, textvariable=self.yt_trim_end_var, width=12).grid(row=1, column=3, sticky="w", padx=6, pady=2)
        dl_frame.columnconfigure(1, weight=1)

        # Download Action
        action_frame = ttk.Frame(card, style="Card.TFrame")
        action_frame.pack(fill=tk.X, pady=(4, 0))

        self.yt_status_lbl = ttk.Label(action_frame, text="Ready", style="Card.TLabel")
        self.yt_status_lbl.pack(side=tk.LEFT)

        self.btn_yt_download = tk.Button(
            action_frame, text="DOWNLOAD AUDIO (WAV)", bg="#43b581", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_yt_download, padx=16, pady=5
        )
        self.btn_yt_download.pack(side=tk.RIGHT)

    def _on_yt_search(self):
        query = self.yt_query_var.get().strip()
        if not query:
            return

        self.yt_status_lbl.config(text="Searching YouTube...")
        self.btn_yt_search.config(state="disabled")

        def _worker():
            try:
                # If direct URL
                if query.startswith("http://") or query.startswith("https://") or "youtube.com" in query or "youtu.be" in query:
                    ydl_opts = {"quiet": True, "extract_flat": True}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(query, download=False)
                        results = [{
                            "title": info.get("title", "Video"),
                            "duration": self._fmt_duration(info.get("duration", 0)),
                            "channel": info.get("uploader", info.get("channel", "Unknown")),
                            "url": query,
                        }]
                else:
                    # Search keywords
                    ydl_opts = {"quiet": True, "extract_flat": True, "default_search": "ytsearch10"}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(f"ytsearch10:{query}", download=False)
                        entries = info.get("entries", [])
                        results = []
                        for e in entries:
                            if e:
                                results.append({
                                    "title": e.get("title", "No Title"),
                                    "duration": self._fmt_duration(e.get("duration", 0)),
                                    "channel": e.get("uploader", e.get("channel", "Unknown")),
                                    "url": e.get("url", f"https://www.youtube.com/watch?v={e.get('id')}"),
                                })

                def _update_ui():
                    for item in self.yt_tree.get_children():
                        self.yt_tree.delete(item)
                    for r in results:
                        self.yt_tree.insert("", tk.END, values=(r["title"], r["duration"], r["channel"], r["url"]))
                    self.yt_status_lbl.config(text=f"Found {len(results)} videos.")
                    self.btn_yt_search.config(state="normal")
                self.root.after(0, _update_ui)

            except Exception as e:
                def _err():
                    self.yt_status_lbl.config(text=f"Search Error: {str(e)[:40]}")
                    self.btn_yt_search.config(state="normal")
                self.root.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _fmt_duration(self, seconds):
        if not seconds:
            return "--:--"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def _on_yt_select_item(self, event):
        selected = self.yt_tree.selection()
        if selected:
            vals = self.yt_tree.item(selected[0], "values")
            if vals and len(vals) >= 4:
                self.yt_target_url_var.set(vals[3])

    def _on_yt_download(self):
        url = self.yt_target_url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please select a video from the list or paste a YouTube URL.")
            return

        self.btn_yt_download.config(state="disabled", text="DOWNLOADING...", bg="#faa61a")
        self.yt_status_lbl.config(text="Fetching & extracting high-quality audio...")

        start_time = self.yt_trim_start_var.get().strip()
        end_time = self.yt_trim_end_var.get().strip()

        def _worker():
            try:
                out_tmpl = str(RAW_DIR / "%(title)s [%(id)s].%(ext)s")
                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": out_tmpl,
                    "ffmpeg_location": FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else None,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "wav",
                    }],
                    "quiet": False,
                }

                # Add time range trimming if specified
                if start_time or end_time:
                    pp_args = []
                    if start_time:
                        pp_args.extend(["-ss", start_time])
                    if end_time:
                        pp_args.extend(["-to", end_time])
                    ydl_opts["postprocessor_args"] = {"ffmpeg": pp_args}

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get("title", "downloaded_audio")

                def _success():
                    self.yt_status_lbl.config(text=f"Downloaded: {title[:30]}... saved to raw_recordings")
                    self.btn_yt_download.config(state="normal", text="DOWNLOAD AUDIO (WAV)", bg="#43b581")
                    self._refresh_clean_file_list()
                    messagebox.showinfo("Download Complete", f"Downloaded and extracted audio:\n{title}\nSaved to raw_recordings.")
                self.root.after(0, _success)

            except Exception as e:
                def _fail():
                    self.yt_status_lbl.config(text=f"Download Error: {str(e)[:40]}")
                    self.btn_yt_download.config(state="normal", text="DOWNLOAD AUDIO (WAV)", bg="#43b581")
                    messagebox.showerror("Download Error", str(e))
                self.root.after(0, _fail)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # TAB 2: DENOISE & CLEANER
    # =========================================================================
    def _build_tab_clean(self):
        card = ttk.Frame(self.tab_clean, style="Card.TFrame", padding=14)
        card.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card, text="Audio Preprocessing & Dataset Cleaner", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(card, text="Cleans background hiss, hum, desk rumble, and normalizes sample rate to 48kHz mono for RVC training.", style="Card.TLabel").pack(anchor="w", pady=(0, 10))

        # Files list
        list_frame = ttk.Frame(card, style="Card.TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        ttk.Label(list_frame, text="Files in raw_recordings/:", style="Header.TLabel").pack(anchor="w", pady=(0, 4))

        self.clean_tree = ttk.Treeview(list_frame, columns=("name", "size"), show="headings", height=7)
        self.clean_tree.heading("name", text="Filename")
        self.clean_tree.heading("size", text="Size")
        self.clean_tree.column("name", width=550)
        self.clean_tree.column("size", width=120, anchor="center")
        self.clean_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.clean_tree.yview)
        self.clean_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Audio Preview Controls
        preview_frame = ttk.Frame(card, style="Card.TFrame")
        preview_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_play_raw = tk.Button(
            preview_frame, text="▶ PREVIEW SELECTED AUDIO", bg="#5865f2", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_play_raw_selected, padx=10, pady=3
        )
        self.btn_play_raw.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_stop_audio = tk.Button(
            preview_frame, text="⏹ STOP", bg="#4f545c", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self.player.stop, padx=10, pady=3
        )
        self.btn_stop_audio.pack(side=tk.LEFT, padx=(0, 6))

        btn_refresh = tk.Button(
            preview_frame, text="🔄 REFRESH LIST", bg="#4f545c", fg="white", font=("Segoe UI", 9),
            relief="flat", cursor="hand2", command=self._refresh_clean_file_list, padx=10, pady=3
        )
        btn_refresh.pack(side=tk.RIGHT)

        # Cleaning Parameters
        params_frame = ttk.Frame(card, style="Card.TFrame")
        params_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(params_frame, text="Noise Reduction Strength (0.0 to 1.0):", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.clean_strength_var = tk.DoubleVar(value=0.85)
        self.clean_slider = tk.Scale(
            params_frame, from_=0.0, to=1.0, resolution=0.05, orient=tk.HORIZONTAL,
            variable=self.clean_strength_var, showvalue=True, bg="#232428", fg="#ffffff", highlightthickness=0
        )
        self.clean_slider.grid(row=0, column=1, sticky="ew", padx=10)

        params_frame.columnconfigure(1, weight=1)

        # Clean Action Button
        clean_action_frame = ttk.Frame(card, style="Card.TFrame")
        clean_action_frame.pack(fill=tk.X, pady=(4, 0))

        self.clean_status_lbl = ttk.Label(clean_action_frame, text="Ready", style="Card.TLabel")
        self.clean_status_lbl.pack(side=tk.LEFT)

        self.btn_run_cleaner = tk.Button(
            clean_action_frame, text="DENOISE & CLEAN ALL FILES FOR DATASET", bg="#43b581", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_run_cleaner, padx=16, pady=6
        )
        self.btn_run_cleaner.pack(side=tk.RIGHT)

        self._refresh_clean_file_list()

    def _refresh_clean_file_list(self):
        for item in self.clean_tree.get_children():
            self.clean_tree.delete(item)
        extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
        files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in extensions]
        for f in files:
            size_mb = f.stat().st_size / (1024 * 1024)
            self.clean_tree.insert("", tk.END, values=(f.name, f"{size_mb:.2f} MB"))

    def _on_play_raw_selected(self):
        selected = self.clean_tree.selection()
        if not selected:
            messagebox.showinfo("Select File", "Please select an audio file from the list to preview.")
            return
        fname = self.clean_tree.item(selected[0], "values")[0]
        fpath = str(RAW_DIR / fname)
        self.player.play(fpath)

    def _on_run_cleaner(self):
        extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
        files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in extensions]
        if not files:
            messagebox.showwarning("No Audio", "No audio files found in raw_recordings folder to clean.")
            return

        self.btn_run_cleaner.config(state="disabled", text="CLEANING DATASET...", bg="#faa61a")
        strength = self.clean_strength_var.get()

        def _worker():
            try:
                import noisereduce as nr
                from scipy.signal import butter, sosfilt
                from scipy.signal import resample_poly
                from math import gcd

                target_sr = 48000
                sos_highpass = butter(2, 80, btype="highpass", fs=target_sr, output="sos")

                for idx, file_path in enumerate(files, start=1):
                    def _prog(i=idx, name=file_path.name):
                        self.clean_status_lbl.config(text=f"[{i}/{len(files)}] Cleaning: {name[:30]}...")
                    self.root.after(0, _prog)

                    data, sr = sf.read(file_path)
                    if data.ndim > 1:
                        data = np.mean(data, axis=1)

                    if sr != target_sr:
                        g = gcd(target_sr, sr)
                        data = resample_poly(data, target_sr // g, sr // g)
                        sr = target_sr

                    data = sosfilt(sos_highpass, data)

                    cleaned = nr.reduce_noise(
                        y=data,
                        sr=sr,
                        prop_decrease=strength,
                        stationary=True,
                        n_fft=1024
                    )

                    out_file = CLEANED_DIR / f"{file_path.stem}_cleaned.wav"
                    sf.write(out_file, cleaned.astype(np.float32), samplerate=target_sr, subtype="PCM_16")

                def _done():
                    self.clean_status_lbl.config(text=f"Completed! Cleaned {len(files)} files into cleaned_for_rvc.")
                    self.btn_run_cleaner.config(state="normal", text="DENOISE & CLEAN ALL FILES FOR DATASET", bg="#43b581")
                    messagebox.showinfo("Dataset Ready", f"Cleaned {len(files)} files successfully!\nFiles saved to: cleaned_for_rvc\nReady for Neural Training.")
                self.root.after(0, _done)

            except Exception as e:
                def _err():
                    self.clean_status_lbl.config(text=f"Cleaning Error: {str(e)[:40]}")
                    self.btn_run_cleaner.config(state="normal", text="DENOISE & CLEAN ALL FILES FOR DATASET", bg="#43b581")
                    messagebox.showerror("Cleaning Error", str(e))
                self.root.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # TAB 3: NEURAL TRAINING
    # =========================================================================
    def _build_tab_train(self):
        card = ttk.Frame(self.tab_train, style="Card.TFrame", padding=14)
        card.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card, text="Neural Voice Model Trainer", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(card, text="Executes the full training pipeline (Preprocessing ➔ Feature Extraction ➔ GAN Training ➔ FAISS Indexing ➔ Model Packaging).", style="Card.TLabel").pack(anchor="w", pady=(0, 10))

        # Parameters Frame
        cfg_frame = ttk.Frame(card, style="Card.TFrame")
        cfg_frame.pack(fill=tk.X, pady=(0, 10))

        # Row 0: Model Name & Epochs
        ttk.Label(cfg_frame, text="Model Name:", style="Header.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.train_model_name_var = tk.StringVar(value="MyNewCustomVoice")
        ttk.Entry(cfg_frame, textvariable=self.train_model_name_var, width=22).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(cfg_frame, text="Total Epochs:", style="Header.TLabel").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=4)
        self.train_epochs_var = tk.StringVar(value="250")
        ttk.Entry(cfg_frame, textvariable=self.train_epochs_var, width=8).grid(row=0, column=3, sticky="w", padx=6, pady=4)

        # Row 1: Batch Size & Save Interval
        ttk.Label(cfg_frame, text="Batch Size:", style="Header.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.train_batch_var = tk.StringVar(value="4")
        ttk.Entry(cfg_frame, textvariable=self.train_batch_var, width=22).grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(cfg_frame, text="Save Every N Epochs:", style="Header.TLabel").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=4)
        self.train_save_epoch_var = tk.StringVar(value="25")
        ttk.Entry(cfg_frame, textvariable=self.train_save_epoch_var, width=8).grid(row=1, column=3, sticky="w", padx=6, pady=4)

        # Live Console Output Box
        ttk.Label(card, text="Live Training Pipeline Console Output:", style="Header.TLabel").pack(anchor="w", pady=(6, 2))

        console_frame = ttk.Frame(card, style="Card.TFrame")
        console_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.train_log_box = tk.Text(console_frame, bg="#1e1e24", fg="#a9b1d6", insertbackground="white", font=("Consolas", 8), relief="flat")
        self.train_log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll_log = ttk.Scrollbar(console_frame, orient=tk.VERTICAL, command=self.train_log_box.yview)
        self.train_log_box.configure(yscrollcommand=scroll_log.set)
        scroll_log.pack(side=tk.RIGHT, fill=tk.Y)

        # Actions
        btn_box = ttk.Frame(card, style="Card.TFrame")
        btn_box.pack(fill=tk.X)

        self.btn_stop_train = tk.Button(
            btn_box, text="⏹ CANCEL / STOP", bg="#f04747", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_stop_training, padx=14, pady=5, state="disabled"
        )
        self.btn_stop_train.pack(side=tk.LEFT)

        self.btn_start_train = tk.Button(
            btn_box, text="🚀 START 1-CLICK TRAINING PIPELINE", bg="#43b581", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_start_training, padx=16, pady=5
        )
        self.btn_start_train.pack(side=tk.RIGHT)

    def _log_train(self, msg):
        def _append():
            self.train_log_box.insert(tk.END, msg + "\n")
            self.train_log_box.see(tk.END)
        self.root.after(0, _append)

    def _on_start_training(self):
        model_name = self.train_model_name_var.get().strip()
        epochs = self.train_epochs_var.get().strip()
        batch_size = self.train_batch_var.get().strip()
        save_every = self.train_save_epoch_var.get().strip()

        if not model_name:
            messagebox.showwarning("Model Name", "Please enter a valid model name.")
            return

        cleaned_files = list(CLEANED_DIR.glob("*.wav"))
        if not cleaned_files:
            messagebox.showwarning("Empty Dataset", "cleaned_for_rvc folder is empty. Please run Step 2 (Denoise & Clean) first!")
            return

        self.btn_start_train.config(state="disabled", text="TRAINING IN PROGRESS...", bg="#faa61a")
        self.btn_stop_train.config(state="normal")
        self.train_log_box.delete("1.0", tk.END)

        def _worker():
            try:
                self._log_train(f"=== [STEP 1/4] Preprocessing Dataset ({len(cleaned_files)} files) ===")
                cmd_pre = [
                    PYTHON_EXE, "core.py", "preprocess",
                    "--model_name", model_name,
                    "--dataset_path", str(CLEANED_DIR),
                    "--sample_rate", "48000",
                    "--cut_preprocess", "Automatic"
                ]
                self._run_subprocess(cmd_pre)

                self._log_train("\n=== [STEP 2/4] Feature Extraction (RMVPE + ContentVec) ===")
                cmd_ext = [
                    PYTHON_EXE, "core.py", "extract",
                    "--model_name", model_name,
                    "--sample_rate", "48000",
                    "--f0_method", "rmvpe",
                    "--embedder_model", "contentvec",
                    "--include_mutes", "2",
                    "--cpu_cores", "4",
                    "--gpu", "0"
                ]
                self._run_subprocess(cmd_ext)

                self._log_train(f"\n=== [STEP 3/4] Neural GAN Training ({epochs} Epochs) ===")
                cmd_trn = [
                    PYTHON_EXE, "core.py", "train",
                    "--model_name", model_name,
                    "--sample_rate", "48000",
                    "--total_epoch", epochs,
                    "--batch_size", batch_size,
                    "--save_every_epoch", save_every,
                    "--save_every_weights", "True",
                    "--gpu", "0"
                ]
                self._run_subprocess(cmd_trn)

                self._log_train("\n=== [STEP 4/4] Building FAISS Index & Extracting Weights ===")
                cmd_idx = [
                    PYTHON_EXE, "core.py", "index",
                    "--model_name", model_name
                ]
                self._run_subprocess(cmd_idx)

                # Post-Processing Extract & Copy
                self._log_train("\n=== Packaging & Syncing Checkpoints to models/ ===")
                model_log_dir = LOGS_DIR / model_name
                out_export_dir = EXPORTED_DIR / model_name
                out_export_dir.mkdir(parents=True, exist_ok=True)

                pth_files = list(model_log_dir.glob(f"{model_name}.pth")) or list(model_log_dir.glob(f"{model_name}_*.pth"))
                if not pth_files:
                    # Extract from G_*.pth
                    g_ckpts = sorted(
                        list(model_log_dir.glob("G_*.pth")),
                        key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 0
                    )
                    if g_ckpts:
                        latest_g = g_ckpts[-1]
                        self._log_train(f"Extracting model from {latest_g.name}...")
                        from rvc.train.process.extract_model import extract_model
                        import torch
                        ckpt = torch.load(latest_g, map_location="cpu")
                        cfg_path = model_log_dir / "config.json"
                        if cfg_path.exists():
                            with open(cfg_path, "r", encoding="utf-8") as f:
                                hps_dict = json.load(f)
                            from types import SimpleNamespace
                            def dict_to_ns(d):
                                if isinstance(d, dict):
                                    return SimpleNamespace(**{k: dict_to_ns(v) for k, v in d.items()})
                                return d
                            hps = dict_to_ns(hps_dict)
                            dest_pth = model_log_dir / f"{model_name}.pth"
                            extract_model(
                                ckpt=ckpt.get("model", ckpt.get("weight", ckpt)),
                                sr=48000,
                                name=model_name,
                                model_path=str(dest_pth),
                                epoch=int(epochs),
                                step=int(latest_g.stem.split("_")[1]) if latest_g.stem.split("_")[1].isdigit() else 0,
                                hps=hps,
                                vocoder="HiFi-GAN",
                                pitch_guidance=True,
                                version="v2"
                            )
                            if dest_pth.exists():
                                pth_files = [dest_pth]

                idx_files = list(model_log_dir.glob("*.index"))

                if pth_files:
                    shutil.copy2(pth_files[0], out_export_dir / f"{model_name}.pth")
                    shutil.copy2(pth_files[0], MODELS_DIR / f"{model_name}.pth")
                    self._log_train(f"✓ Model weights saved to: models/{model_name}.pth")

                if idx_files:
                    shutil.copy2(idx_files[0], out_export_dir / f"{model_name}.index")
                    shutil.copy2(idx_files[0], MODELS_DIR / f"{model_name}.index")
                    self._log_train(f"✓ FAISS search index saved to: models/{model_name}.index")

                self._log_train("\n🎉 TRAINING PIPELINE COMPLETED SUCCESSFULLY!")
                def _done():
                    self.btn_start_train.config(state="normal", text="🚀 START 1-CLICK TRAINING PIPELINE", bg="#43b581")
                    self.btn_stop_train.config(state="disabled")
                    self._refresh_tester_models()
                    messagebox.showinfo("Training Complete", f"Voice Model '{model_name}' trained successfully!\nAvailable in Voice Tester tab and Mic Modulator app.")
                self.root.after(0, _done)

            except Exception as e:
                self._log_train(f"\n[ERROR] Training failed: {e}")
                def _err():
                    self.btn_start_train.config(state="normal", text="🚀 START 1-CLICK TRAINING PIPELINE", bg="#43b581")
                    self.btn_stop_train.config(state="disabled")
                    messagebox.showerror("Training Error", str(e))
                self.root.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_subprocess(self, cmd):
        self.training_process = subprocess.Popen(
            cmd, cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        for line in iter(self.training_process.stdout.readline, ""):
            if line:
                self._log_train(line.strip())
        self.training_process.stdout.close()
        rc = self.training_process.wait()
        if rc != 0:
            raise RuntimeError(f"Command failed with return code {rc}")

    def _on_stop_training(self):
        if self.training_process and self.training_process.poll() is None:
            self.training_process.terminate()
            self._log_train("\n[TRAINING CANCELLED BY USER]")
            self.btn_stop_train.config(state="disabled")
            self.btn_start_train.config(state="normal", text="🚀 START 1-CLICK TRAINING PIPELINE", bg="#43b581")

    # =========================================================================
    # TAB 4: VOICE TESTER & INFERENCE PREVIEW
    # =========================================================================
    def _build_tab_test(self):
        card = ttk.Frame(self.tab_test, style="Card.TFrame", padding=14)
        card.pack(fill=tk.BOTH, expand=True)

        ttk.Label(card, text="Voice Model Tester & Audio Preview", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(card, text="Test your trained voice models against live microphone recordings or audio files to verify quality before streaming.", style="Card.TLabel").pack(anchor="w", pady=(0, 10))

        # Model Selection Frame
        m_frame = ttk.Frame(card, style="Card.TFrame")
        m_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(m_frame, text="Select Voice Model:", style="Header.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.test_model_var = tk.StringVar()
        self.test_model_cb = ttk.Combobox(m_frame, textvariable=self.test_model_var, state="readonly", width=30)
        self.test_model_cb.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        btn_refresh_models = tk.Button(
            m_frame, text="🔄 REFRESH", bg="#4f545c", fg="white", font=("Segoe UI", 8),
            relief="flat", cursor="hand2", command=self._refresh_tester_models, padx=6, pady=2
        )
        btn_refresh_models.grid(row=0, column=2, sticky="w", padx=4)

        # Audio Input Mode (Record or Select File)
        in_frame = ttk.LabelFrame(card, text="  Test Audio Source  ", style="Card.TFrame", padding=10)
        in_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_rec = tk.Button(
            in_frame, text="🎙️ RECORD FROM MIC", bg="#e040fb", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_toggle_record, padx=12, pady=4
        )
        self.btn_rec.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(in_frame, text="OR", style="Card.TLabel").pack(side=tk.LEFT, padx=6)

        btn_browse_audio = tk.Button(
            in_frame, text="📁 SELECT AUDIO FILE", bg="#5865f2", fg="white", font=("Segoe UI", 9),
            relief="flat", cursor="hand2", command=self._on_select_test_audio, padx=10, pady=4
        )
        btn_browse_audio.pack(side=tk.LEFT, padx=6)

        self.test_src_audio_path = tk.StringVar(value="")
        self.test_src_lbl = ttk.Label(in_frame, text="No test audio loaded", style="Card.TLabel")
        self.test_src_lbl.pack(side=tk.LEFT, padx=10)

        # Sliders Frame
        sliders_frame = ttk.Frame(card, style="Card.TFrame")
        sliders_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(sliders_frame, text="Pitch Shift (Semitones):", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        self.test_pitch_var = tk.IntVar(value=0)
        self.test_pitch_slider = tk.Scale(
            sliders_frame, from_=-24, to=24, resolution=1, orient=tk.HORIZONTAL,
            variable=self.test_pitch_var, showvalue=True, bg="#232428", fg="#ffffff", highlightthickness=0
        )
        self.test_pitch_slider.grid(row=0, column=1, sticky="ew", padx=10)

        ttk.Label(sliders_frame, text="Index Rate (Timbre match):", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        self.test_index_rate_var = tk.DoubleVar(value=0.75)
        self.test_index_slider = tk.Scale(
            sliders_frame, from_=0.0, to=1.0, resolution=0.05, orient=tk.HORIZONTAL,
            variable=self.test_index_rate_var, showvalue=True, bg="#232428", fg="#ffffff", highlightthickness=0
        )
        self.test_index_slider.grid(row=1, column=1, sticky="ew", padx=10)
        sliders_frame.columnconfigure(1, weight=1)

        # Convert Action Button
        self.btn_convert_test = tk.Button(
            card, text="⚡ CONVERT & PREVIEW VOICE", bg="#43b581", fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2", command=self._on_convert_test, pady=8
        )
        self.btn_convert_test.pack(fill=tk.X, pady=(4, 10))

        # Playback Comparison Box
        play_card = ttk.LabelFrame(card, text="  Audio Playback & Comparison  ", style="Card.TFrame", padding=10)
        play_card.pack(fill=tk.X, pady=(0, 4))

        self.btn_play_orig = tk.Button(
            play_card, text="▶ PLAY ORIGINAL", bg="#4f545c", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_play_original, padx=14, pady=4, state="disabled"
        )
        self.btn_play_orig.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_play_conv = tk.Button(
            play_card, text="✨ PLAY CONVERTED VOICE", bg="#7289da", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2", command=self._on_play_converted, padx=14, pady=4, state="disabled"
        )
        self.btn_play_conv.pack(side=tk.LEFT, padx=10)

        self.btn_stop_test_audio = tk.Button(
            play_card, text="⏹ STOP", bg="#2f3136", fg="white", font=("Segoe UI", 9),
            relief="flat", cursor="hand2", command=self.player.stop, padx=12, pady=4
        )
        self.btn_stop_test_audio.pack(side=tk.RIGHT)

        self.test_converted_file = None
        self._refresh_tester_models()

    def _refresh_tester_models(self):
        models = [f.name for f in MODELS_DIR.glob("*.pth")]
        self.test_model_cb.config(values=models)
        if models:
            self.test_model_var.set(models[0])

    def _on_toggle_record(self):
        if not self.recorder.is_recording:
            self.recorder.start()
            self.btn_rec.config(text="⏹ STOP RECORDING", bg="#f04747")
            self.test_src_lbl.config(text="Recording from microphone...")
        else:
            rec_path = str(TEST_OUTPUTS_DIR / "mic_test_recording.wav")
            out = self.recorder.stop(rec_path)
            self.btn_rec.config(text="🎙️ RECORD FROM MIC", bg="#e040fb")
            if out:
                self.test_src_audio_path.set(out)
                self.test_src_lbl.config(text=f"Recorded: mic_test_recording.wav")
                self.btn_play_orig.config(state="normal")

    def _on_select_test_audio(self):
        f = filedialog.askopenfilename(filetypes=[("Audio Files", "*.wav;*.mp3;*.flac;*.ogg;*.m4a")])
        if f:
            self.test_src_audio_path.set(f)
            self.test_src_lbl.config(text=f"Selected: {Path(f).name[:25]}")
            self.btn_play_orig.config(state="normal")

    def _on_play_original(self):
        f = self.test_src_audio_path.get()
        if f and os.path.exists(f):
            self.player.play(f)

    def _on_play_converted(self):
        if self.test_converted_file and os.path.exists(self.test_converted_file):
            self.player.play(self.test_converted_file)

    def _on_convert_test(self):
        src_audio = self.test_src_audio_path.get()
        if not src_audio or not os.path.exists(src_audio):
            messagebox.showwarning("No Input Audio", "Please record mic audio or select an audio file first.")
            return

        model_name = self.test_model_var.get()
        if not model_name:
            messagebox.showwarning("No Model", "Please select a trained voice model (.pth).")
            return

        model_path = str(MODELS_DIR / model_name)
        index_path = str(MODELS_DIR / f"{Path(model_name).stem}.index")
        if not os.path.exists(index_path):
            index_path = None

        pitch = self.test_pitch_var.get()
        index_rate = self.test_index_rate_var.get()

        self.btn_convert_test.config(state="disabled", text="CONVERTING AUDIO...", bg="#faa61a")

        out_dest = str(TEST_OUTPUTS_DIR / f"converted_{Path(model_name).stem}.wav")

        def _worker():
            try:
                from rvc.infer.infer import VoiceConverter
                vc = VoiceConverter()
                vc.convert_audio(
                    audio_input_path=src_audio,
                    audio_output_path=out_dest,
                    model_path=model_path,
                    index_path=index_path,
                    pitch=pitch,
                    index_rate=index_rate,
                    f0_method="rmvpe",
                    embedder_model="contentvec",
                    export_format="WAV",
                )

                self.test_converted_file = out_dest

                def _success():
                    self.btn_convert_test.config(state="normal", text="⚡ CONVERT & PREVIEW VOICE", bg="#43b581")
                    self.btn_play_conv.config(state="normal")
                    # Auto play converted voice
                    self.player.play(out_dest)
                self.root.after(0, _success)

            except Exception as e:
                def _err():
                    self.btn_convert_test.config(state="normal", text="⚡ CONVERT & PREVIEW VOICE", bg="#43b581")
                    messagebox.showerror("Conversion Error", str(e))
                self.root.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()


if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    root = tk.Tk()
    app = VoiceTrainerStudioApp(root)
    root.mainloop()
