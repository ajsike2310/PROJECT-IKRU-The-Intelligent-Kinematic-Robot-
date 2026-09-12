"""
IKRU Natural Voice Audio Service
=================================
Expressive speech synthesis for PROJECT IKRU supporting:
1. Chatterbox TTS (Resemble AI):
   - Local neural voice synthesis with rich emotional expressiveness.
   - Native support for inline paralinguistic sound tags:
     [chuckle], [laugh], [sigh], [gasp], [clear throat], [cough], [yawn]
   - Zero-shot voice cloning with custom audio prompt WAV.
   - Multilingual support (23+ languages) via ChatterboxMultilingualTTS.
2. Edge-TTS (Microsoft Neural Voices):
   - Fast online neural voice fallback with regional accents and pitch control.
3. Dual Output:
   - Resampled to 44.1kHz 16-bit Stereo PCM WAV served via HTTP (port 8000) for ESP32 MAX98357A I2S streaming.
   - Optional local PC speaker playback (via Windows winsound).
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
from typing import Optional, Union

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

# Optional PyTorch & Chatterbox TTS
try:
    import torch
    import torchaudio as ta

    # Fix: perth.PerthImplicitWatermarker is None on Windows/CPU because the
    # compiled native binary isn't available. Patch it with DummyWatermarker
    # (same apply_watermark interface, just passes audio through unchanged)
    # before ChatterboxTTS.__init__ tries to call it.
    import perth
    if perth.PerthImplicitWatermarker is None:
        perth.PerthImplicitWatermarker = perth.DummyWatermarker

    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    HAS_CHATTERBOX = True
except Exception as e:
    HAS_CHATTERBOX = False

# Optional Windows native PC audio playback
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# Regional Edge-TTS voice presets for fallback
VOICE_PRESETS = {
    "guy": {
        "voice": "en-US-GuyNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "desc": "US Male (Natural Companion)",
    },
    "jenny": {
        "voice": "en-US-JennyNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "desc": "US Female (Warm Conversational)",
    },
    "ana": {
        "voice": "en-US-AnaNeural",
        "rate": "+5%",
        "pitch": "+8Hz",
        "desc": "US Playful Animated Robot",
    },
    "ryan": {
        "voice": "en-GB-RyanNeural",
        "rate": "-2%",
        "pitch": "+0Hz",
        "desc": "British English Refined",
    },
    "natasha": {
        "voice": "en-AU-NatashaNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "desc": "Australian English Friendly",
    },
    "prabhat": {
        "voice": "en-IN-PrabhatNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "desc": "Indian English Clear",
    },
}

# OLED Eye emotions (to strip from spoken audio so they are not spoken aloud)
OLED_EMOTION_TAGS = (
    "normal|happy|glee|sad|worried|focused|annoyed|surprised|"
    "skeptic|frustrated|unimpressed|sleepy|suspicious|squint|angry|furious|scared|awe"
)


class AudioService:
    def __init__(
        self,
        host_ip: Optional[str] = None,
        port: int = 8000,
        engine: str = "chatterbox",  # "chatterbox", "chatterbox_mtl", or "edge"
        voice: str = "guy",
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        robot_ip: str = "192.168.1.42",
        play_pc: bool = True,
        audio_prompt_path: Optional[str] = None,
        language_id: Optional[str] = None,
        device: Optional[str] = None,
        cache_dir: Optional[str] = None,
        **kwargs,
    ):
        """
        Initializes the AudioService.
        :param host_ip: Local PC IP to serve audio from (auto-detected if None).
        :param port: HTTP server port (default: 8000).
        :param engine: 'chatterbox' (default), 'chatterbox_mtl', or 'edge'.
        :param voice: Voice preset name ('guy', 'jenny', 'ana', etc.) for Edge-TTS fallback.
        :param rate: Speech speed adjustment for Edge-TTS.
        :param pitch: Voice pitch adjustment for Edge-TTS.
        :param robot_ip: Target ESP32 IP for interface route detection.
        :param play_pc: Also play the audio locally on the PC speaker via winsound.
        :param audio_prompt_path: Path to reference audio WAV for voice cloning with Chatterbox.
        :param language_id: Language code for multilingual Chatterbox (e.g. 'fr', 'zh', 'es').
        :param device: PyTorch compute device ('cuda' or 'cpu'). Auto-selected if None.
        """
        self.port = port
        self.robot_ip = robot_ip
        self.play_pc = play_pc
        self.volume: float = 1.0
        self.engine = engine.lower()
        self.audio_prompt_path = audio_prompt_path
        self.language_id = language_id
        self.cache_dir = cache_dir or tempfile.gettempdir()
        self.wav_filename = "ikru_speech.wav"
        self.wav_path = os.path.join(self.cache_dir, self.wav_filename)
        self.mp3_path = os.path.join(self.cache_dir, "temp_ikru.mp3")

        # Resolve compute device for Chatterbox
        if device:
            self.device = device
        elif HAS_CHATTERBOX and torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        # Model handles (lazy-loaded or initialized on first use)
        self.chatterbox_model: Optional[ChatterboxTTS] = None
        self.multilingual_model: Optional[ChatterboxMultilingualTTS] = None

        # Resolve Edge-TTS voice preset
        preset = VOICE_PRESETS.get(voice.lower())
        if preset:
            self.voice = preset["voice"]
            self.rate = rate or preset["rate"]
            self.pitch = pitch or preset["pitch"]
            self.voice_label = f"{preset['desc']} ({self.voice})"
        else:
            self.voice = voice
            self.rate = rate or "+0%"
            self.pitch = pitch or "+0Hz"
            self.voice_label = self.voice

        self.host_ip = host_ip or self._detect_local_ip(target_ip=self.robot_ip)
        self.last_duration: float = 0.0

        self._server: Optional[socketserver.TCPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False

        if self.engine.startswith("chatterbox") and HAS_CHATTERBOX:
            print(f"[AudioService] Voice Engine: Chatterbox TTS (lazy load on demand, device: {self.device})")
            if self.audio_prompt_path:
                print(f"[AudioService] Voice Prompt: {self.audio_prompt_path}")
        else:
            print(f"[AudioService] Voice Engine: Edge-TTS | Voice: {self.voice_label}")

        self._start_server()

    def _detect_local_ip(self, target_ip: str = "192.168.1.42") -> str:
        """Finds the local IP address on the interface communicating with target_ip."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target_ip, 81))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "192.168.1.36"

    def _start_server(self):
        """Starts the background HTTP audio streaming server."""
        service_self = self

        class AudioHTTPHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=service_self.cache_dir, **kwargs)

            def log_message(self, format, *args):
                client_ip = self.client_address[0]
                print(f"[Audio HTTP {time.strftime('%H:%M:%S')}] {client_ip} - {args[0]} (Status: {args[1]})")

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        try:
            self._server = ReusableTCPServer(("0.0.0.0", self.port), AudioHTTPHandler)
            self._running = True
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._server_thread.start()
            print(f"[AudioService] HTTP Audio Server running at http://{self.host_ip}:{self.port}/")
        except Exception as e:
            print(f"[AudioService] Warning: Failed to start HTTP server on port {self.port}: {e}")

    def _init_chatterbox(self):
        """Pre-loads the Chatterbox model on startup."""
        if not HAS_CHATTERBOX:
            print("[AudioService] Warning: Chatterbox TTS not installed, defaulting to Edge-TTS.")
            self.engine = "edge"
            return

        try:
            if self.engine == "chatterbox_mtl" or self.language_id:
                if self.multilingual_model is None:
                    print(f"[AudioService] Initializing Chatterbox Multilingual TTS ({self.device})...")
                    self.multilingual_model = ChatterboxMultilingualTTS.from_pretrained(
                        device=self.device,
                        t3_model="v3"
                    )
            else:
                if self.chatterbox_model is None:
                    print(f"[AudioService] Initializing Chatterbox TTS ({self.device})...")
                    self.chatterbox_model = ChatterboxTTS.from_pretrained(device=self.device)
            print(f"[AudioService] Chatterbox TTS loaded successfully!")
        except Exception as e:
            print(f"[AudioService] Error initializing Chatterbox ({e}). Falling back to Edge-TTS.")
            self.engine = "edge"

    def _clean_text_for_tts(self, text: str, preserve_paralinguistic: bool = True) -> str:
        """
        Cleans and normalizes text for speech synthesis:
        1. Normalizes 'IKRU' / 'I.K.R.U.' acronym to 'Ikru' ('Ik-roo').
        2. Strips camera observation artifacts and prompt tags like '[Camera Visual Observation: ...]'.
        3. Normalizes voice tag variations ([clear throat], [laugh], [chuckle]) to Chatterbox's exact
           supported special tokens ([clear_throat], [laughter], [giggle], [sigh], [gasp], [cry], etc.).
        4. Strips all OLED eye emotions ([happy], [focused], [sad], etc.) and any other bracketed tags
           so they are NEVER read aloud as words.
        5. Ensures proper spacing around vocal tokens so the BPE tokenizer recognizes them as special tokens.
        6. Cleans extraneous punctuation spacing, markdown, and whitespace.
        """
        if not text:
            return ""

        # Strip stray JSON and markdown tokens before tag normalization
        text = re.sub(r'[\{\}\`\*\_]', ' ', text)

        # Normalize 'IKRU' pronunciation
        text = re.sub(r'\bI[Kk][Rr][Uu]\b', 'Ikru', text)
        text = re.sub(r'\bI\.K\.R\.U\.\b', 'Ikru', text)
        text = re.sub(r'\bi-k-r-u\b', 'Ikru', text, flags=re.IGNORECASE)

        # Strip vision/camera observation prompt leaks
        text = re.sub(r'\[Camera Visual Observation:[^\]]*\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[Camera[^\]]*\]', '', text, flags=re.IGNORECASE)

        if preserve_paralinguistic:
            # Map vocal sound aliases to Chatterbox's exact vocabulary tokens
            vocal_aliases = [
                (re.compile(r'\[clear[\s_]?throat\]', re.IGNORECASE), ' [clear_throat] '),
                (re.compile(r'\[clear\]', re.IGNORECASE), ' [clear_throat] '),
                (re.compile(r'\[throat[\s_]?clear\]', re.IGNORECASE), ' [clear_throat] '),
                (re.compile(r'\[laugh(?:ing|s|ter)?\]', re.IGNORECASE), ' [laughter] '),
                (re.compile(r'\[haha+\]', re.IGNORECASE), ' [laughter] '),
                (re.compile(r'\[cackle\]', re.IGNORECASE), ' [laughter] '),
                (re.compile(r'\[chuckle[sd]?\]', re.IGNORECASE), ' [giggle] '),
                (re.compile(r'\[giggle[sd]?\]', re.IGNORECASE), ' [giggle] '),
                (re.compile(r'\[snicker[sd]?\]', re.IGNORECASE), ' [giggle] '),
                (re.compile(r'\[sigh[sd]?\]', re.IGNORECASE), ' [sigh] '),
                (re.compile(r'\[gasp[sd]?\]', re.IGNORECASE), ' [gasp] '),
                (re.compile(r'\[cry(?:ing)?\]', re.IGNORECASE), ' [cry] '),
                (re.compile(r'\[sob(?:bing|s)?\]', re.IGNORECASE), ' [cry] '),
                (re.compile(r'\[groan[sd]?\]', re.IGNORECASE), ' [groan] '),
                (re.compile(r'\[whisper(?:ing|s)?\]', re.IGNORECASE), ' [whisper] '),
                (re.compile(r'\[cough(?:ing|s)?\]', re.IGNORECASE), ' [cough] '),
                (re.compile(r'\[sneeze[sd]?\]', re.IGNORECASE), ' [sneeze] '),
                (re.compile(r'\[sniff(?:ing|s)?\]', re.IGNORECASE), ' [sniff] '),
                (re.compile(r'\[snort[sd]?\]', re.IGNORECASE), ' [sniff] '),
                (re.compile(r'\[yawn(?:ing|s|ed)?\]', re.IGNORECASE), ' [sigh] '),
            ]
            for pattern, repl in vocal_aliases:
                text = pattern.sub(repl, text)

            # Whitelist of valid Chatterbox special tokens
            valid_chatterbox_tags = {
                '[clear_throat]', '[laughter]', '[giggle]', '[sigh]',
                '[gasp]', '[groan]', '[cry]', '[whisper]', '[sniff]',
                '[cough]', '[sneeze]', '[inhale]', '[exhale]'
            }

            # Strip any bracketed tag that is NOT in the valid vocal token whitelist
            # (This eliminates all OLED emotions like [happy], [focused], [sad], [annoyed], etc.)
            def _filter_bracketed_tags(match):
                tag = match.group(0).lower()
                return tag if tag in valid_chatterbox_tags else ''

            text = re.sub(r'\[[^\]]+\]', _filter_bracketed_tags, text)

            # Ensure isolated spacing around valid vocal tags so tokenizer never splits them
            text = re.sub(
                r'\s*(\[(?:clear_throat|laughter|giggle|sigh|gasp|groan|cry|whisper|sniff|cough|sneeze|inhale|exhale)\])\s*',
                r' \1 ',
                text,
            )
        else:
            # For Edge-TTS or non-Chatterbox engines, strip all bracketed tags
            text = re.sub(r'\[[^\]]*\]', '', text)

        # Clean punctuation spacing (e.g. "word ." -> "word.")
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)

        # Collapse excess whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def set_voice(self, voice: str, rate: Optional[str] = None, pitch: Optional[str] = None):
        """Dynamically updates the active Edge-TTS voice and expression preset."""
        preset = VOICE_PRESETS.get(voice.lower())
        if preset:
            self.voice = preset["voice"]
            self.rate = rate or preset["rate"]
            self.pitch = pitch or preset["pitch"]
            self.voice_label = f"{preset['desc']} ({self.voice})"
        else:
            self.voice = voice
            self.rate = rate or "+0%"
            self.pitch = pitch or "+0Hz"
            self.voice_label = self.voice
        print(f"[AudioService] Active Voice changed to: {self.voice_label}")

    def set_engine(self, engine: str):
        """Switches synthesis engine between 'chatterbox', 'chatterbox_mtl', and 'edge'."""
        self.engine = engine.lower()
        if self.engine.startswith("chatterbox"):
            self._init_chatterbox()
        print(f"[AudioService] Active TTS Engine changed to: {self.engine}")

    def set_audio_prompt(self, audio_prompt_path: Optional[str]):
        """Sets custom reference WAV for zero-shot voice cloning with Chatterbox."""
        self.audio_prompt_path = audio_prompt_path
        print(f"[AudioService] Audio Prompt Path set to: {self.audio_prompt_path}")

    def set_play_pc(self, play_pc: bool):
        """Dynamically updates PC speaker playback and purges playing audio if disabled."""
        self.play_pc = bool(play_pc)
        if not self.play_pc and HAS_WINSOUND and os.name == "nt":
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def set_volume(self, volume: float):
        """Sets master audio volume scale factor (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, float(volume)))
        print(f"[AudioService] Master Volume set to {int(self.volume * 100)}%")

    def _fast_resample(self, data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Fast sub-millisecond linear interpolation resampling for audio arrays."""
        if orig_sr == target_sr or len(data) <= 1:
            return data
        old_len = len(data)
        new_len = int(round(old_len * target_sr / orig_sr))
        old_indices = np.arange(old_len)
        new_indices = np.linspace(0, old_len - 1, new_len)
        if data.ndim == 1:
            return np.interp(new_indices, old_indices, data)
        else:
            return np.column_stack([
                np.interp(new_indices, old_indices, data[:, ch]) for ch in range(data.shape[1])
            ])

    def _synthesize_chatterbox(
        self,
        clean_text: str,
        audio_prompt_path: Optional[str] = None,
        language_id: Optional[str] = None,
    ) -> Optional[np.ndarray]:
        """Synthesizes text using Chatterbox TTS (standard or multilingual)."""
        prompt = audio_prompt_path or self.audio_prompt_path
        lang = language_id or self.language_id

        # Multilingual synthesis
        if lang or self.engine == "chatterbox_mtl":
            if self.multilingual_model is None:
                self.multilingual_model = ChatterboxMultilingualTTS.from_pretrained(
                    device=self.device,
                    t3_model="v3"
                )
            wav = self.multilingual_model.generate(clean_text, language_id=lang or "en")
            sr = self.multilingual_model.sr
        else:
            # Standard English expressive synthesis with paralinguistic tag support
            if self.chatterbox_model is None:
                self.chatterbox_model = ChatterboxTTS.from_pretrained(device=self.device)

            if prompt and os.path.exists(prompt):
                wav = self.chatterbox_model.generate(clean_text, audio_prompt_path=prompt)
            else:
                wav = self.chatterbox_model.generate(clean_text)
            sr = self.chatterbox_model.sr

        # Convert torch tensor to numpy
        if isinstance(wav, torch.Tensor):
            audio_np = wav.squeeze().detach().cpu().numpy()
        else:
            audio_np = np.array(wav).squeeze()

        # Resample to 44.1kHz (44100 Hz required by ESP32 MAX98357A I2S)
        target_rate = 44100
        if sr != target_rate:
            audio_np = self._fast_resample(audio_np, sr, target_rate)

        # Ensure stereo 2-channel array
        if audio_np.ndim == 1:
            stereo_data = np.column_stack((audio_np, audio_np))
        else:
            stereo_data = audio_np

        return stereo_data

    def _synthesize_edge_tts(self, clean_text: str) -> Optional[np.ndarray]:
        """Synthesizes text using Edge-TTS Communicator."""
        import edge_tts

        async def _save_mp3():
            communicate = edge_tts.Communicate(
                clean_text,
                self.voice,
                rate=self.rate,
                pitch=self.pitch,
            )
            await communicate.save(self.mp3_path)

        asyncio.run(_save_mp3())

        if not os.path.exists(self.mp3_path):
            return None

        # Read MP3 audio data
        data, sample_rate = sf.read(self.mp3_path)

        # Resample to 44100 Hz
        target_rate = 44100
        if sample_rate != target_rate:
            data = self._fast_resample(data, sample_rate, target_rate)

        # Ensure 2-channel stereo
        if data.ndim == 1:
            stereo_data = np.column_stack((data, data))
        else:
            stereo_data = data

        if os.path.exists(self.mp3_path):
            try:
                os.remove(self.mp3_path)
            except Exception:
                pass

        return stereo_data

    def synthesize(
        self,
        text: str,
        play_pc: Optional[bool] = None,
        voice: Optional[str] = None,
        engine: Optional[str] = None,
        audio_prompt_path: Optional[str] = None,
        language_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Synthesizes text into 44.1kHz 16-bit Stereo PCM WAV:
        1. Cleans text (preserving [chuckle], [laugh] tags for Chatterbox).
        2. Generates speech via Chatterbox TTS (with Edge-TTS fallback).
        3. Saves 16-bit Stereo PCM WAV at self.wav_path.
        4. Optionally plays on PC speaker if play_pc is True.
        Returns the HTTP stream URL for ESP32 I2S playback.
        """
        if not text or not text.strip():
            return None

        active_engine = (engine or self.engine).lower()
        use_chatterbox = active_engine.startswith("chatterbox") and HAS_CHATTERBOX

        # Clean text: keep paralinguistic voice tags for Chatterbox, strip for Edge-TTS
        clean_text = self._clean_text_for_tts(text, preserve_paralinguistic=use_chatterbox)
        if not clean_text:
            return None

        if voice:
            self.set_voice(voice)

        should_play_pc = self.play_pc if play_pc is None else bool(play_pc)
        target_rate = 44100
        stereo_data = None

        with self._lock:
            try:
                # 1. Primary synthesis: Chatterbox TTS
                if use_chatterbox:
                    try:
                        stereo_data = self._synthesize_chatterbox(
                            clean_text,
                            audio_prompt_path=audio_prompt_path,
                            language_id=language_id,
                        )
                    except Exception as e:
                        import traceback
                        print(f"[AudioService] Chatterbox synthesis error ({e}). Falling back to Edge-TTS...")
                        traceback.print_exc()
                        try:
                            clean_text_edge = self._clean_text_for_tts(text, preserve_paralinguistic=False)
                            stereo_data = self._synthesize_edge_tts(clean_text_edge)
                        except Exception as e2:
                            print(f"[AudioService] Edge-TTS fallback also failed ({e2}). No audio produced.")
                            return None

                # 2. Secondary synthesis: Edge-TTS
                else:
                    stereo_data = self._synthesize_edge_tts(clean_text)

                if stereo_data is None:
                    return None

                # Apply master volume scaling
                if self.volume != 1.0:
                    stereo_data = np.clip(stereo_data * self.volume, -1.0, 1.0)

                # Calculate duration in seconds
                self.last_duration = float(len(stereo_data) / target_rate)

                # Write 16-bit Stereo PCM WAV
                sf.write(self.wav_path, stereo_data, target_rate, subtype="PCM_16")

                # Optional local PC speaker playback (winsound)
                if should_play_pc and HAS_WINSOUND and os.name == "nt":
                    try:
                        winsound.PlaySound(self.wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    except Exception as e:
                        print(f"[AudioService] PC Playback error: {e}")
                elif not should_play_pc and HAS_WINSOUND and os.name == "nt":
                    try:
                        winsound.PlaySound(None, winsound.SND_PURGE)
                    except Exception:
                        pass

                # Return fresh HTTP streaming URL (simple path for ESP32 HTTPClient)
                return f"http://{self.host_ip}:{self.port}/{self.wav_filename}"

            except Exception as e:
                print(f"[AudioService] Synthesis error: {e}")
                return None

    def pregenerate_fillers(self):
        """Pre-generates filler audio files to be played while thinking, caching them permanently."""
        self.filler_phrases = [
            ("[hmm] Hmm... let me think.", "filler_0.wav"),
            ("[hmm] Just a moment.", "filler_1.wav"),
            ("[hmm] Let's see...", "filler_2.wav"),
            ("Thinking...", "filler_3.wav")
        ]
        self.filler_urls = []
        for text, filename in self.filler_phrases:
            filepath = os.path.join(self.cache_dir, filename)
            url = f"http://{self.host_ip}:{self.port}/{filename}"
            self.filler_urls.append((url, text))
            
            if not os.path.exists(filepath):
                print(f"[AudioService] Generating cache for: {filename}")
                # temporarily override wav_path to synthesize into filepath
                old_path = self.wav_path
                old_filename = self.wav_filename
                self.wav_path = filepath
                self.wav_filename = filename
                try:
                    self.synthesize(text, play_pc=False)
                finally:
                    self.wav_path = old_path
                    self.wav_filename = old_filename
        print("[AudioService] All filler phrases cached and ready.")

    def get_random_filler(self):
        """Returns a random (url, text) tuple from the pre-generated fillers."""
        import random
        if getattr(self, 'filler_urls', None):
            return random.choice(self.filler_urls)
        return None, None

    def stop(self):
        """Stops the audio HTTP server."""
        self._running = False
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            print("[AudioService] HTTP Audio Server stopped.")
