"""
TTS Comparison & Expressiveness Test Suite for PROJECT IKRU
============================================================
Evaluates speech quality, emotional expressiveness, paralinguistic tags,
and accents across different modern TTS engines:

1. Chatterbox-Nano (Resemble AI)
   - 110M lightweight model
   - Paralinguistic tags: [chuckle], [laugh], [sigh], [gasp], [yawn], [cough], etc.
   - Zero-shot voice cloning support with reference clip

2. Edge-TTS (Microsoft Neural Voices)
   - Zero GPU load, streaming HTTP
   - Multiple regional accents: US, British, Australian, Indian
   - Expressive tones: Guy, Jenny, Ana (animated/playful), Ryan, etc.

Usage:
------
Run full test suite:
  python tests/audio/test_tts_comparison.py

Test only Chatterbox-Nano:
  python tests/audio/test_tts_comparison.py --engine chatterbox

Test only Edge-TTS accents:
  python tests/audio/test_tts_comparison.py --engine edge

Clone voice with Chatterbox-Nano using reference WAV:
  python tests/audio/test_tts_comparison.py --engine chatterbox --ref-clip path/to/voice.wav

Stream test audio directly to IKRU robot over WiFi:
  python tests/audio/test_tts_comparison.py --stream-to-robot --robot-ip 192.168.1.40
"""

import os
import sys
import time
import argparse
import asyncio
from pathlib import Path

# Optional Windows native sound playback
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================================
# Audio Playback Helpers
# =====================================================================
def play_audio_file(file_path: str):
    """Plays audio file on the local PC speaker (Windows native)."""
    if HAS_WINSOUND and os.name == "nt":
        try:
            print(f"  [Playing on PC audio device: {Path(file_path).name}]...")
            winsound.PlaySound(str(file_path), winsound.SND_FILENAME)
        except Exception as e:
            print(f"  [Could not play audio natively: {e}]")
    else:
        print(f"  [Saved audio to: {file_path}]")


# =====================================================================
# 1. Chatterbox-Nano TTS Evaluation
# =====================================================================
def test_chatterbox_nano(device: str = "auto", ref_clip: str = None, play_audio: bool = True):
    """
    Tests Chatterbox-Nano with paralinguistic emotional tags:
    [chuckle], [laugh], [sigh], [gasp], [yawn], [clear throat]
    """
    print("\n" + "="*65)
    print(" 1. CHATTERBOX-NANO (Resemble AI) - Expressiveness Test")
    print("="*65)

    try:
        import torch
        import torchaudio as ta
        from chatterbox.tts_turbo import ChatterboxTurboTTS
    except ImportError as e:
        print("\n[!] Chatterbox-TTS or PyTorch is not currently installed.")
        print("    To install Chatterbox-Nano:")
        print("      pip install chatterbox-tts")
        print("    For GPU acceleration with PyTorch CUDA:")
        print("      pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126")
        print(f"    Details: {e}")
        return []

    # Device selection
    if device == "auto":
        target_device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        target_device = device

    print(f"[*] Loading Chatterbox-Nano model on device: {target_device} (nano=True)...")
    t0 = time.time()
    try:
        model = ChatterboxTurboTTS.from_pretrained(device=target_device, nano=True)
    except Exception as e:
        print(f"[!] Error loading Chatterbox-Nano: {e}")
        return []
    print(f"[+] Model loaded in {time.time() - t0:.2f}s")

    test_prompts = [
        (
            "chatterbox_1_chuckle.wav",
            "Friendly / Chuckle",
            "Hi there! IKRU here [chuckle], have you got one minute to chat about our robotics project?"
        ),
        (
            "chatterbox_2_laugh.wav",
            "Amused / Laugh",
            "Wait, you actually thought I couldn't see you? [laugh] That's hilarious!"
        ),
        (
            "chatterbox_3_sigh.wav",
            "Relief / Sigh",
            "Whew, I just finished exploring the whole living room [sigh]. My motors need a quick recharge."
        ),
        (
            "chatterbox_4_gasp.wav",
            "Surprise / Gasp",
            "Look over there! [gasp] Did you see how fast that was?"
        ),
        (
            "chatterbox_5_robot_tag.wav",
            "Conversational Robot",
            "Hold on, let me compute the trajectory... [clear throat] Okay, path is clear, moving forward now!"
        )
    ]

    generated_files = []

    for filename, label, text in test_prompts:
        out_path = str(OUTPUT_DIR / filename)
        print(f"\n--> Test Case: {label}")
        print(f"    Text: \"{text}\"")
        t_start = time.time()

        try:
            if ref_clip and os.path.exists(ref_clip):
                print(f"    Reference Audio: {ref_clip}")
                wav = model.generate(text, audio_prompt_path=ref_clip)
            else:
                wav = model.generate(text)

            ta.save(out_path, wav, model.sr)
            gen_time = time.time() - t_start
            print(f"    Generated in {gen_time:.2f}s -> {filename}")
            generated_files.append((label, out_path))

            if play_audio:
                play_audio_file(out_path)

        except Exception as e:
            print(f"    [!] Generation error: {e}")

    return generated_files


# =====================================================================
# 2. Edge-TTS Evaluation (Accents & Expressiveness)
# =====================================================================
async def _generate_edge_tts(text: str, voice: str, out_path: str, rate: str = "+0%", pitch: str = "+0Hz"):
    """Helper to synthesize audio using edge-tts."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def test_edge_tts_accents(play_audio: bool = True):
    """
    Tests Edge-TTS with various regional accents and expressive character voices:
    - US Male (Guy - natural desk companion)
    - US Female (Jenny - warm, conversational)
    - US Playful (Ana - cute/robot expressive)
    - UK British (Ryan - crisp British accent)
    - Australian (Natasha - Aussie accent)
    - Indian (Prabhat - Indian English accent)
    """
    print("\n" + "="*65)
    print(" 2. EDGE-TTS - Regional Accents & Expressive Neural Voices")
    print("="*65)

    try:
        import edge_tts
    except ImportError:
        print("[!] edge-tts is not installed. Run: pip install edge-tts")
        return []

    voices_to_test = [
        (
            "edge_us_guy.wav",
            "en-US-GuyNeural",
            "US Male (Default IKRU)",
            "Hello there! I'm IKRU, your kinematic desk robot. All systems are operational and ready for your command.",
            "+0%", "+0Hz"
        ),
        (
            "edge_us_jenny.wav",
            "en-US-JennyNeural",
            "US Female (Warm Conversational)",
            "Hi friend! It's so good to see you today. What exciting things are we going to build together?",
            "+0%", "+0Hz"
        ),
        (
            "edge_us_ana.wav",
            "en-US-AnaNeural",
            "US Animated / Playful Character",
            "Yay, let's explore! I see something colorful on your desk, should I drive closer and take a look?",
            "+5%", "+8Hz"
        ),
        (
            "edge_uk_ryan.wav",
            "en-GB-RyanNeural",
            "British English (Refined)",
            "Good day! I've conducted a quick scan of the environment. Everything appears to be in proper order, sir.",
            "-2%", "+0Hz"
        ),
        (
            "edge_au_natasha.wav",
            "en-AU-NatashaNeural",
            "Australian English (Friendly Aussie)",
            "G'day! Ready to roll around and check out the workshop today? Let's have a look!",
            "+0%", "+0Hz"
        ),
        (
            "edge_in_prabhat.wav",
            "en-IN-PrabhatNeural",
            "Indian English (Clear & Expressive)",
            "Namaste! The camera feed and motor controls are connected. Tell me where you would like me to move.",
            "+0%", "+0Hz"
        ),
    ]

    generated_files = []

    for filename, voice, label, text, rate, pitch in voices_to_test:
        out_path = str(OUTPUT_DIR / filename)
        print(f"\n--> Voice: {label} [{voice}]")
        print(f"    Text: \"{text}\"")
        t_start = time.time()

        try:
            asyncio.run(_generate_edge_tts(text, voice, out_path, rate=rate, pitch=pitch))
            gen_time = time.time() - t_start
            print(f"    Generated in {gen_time:.2f}s -> {filename}")
            generated_files.append((label, out_path))

            if play_audio:
                play_audio_file(out_path)

        except Exception as e:
            print(f"    [!] Generation error: {e}")

    return generated_files


# =====================================================================
# 3. Optional Robot Streamer (Stream any generated WAV to IKRU I2S)
# =====================================================================
def stream_file_to_ikru(file_path: str, robot_ip: str = "192.168.1.40", port: int = 8000):
    """
    Streams a test WAV file to the IKRU ESP32 over WiFi so you can hear it on
    the actual MAX98357A I2S robot speaker!
    """
    import socket
    import http.server
    import threading
    import websocket
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd

    print(f"\n[*] Preparing to stream {Path(file_path).name} to IKRU on {robot_ip}...")

    # Resample to 44.1kHz 16-bit stereo PCM
    data, sr = sf.read(file_path)
    target_rate = 44100
    if sr != target_rate:
        g = gcd(sr, target_rate)
        up = target_rate // g
        down = sr // g
        data = resample_poly(data, up, down)

    if len(data.shape) == 1:
        import numpy as np
        stereo_data = np.column_stack((data, data))
    else:
        stereo_data = data

    stream_path = OUTPUT_DIR / "robot_stream_test.wav"
    sf.write(str(stream_path), stereo_data, target_rate, subtype="PCM_16")

    # Find local IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()

    # Serve file temporarily
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(OUTPUT_DIR), **kwargs)

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    url = f"http://{local_ip}:{port}/robot_stream_test.wav"
    print(f"[*] Hosting stream at {url}")

    # Send SPEAK_URL to ESP32
    try:
        ws = websocket.create_connection(f"ws://{robot_ip}:81", timeout=3.0)
        print(f"[*] Connected to robot WebSocket. Sending SPEAK_URL...")
        ws.send(f"SPEAK_URL:{url}")
        ws.close()
        print(f"[+] Audio dispatched to IKRU speaker! Listen to your robot.")
        time.sleep(5.0)
    except Exception as e:
        print(f"[!] Could not connect to robot on ws://{robot_ip}:81 ({e})")
    finally:
        server.shutdown()


# =====================================================================
# Main CLI Entry Point
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="IKRU TTS Comparison & Expressiveness Test Suite")
    parser.add_argument("--engine", choices=["all", "chatterbox", "edge"], default="all",
                        help="Which TTS engine(s) to test (default: all)")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"],
                        help="Inference device for Chatterbox (default: auto)")
    parser.add_argument("--ref-clip", default=None,
                        help="Optional reference WAV audio clip for Chatterbox voice cloning")
    parser.add_argument("--no-play", action="store_true",
                        help="Do not play audio through PC speakers automatically")
    parser.add_argument("--stream-to-robot", action="store_true",
                        help="Also stream the sample to IKRU robot over WiFi")
    parser.add_argument("--robot-ip", default="192.168.1.40",
                        help="ESP32 Robot IP address (default: 192.168.1.40)")

    args = parser.parse_args()

    print("="*65)
    print(" PROJECT IKRU - TTS EXPRESSIVENESS & ACCENT EVALUATION SUITE")
    print("="*65)
    print(f" Output Directory: {OUTPUT_DIR}")
    print(f" Selected Engine:  {args.engine.upper()}")
    print(f" Auto-Play Audio:  {not args.no_play}")
    if args.ref_clip:
        print(f" Reference Clip:   {args.ref_clip}")

    all_generated = []

    # 1. Edge-TTS
    if args.engine in ["all", "edge"]:
        edge_results = test_edge_tts_accents(play_audio=not args.no_play)
        all_generated.extend(edge_results)

    # 2. Chatterbox-Nano
    if args.engine in ["all", "chatterbox"]:
        chatterbox_results = test_chatterbox_nano(
            device=args.device,
            ref_clip=args.ref_clip,
            play_audio=not args.no_play
        )
        all_generated.extend(chatterbox_results)

    # Summary
    print("\n" + "="*65)
    print(" EVALUATION COMPLETE - GENERATED SAMPLES")
    print("="*65)
    for idx, (label, path) in enumerate(all_generated, 1):
        print(f"  {idx:2d}. {label:<35} -> {Path(path).name}")

    print(f"\nAll audio files are saved in:\n  {OUTPUT_DIR}")

    # Optional stream to robot
    if args.stream_to_robot and all_generated:
        sample_path = all_generated[0][1]
        stream_file_to_ikru(sample_path, robot_ip=args.robot_ip)


if __name__ == "__main__":
    main()
