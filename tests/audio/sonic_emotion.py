"""
===============================================================================
PROJECT IKRU — R2-D2 SONIC EMOTION ENGINE
===============================================================================

Astromech / R2-D2 style droid sound synthesis engine for IKRU.
Produces authentic frequency sweeps (chirps), rapid trills (warbles),
staccato conversational droid chatter, natural sentence-to-droid prosody,
and expressive emotional whistles.

Key Features:
- Natural Sentence-to-Droid Prosody Translation (replicates sentence cadence, syllables & tone)
- Authentic R2-D2 Droid Sound Design (Glissando sweeps, trills, vibrato, chirps)
- 18+ Distinct Droid Personalities (Happy, Sad, Angry, Confused, Success, etc.)
- Dynamic Intensity Modulation (0.0 to 1.0) controlling pitch range, chirp speed, and energy
- Intent Layering & Blending
- Pure-Python Continuous-Phase WAV Synthesizer (Zero dependencies, authentic droid audio)
- Micro-Stepped Non-Blocking Sequences for ESP32 Hardware PWM (SmartElex speaker)
===============================================================================
"""

import io
import json
import math
import re
import struct
import wave
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class DroidStep:
    """
    Represents a dynamic droid sound element:
    - If start_freq == end_freq: steady tone
    - If start_freq != end_freq: smooth continuous frequency sweep / chirp (glissando)
    """
    start_freq: int       # Starting frequency in Hz (0 = silence)
    end_freq: int         # Ending frequency in Hz (0 = silence)
    duration_ms: int      # Duration in milliseconds (proportional to word length)
    pause_ms: int = 10    # Pause after element in milliseconds
    word_label: str = ""  # Optional word/token label for visualization

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


# Backward compatibility alias
Tone = DroidStep


class SonicEmotionEngine:
    """
    R2-D2 Astromech Sonic Emotion Engine for IKRU.
    """

    VALID_EMOTIONS = [
        "neutral", "happy", "excited", "sad", "angry", "confused",
        "surprised", "thinking", "sleepy", "affection", "success",
        "error", "warning", "processing", "cannot_perform"
    ]

    EMOTION_ALIASES = {
        "normal": "neutral",
        "glee": "excited",
        "focused": "thinking",
        "worried": "warning",
        "annoyed": "angry",
        "skeptic": "confused",
        "frustrated": "angry",
        "unimpressed": "sad",
        "suspicious": "confused",
        "squint": "thinking",
        "furious": "angry",
        "scared": "surprised",
        "awe": "affection",
        "blocked": "cannot_perform",
        "failed": "error",
        "ok": "success",
    }

    def __init__(self):
        pass

    @staticmethod
    def clamp_intensity(intensity: Union[int, float]) -> float:
        """Clamps intensity strictly between 0.0 and 1.0 with safe type coercion."""
        try:
            val = float(intensity)
            if math.isnan(val) or math.isinf(val):
                return 0.5
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            return 0.5

    @classmethod
    def normalize_emotion_name(cls, emotion: Optional[str]) -> str:
        """Normalizes and resolves emotion string aliases to canonical names."""
        if not emotion or not isinstance(emotion, str):
            return "neutral"
        clean = emotion.strip().lower()
        if clean in cls.VALID_EMOTIONS:
            return clean
        if clean in cls.EMOTION_ALIASES:
            return cls.EMOTION_ALIASES[clean]
        return "neutral"

    # -------------------------------------------------------------------------
    # HELPER GENERATORS FOR R2-D2 CHIRPS, WARBLES & CHATTERS
    # -------------------------------------------------------------------------

    @staticmethod
    def _chirp(start_hz: int, end_hz: int, dur_ms: int, pause_ms: int = 8) -> DroidStep:
        return DroidStep(int(start_hz), int(end_hz), int(dur_ms), int(pause_ms))

    @staticmethod
    def _tone(freq_hz: int, dur_ms: int, pause_ms: int = 8) -> DroidStep:
        return DroidStep(int(freq_hz), int(freq_hz), int(dur_ms), int(pause_ms))

    @staticmethod
    def _warble(freq_a: int, freq_b: int, cycles: int = 3, step_ms: int = 15, pause_ms: int = 8) -> List[DroidStep]:
        """Rapid alternating trill / warble between two frequencies."""
        steps = []
        for i in range(cycles):
            steps.append(DroidStep(freq_a, freq_b, step_ms, 2))
            steps.append(DroidStep(freq_b, freq_a, step_ms, 2 if i < cycles - 1 else pause_ms))
        return steps

    # -------------------------------------------------------------------------
    # R2-D2 EMOTIONAL SIGNATURE GENERATORS
    # -------------------------------------------------------------------------

    def _generate_happy(self, intensity: float) -> List[DroidStep]:
        """
        R2 HAPPY: Joyful upward chirps, cheerful rising whistle and celebratory trill.
        """
        pitch_mult = 1.0 + (0.25 * intensity)
        base = int(1200 * pitch_mult)
        mid = int(1800 * pitch_mult)
        high = int(2600 * pitch_mult)
        top = int(3200 * pitch_mult)

        dur_scale = max(0.7, 1.1 - (0.3 * intensity))

        if intensity < 0.35:
            return [
                self._chirp(base, mid, int(60 * dur_scale), 15),
                self._chirp(mid, high, int(90 * dur_scale), 0),
            ]
        elif intensity < 0.75:
            return [
                self._chirp(base, mid, int(55 * dur_scale), 12),
                self._chirp(mid, high, int(65 * dur_scale), 12),
                self._chirp(high, top, int(110 * dur_scale), 0),
            ]
        else:
            steps = [
                self._chirp(base, mid, 45, 8),
                self._chirp(mid, top, 55, 10),
            ]
            steps.extend(self._warble(high, top, cycles=3, step_ms=18, pause_ms=8))
            steps.append(self._chirp(high, int(top * 1.15), 130, 0))
            return steps

    def _generate_excited(self, intensity: float) -> List[DroidStep]:
        """
        R2 EXCITED: Fast ascending multi-chirp sparkle and high ecstatic droid trills.
        """
        pitch_mult = 1.0 + (0.3 * intensity)
        b = int(1400 * pitch_mult)

        steps = [
            self._chirp(b, b + 500, 35, 6),
            self._chirp(b + 400, b + 1000, 35, 6),
            self._chirp(b + 900, b + 1600, 45, 8),
        ]
        steps.extend(self._warble(b + 1200, b + 1800, cycles=int(2 + 2 * intensity), step_ms=14, pause_ms=6))
        steps.append(self._chirp(b + 1400, b + 2200, 120, 0))
        return steps

    def _generate_sad(self, intensity: float) -> List[DroidStep]:
        """
        R2 SAD: Pathetic, long downward sliding droid whistle (whooo-oo-op...).
        """
        top = int(2400 - (200 * intensity))
        bottom = int(550 - (150 * intensity))
        dur = int(320 + (220 * intensity))

        return [
            self._chirp(top - 100, top, 60, 25),
            self._chirp(top, bottom, dur, 30),
            self._chirp(bottom + 80, bottom, 140, 0),
        ]

    def _generate_angry(self, intensity: float) -> List[DroidStep]:
        """
        R2 ANGRY: Harsh, low-frequency abrasive buzz sweeps and rapid tantrum screeches.
        """
        low_a = int(350 + (50 * intensity))
        low_b = int(750 + (100 * intensity))
        high_a = int(2200 + (300 * intensity))
        high_b = int(3400 + (400 * intensity))

        steps = [
            self._chirp(low_b, low_a, 50, 10),
            self._chirp(low_a, low_b + 100, 45, 12),
            self._chirp(low_b + 100, low_a - 50, 60, 20),
        ]
        if intensity > 0.4:
            steps.extend([
                self._chirp(high_a, high_b, 40, 8),
                self._chirp(high_b, high_a, 40, 8),
                self._chirp(high_a, high_b, 70, 0),
            ])
        return steps

    def _generate_confused(self, intensity: float) -> List[DroidStep]:
        """
        R2 CONFUSED: Inquisitive droid chatter ending in a distinctive upward questioning sweep (boop-weep?).
        """
        return [
            self._chirp(1100, 1400, 45, 30),
            self._chirp(1600, 1200, 50, 40),
            self._chirp(950, 2600 + int(400 * intensity), 120, 0),
        ]

    def _generate_surprised(self, intensity: float) -> List[DroidStep]:
        """
        R2 SURPRISED: Sudden high-speed rocket sweep and startled droid yip!
        """
        top_freq = int(3400 + (600 * intensity))
        return [
            self._chirp(800, top_freq, 55, 10),
            self._chirp(top_freq, top_freq - 400, 30, 6),
            self._chirp(top_freq - 400, top_freq, 40, 0),
        ]

    def _generate_thinking(self, intensity: float) -> List[DroidStep]:
        """
        R2 THINKING: Conversational droid chatter / computation blips with micro pitch bends.
        """
        pause = int(70 + (70 * (1.0 - intensity)))
        base = int(1400 + (200 * intensity))

        return [
            self._chirp(base, base + 250, 40, pause),
            self._chirp(base + 350, base + 100, 40, pause),
            self._chirp(base + 150, base + 450, 45, pause),
            self._chirp(base + 400, base + 200, 40, 0),
        ]

    def _generate_sleepy(self, intensity: float) -> List[DroidStep]:
        """
        R2 SLEEPY: Gentle powering-down droid whistle slowly trailing into silence.
        """
        dur = int(400 + (250 * intensity))
        return [
            self._chirp(1800, 1600, 90, 40),
            self._chirp(1600, 500, dur, 40),
            self._chirp(450, 250, 160, 0),
        ]

    def _generate_affection(self, intensity: float) -> List[DroidStep]:
        """
        R2 AFFECTION / AWE: Gentle, loving melodic droid warble and warm ascending whistle.
        """
        return [
            self._chirp(1200, 1600, 70, 15),
            self._chirp(1500, 2200, 80, 15),
            self._chirp(2200, 1900, 60, 15),
            self._chirp(1900, 2800, 150, 0),
        ]

    def _generate_success(self, intensity: float) -> List[DroidStep]:
        """
        R2 SUCCESS: Triumphant 4-stage ascending whistle ending in a long sustained vibrato fanfare.
        """
        pitch_mult = 1.0 + (0.2 * intensity)
        steps = [
            self._chirp(int(1100 * pitch_mult), int(1500 * pitch_mult), 50, 10),
            self._chirp(int(1500 * pitch_mult), int(2000 * pitch_mult), 55, 10),
            self._chirp(int(2000 * pitch_mult), int(2700 * pitch_mult), 65, 12),
        ]
        top = int(3200 * pitch_mult)
        steps.extend(self._warble(top - 150, top + 150, cycles=3, step_ms=22, pause_ms=4))
        steps.append(self._chirp(top, int(top * 1.1), 160, 0))
        return steps

    def _generate_error(self, intensity: float) -> List[DroidStep]:
        """
        R2 ERROR: Harsh descending rasp/buzz (BZZT-BZZT) like a blown droid circuit.
        """
        dur = int(80 + (30 * intensity))
        return [
            self._chirp(700, 220, dur, 40),
            self._chirp(650, 180, dur + 20, 0),
        ]

    def _generate_warning(self, intensity: float) -> List[DroidStep]:
        """
        R2 WARNING: Rapid urgent alternating siren chirps.
        """
        high = int(2800 + (400 * intensity))
        low = int(1800 + (300 * intensity))
        dur = int(45 - (10 * intensity))

        steps = []
        count = 3 if intensity < 0.5 else 5
        for i in range(count):
            steps.append(self._chirp(low, high, dur, 6))
            steps.append(self._chirp(high, low, dur, 10 if i < count - 1 else 0))
        return steps

    def _generate_processing(self, intensity: float) -> List[DroidStep]:
        """
        R2 PROCESSING: Fast rhythmic droid radar/sonar clicks & micro-chirps.
        """
        freq = int(1800 + (300 * intensity))
        count = 4 if intensity < 0.6 else 6
        steps = []
        for i in range(count):
            steps.append(self._chirp(freq, freq + 150, 22, 35 if i < count - 1 else 0))
        return steps

    def _generate_cannot_perform(self, intensity: float) -> List[DroidStep]:
        """
        R2 CANNOT PERFORM: Sad descending double boop (boop ↓ boop ↓).
        """
        return [
            self._chirp(1300, 750, 110, 40),
            self._chirp(900, 450, 140, 0),
        ]

    def _generate_neutral(self, intensity: float) -> List[DroidStep]:
        """
        R2 NEUTRAL / GREETING: Classic crisp 2-chirp droid greeting.
        """
        return [
            self._chirp(1300, 1900, 50, 20),
            self._chirp(1700, 2500, 80, 0),
        ]

    # -------------------------------------------------------------------------
    # MAIN PATTERN GENERATOR & LAYER BLENDING
    # -------------------------------------------------------------------------

    def generate_pattern(
        self,
        emotion: str,
        intensity: float = 0.5,
        intent: Optional[str] = None
    ) -> List[DroidStep]:
        """
        Generates a sequence of DroidSteps from emotion, intensity, and optional intent.
        """
        clamped_intensity = self.clamp_intensity(intensity)
        norm_emotion = self.normalize_emotion_name(emotion)
        norm_intent = self.normalize_emotion_name(intent) if intent else None

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

        # 1. Check for Emotion + Intent Layering / Blending
        if norm_intent and norm_intent != norm_emotion:
            blended = self._blend_emotion_and_intent(norm_emotion, norm_intent, clamped_intensity, generators)
            if blended:
                return blended

        # 2. Single Emotion
        gen_func = generators.get(norm_emotion, self._generate_neutral)
        return gen_func(clamped_intensity)

    def _blend_emotion_and_intent(
        self,
        emotion: str,
        intent: str,
        intensity: float,
        generators: Dict
    ) -> List[DroidStep]:
        """Blends emotion + intent pairs into cohesive R2-D2 droid phrases."""
        if (emotion, intent) in [("happy", "success"), ("excited", "success")]:
            return [
                self._chirp(1300, 1800, 45, 8),
                self._chirp(1800, 2400, 50, 10),
                self._chirp(2400, 3200, 60, 12),
                self._chirp(3200, 3600, 150 + int(80 * intensity), 0),
            ]

        if (emotion, intent) in [("thinking", "confused"), ("focused", "confused")]:
            return [
                self._chirp(1400, 1650, 35, 60),
                self._chirp(1750, 1500, 35, 50),
                self._chirp(1100, 2700, 120, 0),
            ]

        if (emotion, intent) in [("sad", "error"), ("worried", "error")]:
            return [
                self._chirp(2000, 900, 160, 40),
                self._chirp(700, 220, 90, 30),
                self._chirp(650, 180, 110, 0),
            ]

        if (emotion, intent) in [("surprised", "warning"), ("scared", "warning")]:
            return [
                self._chirp(800, 3400, 50, 15),
                self._chirp(2800, 1800, 40, 8),
                self._chirp(1800, 2800, 40, 8),
                self._chirp(2800, 1800, 60, 0),
            ]

        # Generic fallback blend
        emo_steps = generators.get(emotion, self._generate_neutral)(intensity)
        int_steps = generators.get(intent, self._generate_neutral)(intensity)
        combined = emo_steps[:2] + int_steps[-2:]
        if combined:
            combined[-1].pause_ms = 0
        return combined

    # -------------------------------------------------------------------------
    # NATURAL SENTENCE-TO-DROID PROSODY & VOCALIZATION
    # -------------------------------------------------------------------------

    def analyze_sentence_emotion(self, sentence: str) -> Tuple[str, float, Optional[str]]:
        """
        Analyzes a natural language sentence and determines:
        - emotion: canonical emotion name (e.g. 'happy', 'sad', 'confused', 'warning')
        - intensity: float (0.0 to 1.0)
        - intent: optional conversational intent (e.g. 'success', 'question')
        """
        text = sentence.strip().lower()
        if not text:
            return "neutral", 0.5, None

        # Check for inline tag e.g. [happy]
        tag_match = re.match(r'\[([a-z]+)\](.*)', text)
        if tag_match:
            tag, remaining = tag_match.groups()
            norm = self.normalize_emotion_name(tag)
            return norm, 0.7, None

        # Punctuation flags
        is_question = "?" in text or text.startswith((
            "what", "who", "where", "when", "why", "how",
            "can you", "could you", "is that", "are you", "do you"
        ))
        is_exclamation = "!" in text

        # Sentiment keyword taxonomies
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

        # Keyword evaluation with precedence
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
        intensity: Optional[float] = None
    ) -> Tuple[str, float, List[DroidStep]]:
        """
        Converts a natural language sentence into an expressive R2-D2 droid vocalization
        that mirrors the sentence's length, syllable count, prosody, and emotional contour.
        """
        clean_text = sentence.strip()
        emotion, auto_int, intent = self.analyze_sentence_emotion(clean_text)
        eff_intensity = self.clamp_intensity(intensity if intensity is not None else auto_int)

        # Strip tags if present
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

        # Determine emotional frequency contour
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
        else: # neutral / question
            base_f = int(1200)
            top_f = int(2200)
            contour = "question" if is_question else "conversational"

        total_words = len(word_tokens)

        for idx, word in enumerate(word_tokens):
            progress = (idx / max(1, total_words - 1)) if total_words > 1 else 0.5
            char_len = len(word)
            vowels = len(re.findall(r'[aeiouy]+', word.lower()))
            syllables = max(1, min(5, vowels))

            # Duration proportional to word length with speech/OLED-synchronized pacing:
            # 1-2 chars ("hi", "I", "to"): ~140-170ms
            # 3-4 chars ("the", "your", "find"): ~190-230ms
            # 5-7 chars ("found", "coffee", "robot"): ~250-320ms
            # 8+ chars ("thinking", "extraordinary"): ~350-480ms
            base_dur = max(130, min(480, 120 + (char_len - 1) * 26 + (syllables - 1) * 35))

            # Pitch for this word along the sentence arc
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

            # Clear, distinct inter-word pause (75-90ms) so every word is individually discernible
            pause = 75 if idx < total_words - 1 else 0

            # For long multi-syllable words (8+ letters), break into an expressive 2-stage compound chirp
            if char_len >= 8 and idx != total_words - 1:
                part1_dur = int(base_dur * 0.5)
                part2_dur = int(base_dur * 0.5)
                mid_f = int((cur_f + target_f) / 2 + 300)
                steps.append(DroidStep(cur_f, mid_f, part1_dur, 15, word_label=word + " (1/2)"))
                steps.append(DroidStep(mid_f, target_f, part2_dur, pause, word_label=word + " (2/2)"))
                continue

            # Sentence final word punctuation inflection
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
    # COMMAND BUILDING (ESP32 INTEGRATION)
    # -------------------------------------------------------------------------

    def build_esp32_command(
        self,
        emotion: str,
        intensity: float = 0.5,
        intent: Optional[str] = None,
        mode: str = "named"
    ) -> Union[dict, str]:
        """
        Builds a compact payload for the ESP32 firmware.
        """
        clamped_intensity = round(self.clamp_intensity(intensity), 2)
        norm_emotion = self.normalize_emotion_name(emotion)
        norm_intent = self.normalize_emotion_name(intent) if intent else None

        pattern_name = norm_emotion
        if norm_intent and norm_intent != norm_emotion:
            pattern_name = f"{norm_emotion}_{norm_intent}"

        if mode == "named":
            cmd = {
                "type": "sound",
                "pattern": pattern_name,
                "intensity": clamped_intensity
            }
            if intent:
                cmd["intent"] = norm_intent
            return cmd

        elif mode == "protocol_named":
            return f"SOUND:{pattern_name.upper()}:{clamped_intensity}"

        else:
            steps = self.generate_pattern(emotion, clamped_intensity, intent)
            if mode == "json_tones":
                return {
                    "type": "tones",
                    "tones": [s.to_tuple() for s in steps]
                }
            elif mode == "protocol_tones":
                seq = ";".join(f"{s.start_freq},{s.end_freq},{s.duration_ms},{s.pause_ms}" for s in steps)
                return f"TONES:{seq}"
            else:
                return {
                    "type": "sound",
                    "pattern": pattern_name,
                    "intensity": clamped_intensity
                }

    # -------------------------------------------------------------------------
    # AUTHENTIC CONTINUOUS-PHASE R2-D2 SYNTHESIZER (PURE PYTHON)
    # -------------------------------------------------------------------------

    def synthesize_wav(
        self,
        steps: List[DroidStep],
        sample_rate: int = 22050,
        volume: float = 0.25
    ) -> io.BytesIO:
        """
        Synthesizes DroidSteps into rich continuous-phase audio with smooth glissando sweeps.
        Phase continuity is maintained across every sample to produce authentic, analog-like droid sweeps.
        """
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

                sample_val = int(val * (max_amp / 1.15) * envelope)
                pcm_samples.append(max(-32768, min(32767, sample_val)))

            pause_count = int(sample_rate * pause_sec)
            pcm_samples.extend([0] * pause_count)

        raw_data = struct.pack(f"<{len(pcm_samples)}h", *pcm_samples)

        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(raw_data)

        wav_io.seek(0)
        return wav_io
