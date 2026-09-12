"""
IKRU Natural Voice Test Audio Server
Generates natural voice TTS via edge-tts, converts to 44.1kHz 16-bit Stereo PCM WAV,
and serves it on HTTP port 8000 for ESP32 I2S streaming.
"""

import asyncio
import http.server
import os
import socketserver
import threading
import time
import edge_tts
import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
MP3_PATH = os.path.join(DIRECTORY, "test.mp3")
WAV_PATH = os.path.join(DIRECTORY, "test.wav")

DEFAULT_TEXT = (
    "Hello! I am IKRU, your intelligent kinematic robot companion. "
    "My natural voice streaming is now active and working properly through the I2S speaker!"
)
VOICE = "en-US-GuyNeural"  # Natural male voice (or "en-US-JennyNeural" / "en-US-AnaNeural")


async def generate_speech(text: str = DEFAULT_TEXT, voice: str = VOICE):
    """Synthesize speech using edge-tts and convert to stereo 44.1kHz 16-bit WAV."""
    print(f"[TTS] Synthesizing speech with voice '{voice}'...")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(MP3_PATH)
    print(f"[TTS] Saved temporary MP3 to {MP3_PATH}")

    print("[Audio] Converting to 44.1kHz 16-bit stereo PCM WAV...")
    data, sample_rate = sf.read(MP3_PATH)

    # Resample to 44100 Hz if needed
    target_rate = 44100
    if sample_rate != target_rate:
        # edge-tts defaults to 24000 Hz. 44100 / 24000 = 147 / 80
        from math import gcd
        g = gcd(target_rate, sample_rate)
        up = target_rate // g
        down = sample_rate // g
        data = resample_poly(data, up, down)

    # Ensure stereo (2 channels)
    if data.ndim == 1:
        stereo_data = np.column_stack((data, data))
    else:
        stereo_data = data

    sf.write(WAV_PATH, stereo_data, target_rate, subtype="PCM_16")
    file_size = os.path.getsize(WAV_PATH)
    print(f"[Audio] Generated WAV: {WAV_PATH} ({file_size} bytes, 44100 Hz, stereo, 16-bit)")


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        print(f"[HTTP {time.strftime('%H:%M:%S')}] {args[0]} - Status: {args[1]}")


def run_server():
    server = socketserver.TCPServer(("", PORT), CustomHTTPRequestHandler)
    server.allow_reuse_address = True
    print(f"\n[HTTP Server] Listening on http://0.0.0.0:{PORT}")
    print(f"[HTTP Server] Serving {WAV_PATH} at http://192.168.1.33:{PORT}/test.wav\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    asyncio.run(generate_speech())
    run_server()
