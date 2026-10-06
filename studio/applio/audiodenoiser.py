from pathlib import Path
import numpy as np
import soundfile as sf
import noisereduce as nr
from scipy.signal import butter, sosfilt

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "raw_recordings"
OUTPUT_DIR = BASE_DIR / "cleaned_for_rvc"
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_SR = 48000
EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

# 80 Hz high-pass filter to strip desk thumps and rumble
sos_highpass = butter(2, 80, btype="highpass", fs=TARGET_SR, output="sos")

audio_files = [f for f in INPUT_DIR.iterdir() if f.suffix.lower() in EXTENSIONS]

if not audio_files:
    print(f"No audio files found in {INPUT_DIR.resolve()}")
    exit()

print(f"Cleaning {len(audio_files)} files...")

for idx, file_path in enumerate(audio_files, start=1):
    print(f"[{idx}/{len(audio_files)}] Denoising: {file_path.name}")
    data, sr = sf.read(file_path)
    
    # Mono conversion
    if data.ndim > 1:
        data = np.mean(data, axis=1)
        
    # Resample to 48 kHz
    if sr != TARGET_SR:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(TARGET_SR, sr)
        data = resample_poly(data, TARGET_SR // g, sr // g)
        sr = TARGET_SR

    data = sosfilt(sos_highpass, data)

    # Clean stationary background hiss / fans
    cleaned = nr.reduce_noise(
        y=data,
        sr=sr,
        prop_decrease=0.85,
        stationary=True,
        n_fft=1024
    )

    out_file = OUTPUT_DIR / f"{file_path.stem}_cleaned.wav"
    sf.write(out_file, cleaned.astype(np.float32), samplerate=TARGET_SR, subtype="PCM_16")

print(f"\nCleaned files saved to: {OUTPUT_DIR.resolve()}")