# 🎙️ Voice Modulator & Voice Trainer Studio Pro

> **High-Performance Real-Time AI Voice Modulation & Autonomous Voice Model Training Pipeline** powered by PyTorch, CUDA, RVC v2 (Retrieval-based Voice Conversion), and Spotify Pedalboard DSP.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![PyTorch CUDA](https://img.shields.io/badge/PyTorch-CUDA%20Accelerated-green.svg)](https://pytorch.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture & Workflow](#-architecture--workflow)
- [Quick Start Guide](#-quick-start-guide)
- [Applications & Tools](#-applications--tools)
  - [1. Voice Modulator Studio Pro (`voice_tray_app.py`)](#1-voice-modulator-studio-pro-voice_tray_apppy)
  - [2. Voice Trainer Studio (`voice_trainer_studio.py`)](#2-voice-trainer-studio-voice_trainer_studiopy)
  - [3. CLI & Pipeline Utilities](#3-cli--pipeline-utilities)
  - [4. Applio Web Interface (`app.py`)](#4-applio-web-interface-apppy)
- [Virtual Audio Cable Setup (Discord, OBS, Games)](#-virtual-audio-cable-setup)
- [Detailed Documentation](#-detailed-documentation)
- [Dependencies & Installation](#-dependencies--installation)
- [License](#-license)

---

## 🌟 Overview

This repository provides an all-in-one suite for real-time voice conversion and custom voice AI model training:
1. **Real-Time Voice Modulator Studio**: Zero-latency in-process GPU inference engine with live animated VU meters, WASAPI auto-channel matching, ear monitoring (sidetone), DSP effect racks (Reverb, Delay, Chorus, Radio/Telephone EQ, Soft Limiter), and global background hotkeys with system tray integration.
2. **Autonomous Voice Trainer Studio**: Streamlined UI to search YouTube, download clean speech audio clips, run AI spectral denoising, slice audio, extract HuBERT & RMVPE pitch features, and train production-ready `.pth` + `.index` voice models.
3. **Applio Full WebUI & CLI Core**: Advanced model customization, dataset preparation, ONNX export, and TensorBoard loss tracking.

---

## 🚀 Key Features

- ⚡ **Ultra-Low Latency Direct GPU Pipeline**: Runs in-process inference on CUDA (`~46ms` for 512ms audio blocks — **11x faster than real-time**).
- 🎚️ **Live WASAPI Audio Engine**: Real-time microphone input routing with channel-clamping, WASAPI non-exclusive low-latency streaming, and VB-Audio Virtual Cable support.
- 🎛️ **Studio DSP Effects Rack**: Built-in Spotify Pedalboard processing with Noise Gate, Highpass, Reverb (room size & wet mix), Delay (time & feedback), Chorus (depth & rate), Radio/Telephone filter, and safety soft limiters.
- ⌨️ **Global Background Hotkeys & Tray App**:
  - `F8`: Toggle between **Modulated AI Voice** and **Real Voice (Bypass)** instantly from inside any game or full-screen application.
  - `F7`: Global Microphone Mute toggle.
  - Minimizes to Windows System Tray with animated tray icon and right-click quick menu.
- 🎧 **Ear Monitor / Sidetone**: Listen to your own converted voice in your headphones with dedicated volume control while streaming to your virtual microphone.
- 🌐 **YouTube-to-Voice Ingestion Pipeline**: Search YouTube directly within the trainer UI, preview video duration/views, and auto-download high-bitrate audio.
- 🧹 **AI Spectral Denoising**: Removes background hiss, fans, and ambient noise using Butterworth bandpass filtering and spectral gating before model training.
- 🧠 **RVC v2 + RMVPE Pitch Guidance**: High-accuracy pitch tracking and FAISS feature index matching for natural, artifact-free voice conversion.

---

## 🏗️ Architecture & Workflow

```
[ Microphone (HyperX / USB Mic) ]
               │ (WASAPI Input Stream)
               ▼
[ Voice Modulator Studio (In-Process Audio Engine) ]
 ├── Input Volume Gain Booster
 ├── Silence Detection Gate (-60 dBFS)
 ├── RVC Realtime Inference (GPU CUDA:0)
 │    ├── HuBERT Feature Extraction
 │    ├── RMVPE Pitch Tracking
 │    ├── FAISS Index Speaker Retrieval (.index)
 │    └── HiFi-GAN Vocoder Synthesis (.pth)
 ├── Studio DSP Effects Rack (Pedalboard)
 │    ├── Noise Gate & Highpass Filter (80Hz)
 │    ├── Reverb / Delay / Chorus / Radio EQ
 │    └── Soft Output Peak Limiter (-0.5 dB)
 ├── Output Volume Booster & Metering
 ├── ├──► [ Ear Monitor Stream (Headphones) ]
 └── └──► [ Virtual Cable Input (VB-Audio) ] ──► [ Discord / OBS / Games / Zoom ]
```

---

## ⚡ Quick Start Guide

### Prerequisites
- **OS**: Windows 10/11 (or Linux with ALSA/PulseAudio/JACK)
- **Python**: Python 3.10, 3.11, or 3.12
- **GPU**: NVIDIA GPU with CUDA support (GTX 1060+ or RTX series recommended)
- **Virtual Audio Cable**: [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (Free)

### 1. Installation
Clone the repository and install the dependencies:

```powershell
# Clone the repository
git clone https://github.com/ColbyJacks/voice-modulator-studio.git
cd voice-modulator-studio

# Create a virtual environment
python -m venv env
.\env\Scripts\activate

# Install PyTorch with CUDA support (e.g. CUDA 12.4 / 12.8)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# Install required dependencies
pip install -r requirements.txt
```

### 2. Launching the Tools

| Tool | Launch Command | Batch Shortcut |
| :--- | :--- | :--- |
| **Voice Modulator Studio Pro** (Live Mic Changer) | `python voice_tray_app.py` | Double-click `run-voice-tray.bat` |
| **Voice Trainer Studio** (YouTube & Training UI) | `python voice_trainer_studio.py` | Double-click `run-trainer-studio.bat` |
| **Applio WebUI** (Full Web Interface) | `python app.py` | Double-click `run-applio.bat` |

---

## 🛠️ Applications & Tools

### 1. Voice Modulator Studio Pro (`voice_tray_app.py`)
A full-featured desktop voice modulation dashboard with a system tray mode.

- **Audio Routing**: Select your physical input microphone and your target output device (e.g., `CABLE Input`).
- **Ear Monitoring**: Enable "Hear Myself" to monitor your converted voice in real time through your headphones.
- **Voice Controls**: Pitch Shift (-24 to +24 semitones), Index Rate (accent strength), Volume Envelope, and Output Volume Booster (up to 3.0x).
- **DSP Rack**: Interactive sliders for Reverb, Delay, Chorus, and Radio/Telephone EQ.
- **Hotkeys**:
  - `F8`: Toggle Voice Modulation / Bypass (Real Voice)
  - `F7`: Toggle Microphone Mute

### 2. Voice Trainer Studio (`voice_trainer_studio.py`)
An autonomous voice cloning studio designed for fast dataset creation and model training.

- **Step 1: YouTube Audio Ingestion**: Search YouTube keywords or paste URLs, view video duration/details, and download audio.
- **Step 2: AI Denoising**: Remove background noise, hums, and music artifacts.
- **Step 3: Slicing & Preprocessing**: Automatically slice long audio into 3–4 second chunks and resample to 48kHz.
- **Step 4: Model Training**: Extract HuBERT features + RMVPE pitch tracks, train RVC v2 generator/discriminator for specified epochs, and build the FAISS `.index` file.
- **Step 5: Test Voice**: 1-click audio tester with pitch shifting to audition your new model instantly before deployment.

### 3. CLI & Pipeline Utilities
- `audio_to_pth.py`: Headless command-line training pipeline from a single audio file to `.pth` model.
- `audiodenoiser.py`: Command-line AI audio cleaner and spectral noise reducer.
- `pth_to_onnx.py`: Export RVC weights to ONNX format for cross-platform deployments.

---

## 🔌 Virtual Audio Cable Setup

To route your modulated voice into **Discord**, **OBS Studio**, **Zoom**, **VRChat**, or games:

1. Download and install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/).
2. In **Voice Modulator Studio Pro**:
   - Set **Microphone Input** to your physical microphone (e.g. *Microphone (HyperX QuadCast S)*).
   - Set **Output (Mic Out)** to `CABLE Input (VB-Audio Virtual Cable)`.
   - *(Optional)* Enable **Ear Monitor** and select your headphones.
3. In **Discord / Game Audio Settings**:
   - Set **Input Device** to `CABLE Output (VB-Audio Virtual Cable)`.
   - Set Input Sensitivity to automatic or low threshold.
4. Press `F8` to toggle between your real voice and your AI modulated voice on the fly.

---

## 📚 Detailed Documentation

Comprehensive guides are available in the [`docs/`](./docs/) directory:
- [📘 Architecture & Audio Pipeline Deep-Dive](./docs/ARCHITECTURE.md)
- [🎙️ Voice Modulator Studio & Realtime Guide](./docs/REALTIME_MODULATION.md)
- [🧠 Voice Training Studio & Dataset Pipeline Guide](./docs/TRAINING_GUIDE.md)
- [📦 Dependency Reference & Installation Guide](./docs/DEPENDENCIES.md)

---

## 📦 Dependencies

All dependencies are maintained in [requirements.txt](./requirements.txt). The core stack includes:
- `torch`, `torchaudio`, `torchcrepe`, `torchfcpe` (Neural inference & pitch extraction)
- `sounddevice`, `soundfile`, `librosa`, `scipy`, `pedalboard` (Low-latency audio streaming & DSP)
- `faiss-cpu` (Feature retrieval index)
- `pystray`, `Pillow`, `keyboard` (System tray & global hotkey hooks)
- `yt-dlp`, `noisereduce` (Audio ingestion & spectral cleaning)
- `gradio`, `tensorboard` (Web interface & training monitoring)

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE). Model weights, datasets, and voice conversions generated using this software must comply with applicable local laws, privacy regulations, and ethical AI guidelines.
