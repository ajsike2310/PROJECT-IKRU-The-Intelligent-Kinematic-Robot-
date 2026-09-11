"""
Generate Expressive Audio Samples using Chatterbox TTS
=====================================================
Generates high-quality, expressive WAV files demonstrating authentic human-like
paralinguistic vocal sounds:
- [laughter] - Hearty laugh
- [giggle]   - Playful chuckle
- [sigh]     - Relieved/dramatic sigh
- [clear_throat] - Thoughtful throat clear
- [gasp]     - Startled gasp
- [cry]      - Sympathetic tearful sound
- [whisper]  - Conspiratorial quiet whisper

All files are saved to tests/audio/output/ as 44.1kHz 16-bit Stereo PCM WAV.
"""

import os
import sys
import time
from pathlib import Path

# Add project root and software dir to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SOFTWARE_DIR = ROOT_DIR / "software"
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import soundfile as sf
import winsound
import torch
from chatterbox.tts import ChatterboxTTS
from scipy.signal import resample_poly
import math

from ikru.audio import AudioService

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLES = [
    (
        "expressive_1_giggle.wav",
        "Playful Chuckle / Giggle",
        "Hi there! Ikru here [giggle], have you got a minute to chat about our robotics project?"
    ),
    (
        "expressive_2_laughter.wav",
        "Hearty Human Laugh",
        "Wait, you actually thought I couldn't see you? [laughter] That's hilarious!"
    ),
    (
        "expressive_3_sigh.wav",
        "Relief / Deep Sigh",
        "Whew, I just finished exploring the whole living room [sigh]. My motors need a recharge."
    ),
    (
        "expressive_4_clear_throat.wav",
        "Thoughtful / Throat Clearing",
        "Hold on, let me compute the trajectory... [clear_throat] Okay, path is clear, moving forward now!"
    ),
    (
        "expressive_5_gasp.wav",
        "Surprise / Dramatic Gasp",
        "Look over there! [gasp] Did you see how fast that was?"
    ),
    (
        "expressive_6_cry.wav",
        "Sympathetic / Sad Cry",
        "Oh no... [cry] That is really heartbreaking. I am here for you, friend."
    ),
    (
        "expressive_7_whisper.wav",
        "Quiet Whisper",
        "Come closer... [whisper] I discovered where they hid the extra potato batteries."
    )
]

def main():
    print("=" * 65)
    print(" PROJECT IKRU — Generating Expressive Audio Showcase")
    print("=" * 65)

    # Initialize AudioService with PC playback disabled so we can play individually
    svc = AudioService(play_pc=False, port=8001)  # Use port 8001 to avoid conflicting with main.py on 8000
    print(f"[*] AudioService ready (device: {svc.device})\n")

    results = []
    for filename, label, text in SAMPLES:
        out_path = OUTPUT_DIR / filename
        print(f"--> [{label}]")
        print(f"    Text: \"{text}\"")
        t_gen = time.time()

        try:
            # Synthesize through AudioService
            url = svc.synthesize(text, play_pc=False)
            if url and os.path.exists(svc.wav_path):
                # Copy generated 44.1kHz stereo WAV to output directory
                import shutil
                shutil.copy2(svc.wav_path, str(out_path))
                duration = svc.last_duration
                gen_time = time.time() - t_gen
                print(f"    [+] Generated in {gen_time:.2f}s | Duration: {duration:.2f}s -> {filename}")
                results.append((label, str(out_path), duration))

                # Play sample on PC speaker
                try:
                    winsound.PlaySound(str(out_path), winsound.SND_FILENAME)
                except Exception as pe:
                    print(f"    [!] PC playback error: {pe}")
            else:
                print(f"    [!] Failed to synthesize {filename}")

        except Exception as e:
            print(f"    [!] Error generating {filename}: {e}")

    svc.stop()

    print("\n" + "=" * 65)
    print(f" [OK] Successfully generated {len(results)} expressive audio files!")
    print(f" Saved to: {OUTPUT_DIR}")
    for lbl, pth, dur in results:
        print(f"   - {lbl} ({dur:.2f}s): {Path(pth).name}")
    print("=" * 65)

if __name__ == "__main__":
    main()
