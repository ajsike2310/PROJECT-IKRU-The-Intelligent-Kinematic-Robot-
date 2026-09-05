"""
IKRU Audio Service
Manages natural text-to-speech synthesis (edge-tts) and local HTTP audio streaming
to the ESP32 MAX98357A I2S audio receiver.
"""

import asyncio
import http.server
import math
import os
import socket
import socketserver
import tempfile
import threading
import time
from typing import Optional

import edge_tts
import numpy as np
from scipy.signal import resample_poly
import soundfile as sf


class AudioService:
    def __init__(
        self,
        host_ip: Optional[str] = None,
        port: int = 8000,
        voice: str = "en-US-GuyNeural",
        cache_dir: Optional[str] = None,
    ):
        self.port = port
        self.voice = voice
        self.cache_dir = cache_dir or tempfile.gettempdir()
        self.wav_filename = "ikru_speech.wav"
        self.wav_path = os.path.join(self.cache_dir, self.wav_filename)
        self.host_ip = host_ip or self._detect_local_ip()

        self._server: Optional[socketserver.TCPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False

        self._start_server()

    def _detect_local_ip(self) -> str:
        """Finds the most appropriate local network IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "192.168.1.33"

    def _start_server(self):
        """Starts the background HTTP server serving audio files."""
        service_self = self

        class AudioHTTPHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=service_self.cache_dir, **kwargs)

            def log_message(self, format, *args):
                # Suppress noisy GET logs
                pass

        try:
            self._server = socketserver.TCPServer(("0.0.0.0", self.port), AudioHTTPHandler)
            self._server.allow_reuse_address = True
            self._running = True
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._server_thread.start()
            print(f"[AudioService] HTTP Audio Server running at http://{self.host_ip}:{self.port}/")
        except Exception as e:
            print(f"[AudioService] Failed to start HTTP server on port {self.port}: {e}")

    def synthesize(self, text: str, voice: Optional[str] = None) -> Optional[str]:
        """
        Synthesizes text into 44.1kHz 16-bit Stereo PCM WAV via edge-tts.
        Returns the HTTP URL to stream the audio from, or None on failure.
        """
        if not text or not text.strip():
            return None

        chosen_voice = voice or self.voice
        clean_text = text.strip()

        with self._lock:
            mp3_path = os.path.join(self.cache_dir, f"temp_{int(time.time()*1000)}.mp3")

            async def _generate():
                communicate = edge_tts.Communicate(clean_text, chosen_voice)
                await communicate.save(mp3_path)

            try:
                # Run async TTS generator in event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                if loop.is_running():
                    # If in an already running loop, run in a separate thread
                    future = asyncio.run_coroutine_threadsafe(_generate(), loop)
                    future.result(timeout=15)
                else:
                    loop.run_until_complete(_generate())

                # Load generated MP3 and convert to 44.1kHz 16-bit stereo WAV
                data, sample_rate = sf.read(mp3_path)
                target_rate = 44100

                if sample_rate != target_rate:
                    g = math.gcd(target_rate, sample_rate)
                    up = target_rate // g
                    down = sample_rate // g
                    data = resample_poly(data, up, down)

                # Ensure stereo (2-channel)
                if data.ndim == 1:
                    stereo_data = np.column_stack((data, data))
                else:
                    stereo_data = data

                sf.write(self.wav_path, stereo_data, target_rate, subtype="PCM_16")

                # Clean up temporary mp3
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)

                # Return URL with timestamp cache-buster
                url = f"http://{self.host_ip}:{self.port}/{self.wav_filename}?t={int(time.time()*1000)}"
                return url

            except Exception as e:
                print(f"[AudioService] Error synthesizing speech: {e}")
                if os.path.exists(mp3_path):
                    try:
                        os.remove(mp3_path)
                    except Exception:
                        pass
                return None

    def stop(self):
        """Stops the audio HTTP server."""
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            print("[AudioService] HTTP Audio Server stopped.")
