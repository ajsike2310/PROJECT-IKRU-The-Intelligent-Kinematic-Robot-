"""
IKRU Audio Service
Manages natural text-to-speech synthesis (Chatterbox-Nano / Edge-TTS)
and local HTTP audio streaming to the ESP32 MAX98357A I2S audio receiver.
"""

import asyncio
import http.server
import math
import os
import re
import socket
import socketserver
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

# Default reference voice path for Chatterbox voice cloning
DEFAULT_REF_VOICE = Path(__file__).resolve().parent / "voices" / "ikru_voice.wav"
FALLBACK_REF_VOICE = Path(__file__).resolve().parents[3] / "tests" / "audio" / "ikru_voice.wav"


class AudioService:
    def __init__(
        self,
        host_ip: Optional[str] = None,
        port: int = 8000,
        engine: str = "chatterbox",  # "chatterbox" or "edge"
        ref_audio_path: Optional[str] = None,
        edge_voice: str = "en-US-GuyNeural",
        device: str = "auto",
        cache_dir: Optional[str] = None,
    ):
        self.port = port
        self.engine = engine.lower()
        self.edge_voice = edge_voice
        self.device = device
        self.cache_dir = cache_dir or tempfile.gettempdir()
        self.wav_filename = "ikru_speech.wav"
        self.wav_path = os.path.join(self.cache_dir, self.wav_filename)
        self.host_ip = host_ip or self._detect_local_ip()

        # Locate reference audio for voice cloning
        if ref_audio_path and os.path.exists(ref_audio_path):
            self.ref_audio_path = str(ref_audio_path)
        elif DEFAULT_REF_VOICE.exists():
            self.ref_audio_path = str(DEFAULT_REF_VOICE)
        elif FALLBACK_REF_VOICE.exists():
            self.ref_audio_path = str(FALLBACK_REF_VOICE)
        else:
            self.ref_audio_path = None

        self._server: Optional[socketserver.TCPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self.last_duration: float = 0.0

        # Chatterbox-Nano model instance
        self._chatterbox_model = None

        if self.engine == "chatterbox":
            self._init_chatterbox()

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

    def _init_chatterbox(self):
        """Initializes Chatterbox-Nano and pre-caches the reference voice embedding."""
        try:
            import torch
            from chatterbox.tts_turbo import ChatterboxTurboTTS

            if self.device == "auto":
                target_device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                target_device = self.device

            print(f"[AudioService] Loading Chatterbox-Nano TTS on {target_device}...")
            t0 = time.time()
            self._chatterbox_model = ChatterboxTurboTTS.from_pretrained(device=target_device, nano=True)
            print(f"[AudioService] Chatterbox-Nano loaded in {time.time() - t0:.2f}s")

            # Pre-compute and cache reference voice conditionals
            if self.ref_audio_path and os.path.exists(self.ref_audio_path):
                print(f"[AudioService] Caching reference voice profile from: {Path(self.ref_audio_path).name}")
                self._chatterbox_model.prepare_conditionals(self.ref_audio_path)
                print(f"[AudioService] Voice profile active as primary IKRU voice.")
            else:
                print("[AudioService] No reference clip found; using default Chatterbox voice.")

        except Exception as e:
            print(f"[AudioService] Warning: Could not initialize Chatterbox-Nano ({e}). Falling back to Edge-TTS.")
            self.engine = "edge"
            self._chatterbox_model = None

    def _start_server(self):
        """Starts the background HTTP server serving audio files."""
        service_self = self

        class AudioHTTPHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=service_self.cache_dir, **kwargs)

            def log_message(self, format, *args):
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

    def _clean_text_for_tts(self, text: str) -> str:
        """
        Cleans and normalizes text for natural TTS output:
        1. Fixes pronunciation of 'Ikru': converts all-caps 'IKRU' or 'I.K.R.U.'
           to 'Ikru' so the tokenizer pronounces it as a unified word ('Ik-roo')
           rather than spelling out each letter individually.
        2. Strips OLED facial emotion tags ([happy], [worried], [focused], etc.)
           while preserving Chatterbox voice tags ([chuckle], [laugh], [sigh], [gasp], [clear throat]).
        """
        # Fix letter-by-letter acronym pronunciation
        text = re.sub(r'\bI[Kk][Rr][Uu]\b', 'Ikru', text)
        text = re.sub(r'\bI\.K\.R\.U\.\b', 'Ikru', text)
        text = re.sub(r'\bi-k-r-u\b', 'Ikru', text, flags=re.IGNORECASE)

        # Strip OLED eye emotion tags (keep paralinguistic voice sound tags)
        oled_tags = (
            "normal|happy|glee|sad|worried|focused|annoyed|surprised|"
            "skeptic|frustrated|unimpressed|sleepy|suspicious|squint|"
            "angry|furious|scared|awe"
        )
        text = re.sub(r'\[' + oled_tags + r'\]', '', text, flags=re.IGNORECASE)

        # Clean excess spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def synthesize(self, text: str) -> Optional[str]:
        """
        Synthesizes text into 44.1kHz 16-bit Stereo PCM WAV.
        Primary: Chatterbox-Nano with cloned voice.
        Fallback: Edge-TTS.
        Returns the HTTP stream URL, or None on failure.
        """
        if not text or not text.strip():
            return None

        clean_text = self._clean_text_for_tts(text)
        if not clean_text:
            return None

        with self._lock:
            # 1. Primary: Chatterbox-Nano
            if self.engine == "chatterbox" and self._chatterbox_model is not None:
                try:
                    # Model conditionals were pre-cached during init, so generate() uses cloned voice
                    wav_tensor = self._chatterbox_model.generate(clean_text)

                    # Extract to NumPy float32
                    data = wav_tensor.detach().cpu().squeeze().numpy().astype(np.float32)
                    sr = self._chatterbox_model.sr
                    return self._save_resampled_wav(data, sr)
                except Exception as e:
                    print(f"[AudioService] Chatterbox synthesis error ({e}). Trying fallback...")

            # 2. Fallback: Edge-TTS
            return self._synthesize_edge_tts(clean_text)

    def _save_resampled_wav(self, data: np.ndarray, sample_rate: int) -> Optional[str]:
        """Resamples audio data to 44.1kHz 16-bit stereo PCM WAV and writes to cache."""
        target_rate = 44100

        if sample_rate != target_rate:
            g = math.gcd(target_rate, sample_rate)
            up = target_rate // g
            down = sample_rate // g
            data = resample_poly(data, up, down)

        # Convert to 2-channel stereo
        if data.ndim == 1:
            stereo_data = np.column_stack((data, data))
        else:
            stereo_data = data

        self.last_duration = float(len(data) / target_rate)
        sf.write(self.wav_path, stereo_data, target_rate, subtype="PCM_16")

        return f"http://{self.host_ip}:{self.port}/{self.wav_filename}?t={int(time.time()*1000)}"

    def _synthesize_edge_tts(self, clean_text: str) -> Optional[str]:
        """Edge-TTS synthesis helper."""
        import edge_tts
        mp3_path = os.path.join(self.cache_dir, f"temp_{int(time.time()*1000)}.mp3")

        async def _generate():
            communicate = edge_tts.Communicate(clean_text, self.edge_voice)
            await communicate.save(mp3_path)

        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(_generate(), loop)
                future.result(timeout=15)
            else:
                loop.run_until_complete(_generate())

            data, sr = sf.read(mp3_path)
            if os.path.exists(mp3_path):
                os.remove(mp3_path)

            return self._save_resampled_wav(data, sr)
        except Exception as e:
            print(f"[AudioService] Edge-TTS error: {e}")
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
