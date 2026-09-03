"""
===============================================================================
PROJECT IKRU — R2-D2 ASTROMECH SONIC EMOTION ENGINE & CLIENT
===============================================================================
Provides non-verbal emotional audio synthesis for IKRU:
1. Translates natural language sentences into expressive R2-D2 droid vocalizations
   (pitch sweeps, glissando chirps, word-length scaled cadence, trills, and whistles).
2. Manages transmission to the ESP32-CAM Head Speaker (192.168.4.1:5000) over TCP.
3. Provides continuous-phase 22.05 kHz WAV synthesis for local PC audio.
===============================================================================
"""

import io
import math
import os
import re
import socket
import struct
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


@dataclass
class DroidStep:
    """
    Represents a dynamic droid sound element:
    - If start_freq == end_freq: steady tone
    - If start_freq != end_freq: continuous glissando frequency sweep (chirp)
    """
    start_freq: int       # Starting frequency in Hz (0 = silence)
    end_freq: int         # Ending frequency in Hz (0 = silence)
    duration_ms: int      # Duration in milliseconds (proportional to word length)
    pause_ms: int = 10    # Pause after element in milliseconds
    word_label: str = ""  # Optional word token label

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (int(self.start_freq), int(self.end_freq), int(self.duration_ms), int(self.pause_ms))

    def to_dict(self) -> dict:
        d = {
            "start": int(self.start_freq),
            "end": int(self.end_freq),
            "dur": int(self.duration_ms),
            "pause": int(self.pause_ms)
        }
        if self.word_label:
            d["word"] = self.word_label
        return d


class SonicEmotionEngine:
    """
    Core R2-D2 Astromech audio generator and prosody analyzer.
    """

    EMOTION_MAP = {
        # High arousal positive
        "happy": "happy",
        "glee": "excited",
        "excited": "excited",
        "awe": "affection",
        "affection": "affection",
        "success": "success",

        # Low arousal negative
        "sad": "sad",
        "worried": "sad",
        "sleepy": "sleepy",
        "cannot_perform": "cannot_perform",
        "error": "error",

        # High arousal negative
        "angry": "angry",
        "furious": "angry",
        "frustrated": "angry",
        "annoyed": "angry",
        "scared": "warning",
        "warning": "warning",

        # Inquisitive / Neutral
        "confused": "confused",
        "skeptic": "confused",
        "suspicious": "confused",
        "squint": "confused",
        "surprised": "surprised",
        "focused": "thinking",
        "thinking": "thinking",
        "unimpressed": "neutral",
        "neutral": "neutral",
        "normal": "neutral",
        "processing": "processing",
    }

    def normalize_emotion_name(self, name: any) -> str:
        if not name or not isinstance(name, str):
            return "neutral"
        clean = name.strip().lower()
        return self.EMOTION_MAP.get(clean, "neutral")

    def clamp_intensity(self, val: float) -> float:
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return 0.5
            return max(0.0, min(1.0, f))
        except (ValueError, TypeError):
            return 0.5

    def build_esp32_command(
        self,
        emotion: str,
        intensity: float = 0.5,
        intent: Optional[str] = None,
        mode: str = "json_named"
    ) -> Union[dict, str]:
        clamped_intensity = self.clamp_intensity(intensity)
        norm_emotion = self.normalize_emotion_name(emotion)
        steps = self.generate_pattern(norm_emotion, clamped_intensity, intent)

        if mode == "protocol_named":
            return f"SOUND:{norm_emotion.upper()}:{clamped_intensity:.2f}"
        elif mode == "protocol_tones":
            tone_strs = [f"{int(s.start_freq)},{int(s.end_freq)},{int(s.duration_ms)},{int(s.pause_ms)}" for s in steps]
            return f"TONES:{';'.join(tone_strs)}"
        elif mode == "json_tones":
            return {
                "type": "tones",
                "tones": [s.to_tuple() for s in steps]
            }
        else:  # json_named default
            return {
                "type": "sound",
                "pattern": norm_emotion,
                "intensity": clamped_intensity,
                "steps": [s.to_dict() for s in steps]
            }

    # -------------------------------------------------------------------------
    # R2-D2 ASTROMECH GLISSANDO SOUND GENERATORS
    # -------------------------------------------------------------------------

    def _chirp(self, start_f: int, end_f: int, dur_ms: int, pause_ms: int = 8, label: str = "") -> DroidStep:
        return DroidStep(int(start_f), int(end_f), int(dur_ms), int(pause_ms), label)

    def _generate_happy(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1400, 1850, 45, 10),
            self._chirp(1850, 2600, 55, 12),
            self._chirp(2600, 3400, 70 + int(30 * intensity), 15),
            self._chirp(3400, 3600, 140 + int(70 * intensity), 0),
        ]

    def _generate_excited(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1800, 2400, 35, 6),
            self._chirp(2400, 3100, 35, 6),
            self._chirp(3100, 3700, 40, 8),
            self._chirp(3700, 3200, 45, 6),
            self._chirp(3200, 4000, 60, 8),
            self._chirp(4000, 4200, 120 + int(60 * intensity), 0),
        ]

    def _generate_sad(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(2100, 1100, 160 + int(50 * intensity), 25),
            self._chirp(1100, 500, 200 + int(60 * intensity), 30),
            self._chirp(500, 220, 260 + int(80 * intensity), 0),
        ]

    def _generate_angry(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(450, 220, 70, 10),
            self._chirp(220, 500, 65, 8),
            self._chirp(3600, 1800, 90 + int(40 * intensity), 12),
            self._chirp(550, 180, 140, 0),
        ]

    def _generate_confused(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1500, 1750, 40, 70),
            self._chirp(1800, 1450, 45, 55),
            self._chirp(950, 2800, 130 + int(50 * intensity), 0),
        ]

    def _generate_surprised(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(850, 3600, 65 + int(30 * intensity), 12),
            self._chirp(3600, 2200, 45, 8),
            self._chirp(2200, 3800, 80, 0),
        ]

    def _generate_thinking(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1450, 1600, 30, 80),
            self._chirp(1650, 1500, 30, 90),
            self._chirp(1750, 1900, 35, 75),
            self._chirp(1850, 1700, 40, 0),
        ]

    def _generate_sleepy(self, intensity: float) -> List[DroidStep]:
        return [
            # Inhale (snore in)
            self._chirp(150, 300, 800 + int(200 * intensity), 300),
            # Exhale (snore out)
            self._chirp(300, 100, 1000 + int(300 * intensity), 600),
            # Inhale
            self._chirp(150, 300, 800 + int(200 * intensity), 300),
            # Exhale
            self._chirp(300, 100, 1000 + int(300 * intensity), 0),
        ]

    def _generate_affection(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1300, 1650, 55, 12),
            self._chirp(1650, 2200, 65, 15),
            self._chirp(2200, 2000, 50, 10),
            self._chirp(2000, 2700, 130 + int(40 * intensity), 0),
        ]

    def _generate_success(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1200, 1600, 40, 8),
            self._chirp(1600, 2100, 45, 10),
            self._chirp(2100, 2800, 55, 12),
            self._chirp(2800, 3500, 150 + int(70 * intensity), 0),
        ]

    def _generate_error(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(800, 250, 110, 35),
            self._chirp(750, 200, 140, 0),
        ]

    def _generate_warning(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(2200, 3400, 50, 15),
            self._chirp(3400, 2200, 50, 15),
            self._chirp(2200, 3400, 50, 15),
            self._chirp(3400, 2200, 50, 0),
        ]

    def _generate_processing(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1700, 1750, 20, 50),
            self._chirp(1800, 1850, 20, 50),
            self._chirp(1900, 1950, 20, 50),
            self._chirp(2000, 2050, 25, 0),
        ]

    def _generate_cannot_perform(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1500, 1050, 90, 40),
            self._chirp(1000, 650, 130, 0),
        ]

    def _generate_neutral(self, intensity: float) -> List[DroidStep]:
        return [
            self._chirp(1400, 1700, 40, 18),
            self._chirp(1700, 2500, 80, 0),
        ]

    def generate_pattern(
        self,
        emotion: str,
        intensity: float = 0.5,
        intent: Optional[str] = None
    ) -> List[DroidStep]:
        clamped_intensity = self.clamp_intensity(intensity)
        norm_emotion = self.normalize_emotion_name(emotion)
        generators = {
            "happy": self._generate_happy,
            "excited": self._generate_excited,
            "sad": self._generate_sad,
            "angry": self._generate_angry,
            "confused": self._generate_confused,
            "surprised": self._generate_surprised,
            "thinking": self._generate_thinking,
            "sleepy": self._generate_sleepy,
            "affection": self._generate_affection,
            "success": self._generate_success,
            "error": self._generate_error,
            "warning": self._generate_warning,
            "processing": self._generate_processing,
            "cannot_perform": self._generate_cannot_perform,
            "neutral": self._generate_neutral,
        }
        gen_func = generators.get(norm_emotion, self._generate_neutral)
        return gen_func(clamped_intensity)

    # -------------------------------------------------------------------------
    # NATURAL SENTENCE-TO-DROID PROSODY ANALYZER
    # -------------------------------------------------------------------------

    def analyze_sentence_emotion(self, sentence: str) -> Tuple[str, float, Optional[str]]:
        text = sentence.strip().lower()
        if not text:
            return "neutral", 0.5, None

        tag_match = re.match(r'\[([a-z]+)\](.*)', text)
        if tag_match:
            tag, _ = tag_match.groups()
            norm = self.normalize_emotion_name(tag)
            return norm, 0.75, None

        is_question = "?" in text or text.startswith((
            "what", "who", "where", "when", "why", "how",
            "can you", "could you", "is that", "are you", "do you"
        ))
        is_exclamation = "!" in text

        warning_words = ["warning", "danger", "careful", "watch out", "stop", "halt", "alert", "fire", "emergency", "obstacle"]
        angry_words = ["angry", "mad", "hate", "furious", "shut up", "annoying", "idiot", "worst", "stupid", "rage"]
        cannot_words = ["cannot", "cant", "can't", "unable", "not allowed", "failed", "impossible", "blocked"]
        sad_words = ["sad", "sorry", "unfortunate", "lost", "bad", "terrible", "depressed", "miss", "hurt", "crying", "apologize"]
        sleepy_words = ["sleep", "sleepy", "tired", "good night", "goodnight", "bedtime", "yawn", "nap", "exhausted", "rest"]
        discovery_words = ["found", "solved", "discovered", "completed", "success", "finished", "here it is", "got it", "i found"]
        excited_words = ["excited", "amazing", "incredible", "fantastic", "so happy", "super", "omg", "wow", "yesss"]
        happy_words = ["happy", "great", "awesome", "yay", "love", "hurray", "wonderful", "cool", "nice", "glad", "good", "welcome"]
        thinking_words = ["think", "thinking", "let me see", "calculating", "processing", "checking", "hmm", "pondering", "ponder", "scanning", "looking", "searching"]
        affection_words = ["cute", "sweet", "hug", "friend", "thank you", "thanks", "love you", "precious", "buddy"]

        if any(w in text for w in warning_words):
            return "warning", 0.9, None
        if any(w in text for w in angry_words):
            return "angry", 0.8, None
        if any(w in text for w in cannot_words):
            return "cannot_perform", 0.6, "error"
        if any(w in text for w in sad_words):
            return "sad", 0.7, "error" if "error" in text else None
        if any(w in text for w in sleepy_words):
            return "sleepy", 0.5, None
        if any(w in text for w in discovery_words):
            return "happy", 0.85, "success"
        if any(w in text for w in excited_words):
            return "excited", 0.9, "success" if is_exclamation else None
        if any(w in text for w in happy_words):
            return "happy", 0.8 if is_exclamation else 0.6, "success" if is_exclamation else None
        if any(w in text for w in thinking_words):
            return "thinking", 0.5, None
        if any(w in text for w in affection_words):
            return "affection", 0.7, None

        if is_question:
            return "confused", 0.6, "question"
        if is_exclamation:
            return "happy", 0.75, "success"

        return "neutral", 0.5, None

    def sentence_to_droid_pattern(
        self,
        sentence: str,
        emotion_override: Optional[str] = None,
        intensity: Optional[float] = None
    ) -> Tuple[str, float, List[DroidStep]]:
        """
        Converts an English sentence into speech-paced R2-D2 droid vocalizations.
        Duration of each chirp is scaled to word length and syllable count.
        """
        clean_text = sentence.strip()
        auto_emo, auto_int, intent = self.analyze_sentence_emotion(clean_text)
        emotion = self.normalize_emotion_name(emotion_override) if emotion_override else auto_emo
        eff_intensity = self.clamp_intensity(intensity if intensity is not None else auto_int)

        text_content = re.sub(r'\[[a-z]+\]', '', clean_text).strip()
        if not text_content:
            return emotion, eff_intensity, self.generate_pattern(emotion, eff_intensity, intent)

        words = re.findall(r'\w+|[.,!?;]', text_content)
        word_tokens = [w for w in words if re.match(r'\w+', w)]
        if not word_tokens:
            return emotion, eff_intensity, self.generate_pattern(emotion, eff_intensity, intent)

        steps: List[DroidStep] = []
        is_question = "?" in text_content
        is_exclamation = "!" in text_content

        if emotion in ["happy", "excited"]:
            base_f = int(1300 * (1.0 + 0.2 * eff_intensity))
            top_f = int(2800 * (1.0 + 0.3 * eff_intensity))
            contour = "rising"
        elif emotion in ["sad", "cannot_perform"]:
            base_f = int(1900 * (1.0 - 0.1 * eff_intensity))
            top_f = int(500)
            contour = "falling"
        elif emotion == "angry":
            base_f = int(600)
            top_f = int(3200)
            contour = "abrasive"
        elif emotion == "warning":
            base_f = int(2200)
            top_f = int(3400)
            contour = "siren"
        elif emotion == "thinking":
            base_f = int(1400)
            top_f = int(1800)
            contour = "chatter"
        else:
            base_f = int(1200)
            top_f = int(2200)
            contour = "question" if is_question else "conversational"

        total_words = len(word_tokens)

        for idx, word in enumerate(word_tokens):
            progress = (idx / max(1, total_words - 1)) if total_words > 1 else 0.5
            char_len = len(word)
            vowels = len(re.findall(r'[aeiouy]+', word.lower()))
            syllables = max(1, min(5, vowels))

            base_dur = max(130, min(480, 120 + (char_len - 1) * 26 + (syllables - 1) * 35))

            if contour == "rising":
                cur_f = int(base_f + (top_f - base_f) * progress)
                target_f = cur_f + int(180 + 90 * syllables)
            elif contour == "falling":
                cur_f = int(base_f - (base_f - top_f) * progress)
                target_f = max(300, cur_f - int(140 * syllables))
            elif contour == "abrasive":
                cur_f = base_f if idx % 2 == 0 else top_f
                target_f = cur_f + (200 if idx % 2 == 0 else -400)
            elif contour == "siren":
                cur_f = base_f if idx % 2 == 0 else top_f
                target_f = top_f if idx % 2 == 0 else base_f
            else:
                cur_f = base_f + int(350 * math.sin(progress * math.pi))
                target_f = cur_f + int(100 * syllables)

            pause = 75 if idx < total_words - 1 else 0

            # Polysyllabic compounding for 8+ character words
            if char_len >= 8 and idx != total_words - 1:
                part1_dur = int(base_dur * 0.5)
                part2_dur = int(base_dur * 0.5)
                mid_f = int((cur_f + target_f) / 2 + 300)
                steps.append(DroidStep(cur_f, mid_f, part1_dur, 15, word_label=word + " (1/2)"))
                steps.append(DroidStep(mid_f, target_f, part2_dur, pause, word_label=word + " (2/2)"))
                continue

            if idx == total_words - 1:
                if is_question:
                    steps.append(DroidStep(cur_f, int(top_f * 1.35), max(160, base_dur + 40), 0, word_label=word + "?"))
                    continue
                elif is_exclamation or emotion in ["happy", "excited"]:
                    steps.append(DroidStep(cur_f, top_f, int(base_dur * 0.7), 15, word_label=word))
                    steps.append(DroidStep(top_f, int(top_f * 1.2), max(160, int(base_dur * 0.8)), 0, word_label="!"))
                    continue

            steps.append(DroidStep(cur_f, target_f, base_dur, pause, word_label=word))

        return emotion, eff_intensity, steps

    # -------------------------------------------------------------------------
    # CONTINUOUS-PHASE WAV SYNTHESIS
    # -------------------------------------------------------------------------

    def synthesize_wav(
        self,
        steps: List[DroidStep],
        sample_rate: int = 22050,
        volume: float = 0.20
    ) -> io.BytesIO:
        wav_io = io.BytesIO()
        max_amp = int(32767 * max(0.0, min(1.0, volume)))

        pcm_samples = []
        current_phase = 0.0

        for step in steps:
            start_f = step.start_freq
            end_f = step.end_freq
            dur_sec = step.duration_ms / 1000.0
            pause_sec = step.pause_ms / 1000.0

            total_samples = int(sample_rate * dur_sec)
            attack_decay_len = min(int(sample_rate * 0.004), max(1, total_samples // 6))

            for i in range(total_samples):
                if start_f <= 0 and end_f <= 0:
                    pcm_samples.append(0)
                    continue

                progress = i / max(1, total_samples)
                inst_freq = start_f + (end_f - start_f) * progress

                current_phase += (2.0 * math.pi * inst_freq) / sample_rate
                if current_phase > 2.0 * math.pi:
                    current_phase -= 2.0 * math.pi * (current_phase // (2.0 * math.pi))

                val = math.sin(current_phase) + 0.15 * math.sin(2.0 * current_phase)

                envelope = 1.0
                if attack_decay_len > 0:
                    if i < attack_decay_len:
                        envelope = i / attack_decay_len
                    elif i > total_samples - attack_decay_len:
                        envelope = (total_samples - i) / attack_decay_len

                sample_val = int(val * envelope * max_amp)
                pcm_samples.append(max(-32767, min(32767, sample_val)))

            pause_samples = int(sample_rate * pause_sec)
            for _ in range(pause_samples):
                pcm_samples.append(0)

        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            raw_data = struct.pack(f"<{len(pcm_samples)}h", *pcm_samples)
            wf.writeframes(raw_data)

        wav_io.seek(0)
        return wav_io


class SonicClient:
    """
    Client interface connecting the host application to the ESP32-CAM Head Speaker (192.168.4.1:5000)
    with integrated local PC audio playback.
    """

    def __init__(
        self,
        ip: str = "192.168.4.1",
        port: int = 5000,
        enable_local_audio: bool = True,
        volume: float = 0.20
    ):
        self.ip = ip
        self.port = port
        self.enable_local_audio = enable_local_audio
        self.volume = volume
        self.engine = SonicEmotionEngine()
        self.temp_dir = Path(__file__).parent / "scratch"

    def play_sentence(self, sentence: str, emotion_override: Optional[str] = None) -> Tuple[str, float, int]:
        """
        Translates a natural language sentence into R2-D2 beeps and plays it
        on the ESP32-CAM Head Speaker and PC speakers.
        Returns: (emotion, intensity, total_duration_ms)
        """
        emo, intensity, steps = self.engine.sentence_to_droid_pattern(sentence, emotion_override)
        total_dur = sum(s.duration_ms + s.pause_ms for s in steps)

        # 1. Transmit to ESP32 Head Speaker via fast TCP
        self._transmit_steps(steps, emo, intensity)

        # 2. Concurrently play local PC audio preview
        if self.enable_local_audio:
            self._play_pc_audio(steps)

        return emo, intensity, total_dur

    def play_emotion(self, emotion: str, intensity: float = 0.5):
        """Plays a canned emotion sound signature."""
        steps = self.engine.generate_pattern(emotion, intensity)
        self._transmit_steps(steps, emotion, intensity)
        if self.enable_local_audio:
            self._play_pc_audio(steps)

    def _transmit_steps(self, steps: List[DroidStep], emotion: str, intensity: float):
        if steps and len(steps) > 0:
            tone_strs = [f"{int(s.start_freq)},{int(s.end_freq)},{int(s.duration_ms)},{int(s.pause_ms)}" for s in steps]
            cmd_str = f"TONES:{';'.join(tone_strs)}\n"
        else:
            cmd_str = f"SOUND:{emotion.upper()}:{intensity:.2f}\n"

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.8)
            sock.connect((self.ip, self.port))
            sock.sendall(cmd_str.encode("utf-8"))
            sock.recv(32)
        except Exception:
            # Silent fallback if ESP32-CAM is offline
            pass
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def _play_pc_audio(self, steps: List[DroidStep]):
        if not HAS_WINSOUND or not steps:
            return
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            wav_path = self.temp_dir / "live_speech.wav"
            wav_io = self.engine.synthesize_wav(steps, volume=self.volume)
            wav_path.write_bytes(wav_io.getvalue())

            threading.Thread(
                target=winsound.PlaySound,
                args=(str(wav_path), winsound.SND_FILENAME),
                daemon=True
            ).start()
        except Exception:
            pass
