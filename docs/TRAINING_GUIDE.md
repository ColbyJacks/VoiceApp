# 🧠 Voice Training Studio & Dataset Pipeline Guide

**Voice Trainer Studio** (`voice_trainer_studio.py`) provides an autonomous end-to-end workflow to build custom RVC v2 AI voice models from YouTube videos or local audio recordings.

---

## 🔄 End-to-End Training Pipeline

```
[ YouTube URL or Search Query ]
             │ (yt-dlp stream extraction)
             ▼
[ High-Bitrate Raw Audio (.wav) ]
             │ (Spectral Denoising: noisereduce + Butterworth Filter)
             ▼
[ Cleaned Studio Vocal Track ]
             │ (Audio Slicing & Resampling to 48kHz / 16kHz)
             ▼
[ Sliced Dataset: logs/<ModelName>/sliced_audios/ ]
             │
             ├──► [ HuBERT Feature Extraction -> logs/<ModelName>/v2_extracted/ ]
             └──► [ RMVPE Pitch Extraction   -> logs/<ModelName>/f0/ & f0f/ ]
             │
             ▼
[ PyTorch RVC v2 Neural Network Training ]
  - Epoch Iterations (e.g. 50 - 200 epochs)
  - Generator / Discriminator Loss Optimization
  - Target Sample Rate: 48,000 Hz
             │
             ▼
[ Model Export & FAISS Index Creation ]
  - Exported Weights: models/<ModelName>.pth
  - Speaker Index:    models/<ModelName>.index
             │
             ▼
[ 1-Click Voice Audition Tester ]
  - Built-in audio playback with pitch shifting (-12 to +12 semitones)
```

---

## 🛠️ Step-by-Step Training Walkthrough

### Step 1: Ingesting Audio from YouTube
1. Launch **Voice Trainer Studio**:
   ```powershell
   python voice_trainer_studio.py
   ```
2. Enter a **YouTube Search Query** (e.g., `"Narrator interview long clip clean speech"`) or paste a direct **YouTube URL**.
3. Click **"Search YouTube"** to review the top results (title, uploader, duration, view count).
4. Select your preferred result and click **"Download Audio"**.
5. The high-quality audio stream will be saved automatically to `raw_recordings/`.

---

### Step 2: AI Vocal Cleaning & Denoising
1. Select the raw recording in the trainer.
2. Enable **"AI Spectral Denoising"**:
   - The cleaner uses non-stationary spectral gating to remove room reverb, fan noise, microphone hum, and background hiss without muffling vocal clarity.
3. The cleaned audio is exported to `cleaned_for_rvc/`.

---

### Step 3: Dataset Slicing & Feature Extraction
1. Enter your desired **Model Name** (e.g., `MyCustomVoice`).
2. Click **"Process Dataset & Extract Features"**:
   - **Audio Slicer**: Splits the audio file into small, clean segments (3 to 4 seconds) suited for neural training.
   - **HuBERT Extraction**: Computes linguistic representations across 16kHz channels.
   - **RMVPE Pitch Extraction**: Analyzes melody and pitch contours across all sliced samples.

---

### Step 4: Model Training
Configure training hyperparameters:
- **Total Epochs**:
  - `50 - 100 epochs`: Fast preview (5–10 minutes on modern GPUs).
  - `150 - 300 epochs`: Production quality with clear phoneme recreation and natural timbre.
- **Batch Size**:
  - `4 - 8`: GPUs with 6GB–8GB VRAM.
  - `12 - 16`: GPUs with 12GB+ VRAM.
- **Target Sample Rate**: `48k` (recommended for crystal-clear fidelity).
- **Pitch Guidance (f0)**: Enabled (`True`).
- **Pitch Algorithm**: `rmvpe`.

Click **"Start Model Training"**. The progress bar and loss metrics will update in real time.

---

### Step 5: Index Creation & Automatic Export
When training completes:
1. The trained weights are compiled into `models/<ModelName>.pth`.
2. A FAISS feature retrieval index is generated at `models/<ModelName>.index`.
3. The model is immediately available in **Voice Modulator Studio Pro** for real-time live usage.

---

### Step 6: 1-Click Voice Audition Tester
Before going live, test your trained model directly in the studio:
1. Under **"Voice Model Tester"**, select your newly trained model.
2. Choose a test speech sample or record a quick audio clip.
3. Adjust the audition pitch slider and click **"Run Conversion Test"**.
4. Listen to the converted audio output directly in the player.

---

## 💡 Best Practices for High-Quality Voice Models

| Factor | Recommendation | Why |
| :--- | :--- | :--- |
| **Dataset Length** | 5 – 15 minutes of clean speech | Provides enough phonetic variation without overfitting. |
| **Background Noise** | Zero background music or loud sound effects | Background music confuses the HuBERT feature extractor and introduces artifacts. |
| **Speaking Style** | Natural conversation with dynamic pitch range | Allows the model to generalize well across different speaking tones. |
| **Epoch Count** | Stop when validation loss plateaus (usually 150–250 epochs) | Prevents robotic vocal artifacts caused by overtraining. |
