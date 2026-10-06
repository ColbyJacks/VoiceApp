# 🎙️ Voice Modulator Studio Pro User Guide

**Voice Modulator Studio Pro** (`voice_tray_app.py`) is a real-time desktop AI voice changer that routes your microphone through custom RVC voice models and studio DSP effects with instantaneous hotkey switching.

---

## 🖥️ UI Layout Overview

The studio application features a modern dual-column interface designed for live streaming, gaming, and recording.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🎙️ VOICE MODULATOR STUDIO PRO                                              │
│ [🟢 ACTIVE] Model: MyCustomVoice.pth | Mode: MODULATED AI | In: HyperX ... │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ 🎛️ AUDIO ROUTING & GAIN              │ 🎭 VOICE MODEL & FX RACK             │
│                                      │                                      │
│  Input Microphone:                   │  Selected Voice Model:               │
│  [ [1] Microphone (HyperX)     ▼ ]   │  [ MyCustomVoice.pth             ▼ ] │
│  Mic Input Gain (Boost): [1.25x]     │                                      │
│                                      │  Pitch Shift (Semitones): [+0]       │
│  Output Device (Virtual Mic):        │  [-24] ───────────●─────────── [+24] │
│  [ [44] CABLE Input (VB-Audio) ▼ ]   │                                      │
│  Output Volume Boost:    [1.50x]     │  Index Retrieval Rate:   [0.75]      │
│                                      │  [0.0] ─────────────●───────── [1.0] │
│  🎧 Ear Monitor (Hear Myself): [ON]  │                                      │
│  Monitor Device:                     │  Volume Envelope Mix:    [1.00]      │
│  [ [2] Headphones (Realtek)    ▼ ]   │                                      │
│  Ear Monitor Volume:     [0.80x]     │  🎚️ DSP Effects Rack:                 │
│                                      │  [✓] Reverb     Room [0.5] Wet [0.3] │
│  📊 Live VU Meters:                  │  [ ] Delay      Time [0.35] Fbk[0.3] │
│  MIC IN : [████████████░░░░░░] -12dB │  [ ] Chorus     Depth[0.3] Rate[1.2] │
│  AI OUT : [████████████████░░] -3dB  │  [ ] Radio EQ   (Walkie-Talkie Mode) │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ [ ⚡ START ENGINE ]   [ 🎭 TOGGLE BYPASS (F8) ]   [ 🔇 MUTE MIC (F7) ]      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ⌨️ Global Hotkeys

Global hotkeys work anywhere in Windows — even while full-screen in games (Discord, VRChat, Counter-Strike, Valorant, Call of Duty, etc.):

| Hotkey | Action | Behavior |
| :--- | :--- | :--- |
| **`F8`** | **Toggle Bypass / Modulate** | Switches instantly between **Modulated AI Voice** and your **Natural Real Voice**. |
| **`F7`** | **Toggle Microphone Mute** | Mutes all audio output instantly. |

---

## 🎧 Ear Monitoring (Hear Myself)

Ear monitoring sends a real-time copy of your converted voice directly to your headphones without affecting the virtual microphone output being sent to Discord or your game:

1. Check the **"Hear Myself"** checkbox.
2. Select your physical **Headphones / Audio Interface** in the dropdown.
3. Adjust the **Ear Monitor Volume** slider so you can comfortably hear your own vocal delivery without feedback.

---

## 🔊 Routing to Discord, OBS, and Games

To speak with your modulated voice in any app:

### 1. Configure the Voice Modulator
- **Input Microphone**: Select your physical microphone.
- **Output Device**: Select `CABLE Input (VB-Audio Virtual Cable)`.

### 2. Configure Discord
1. Open **Discord Settings** ➡️ **Voice & Video**.
2. Set **Input Device** to `CABLE Output (VB-Audio Virtual Cable)`.
3. Set **Output Device** to your normal headphones.
4. Set **Input Sensitivity** to "Automatically determine" (or set manual threshold to `-60 dB`).
5. Disable "Echo Cancellation" and "Noise Suppression (Krisp)" in Discord if it cuts off the AI voice harmonics.

### 3. Configure OBS Studio
1. In OBS, go to **Settings** ➡️ **Audio**.
2. Set **Mic/Auxiliary Audio** to `CABLE Output (VB-Audio Virtual Cable)`.

---

## 🎚️ Parameter Explanations

- **Pitch Shift (Semitones)**:
  - `0`: Unchanged pitch (same pitch as your natural voice).
  - `+12`: Shift up 1 octave (useful when converting male $\to$ female voice).
  - `-12`: Shift down 1 octave (useful when converting female $\to$ male voice).
- **Index Retrieval Rate ($0.0 \to 1.0$)**:
  - Controls how much of the target speaker's dataset timbre and accent from the `.index` file is blended into the output. Recommended: `0.65 - 0.85`.
- **Output Volume Boost ($0.5\text{x} \to 3.0\text{x}$)**:
  - Amplifies the converted voice to ensure you are heard loud and clear in team voice chats. The built-in `-0.5 dB` limiter ensures your audio never clips or distorts.
- **Volume Envelope ($0.0 \to 1.0$)**:
  - Blends the dynamic loudness envelope of your original microphone into the synthesized voice. `1.0` produces the cleanest, most natural output.

---

## 🪟 System Tray Mode

- Closing or minimizing the application window keeps it running quietly in the background.
- Left-click the system tray icon to restore the window.
- Right-click the tray icon to quickly toggle **Bypass Mode**, **Mute**, or **Quit**.
