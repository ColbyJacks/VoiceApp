# 📦 Dependency Reference & Installation Guide

This document lists all required dependencies for the project, their roles, and setup commands across platforms.

---

## 📋 Dependency Categories

### 1. Core Audio Processing & DSP
| Package | Version | Purpose |
| :--- | :--- | :--- |
| `sounddevice` | `>=0.4.6` | Low-latency audio stream I/O via WASAPI (Windows) and ALSA/PulseAudio (Linux). |
| `soundfile` | `>=0.12.1` | High-fidelity WAV/FLAC audio reading and writing. |
| `librosa` | `>=0.10.2` | Audio feature extraction, STFT, and time-frequency transformations. |
| `scipy` | `>=1.13.0` | Digital signal processing (Butterworth filters, signal resampling). |
| `noisereduce` | `>=3.0.0` | Spectral gating for background noise removal. |
| `pedalboard` | `>=0.8.0` | Spotify's real-time DSP effects (Noise Gate, Reverb, Delay, Chorus, Limiter). |
| `stftpitchshift` | `>=1.5.0` | Phase vocoder pitch shifting routines. |
| `soxr` | `>=0.3.7` | High-quality audio resampling. |
| `resampy` | `>=0.4.3` | Polyphase audio resampling algorithms. |
| `webrtcvad-wheels` | `>=2.0.10` | WebRTC Voice Activity Detection (VAD). |

### 2. Neural Networks & PyTorch Ecosystem
| Package | Version | Purpose |
| :--- | :--- | :--- |
| `torch` | `>=2.2.0` | Deep learning tensor operations and CUDA acceleration. |
| `torchaudio` | `>=2.2.0` | PyTorch native audio filters and spectrogram operations. |
| `torchcrepe` | `>=0.0.22` | CREPE deep neural network pitch extractor. |
| `torchfcpe` | `>=0.0.4` | Fast Context-informed Pitch Estimation (FCPE). |
| `transformers` | `>=4.40.0` | HuBERT linguistic representation model architecture. |
| `einops` | `>=0.7.0` | Flexible tensor dimension transformations. |
| `faiss-cpu` | `>=1.8.0` | Fast vector similarity search for speaker index retrieval. |

### 3. Desktop GUI, Tray App & Global Hotkeys
| Package | Version | Purpose |
| :--- | :--- | :--- |
| `pystray` | `>=0.19.5` | Windows system tray icon and background notification menu. |
| `Pillow` | `>=10.0.0` | Image processing for tray icons and UI artwork. |
| `keyboard` | `>=0.13.5` | Global background hotkey hooks (`F8` bypass, `F7` mute). |

### 4. Media Ingestion & Web Interface
| Package | Version | Purpose |
| :--- | :--- | :--- |
| `yt-dlp` | `>=2024.4.9` | YouTube search and high-bitrate audio extraction. |
| `requests` | `>=2.31.0` | HTTP client for downloading base models and assets. |
| `tqdm` | `>=4.66.0` | Real-time console progress bars. |
| `gradio` | `>=4.30.0` | Web UI framework for Applio full dashboard. |
| `tensorboard` | `>=2.16.0` | Training loss visualization and metric logging. |
| `matplotlib` | `>=3.8.0` | Waveform and spectrogram visualization. |

---

## 💻 Installation Steps

### Windows (Recommended)
```powershell
# 1. Create a clean Python virtual environment (Python 3.10 - 3.12)
python -m venv env
.\env\Scripts\activate

# 2. Install PyTorch with your system's CUDA version:
# For CUDA 12.4 / 12.8:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# 3. Install remaining minimal dependencies:
pip install -r requirements.txt
```

### Linux (Ubuntu / Debian)
```bash
# 1. Install system audio libraries
sudo apt update
sudo apt install -y python3-dev python3-venv portaudio19-dev libsndfile1 ffmpeg

# 2. Setup virtual environment
python3 -m venv env
source env/bin/activate

# 3. Install PyTorch with CUDA
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# 4. Install dependencies
pip install -r requirements.txt
```
