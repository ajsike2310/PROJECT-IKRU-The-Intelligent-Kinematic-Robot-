"""
===============================================================================
PROJECT IKRU — R2-D2 SONIC EMOTION SYSTEM UNIT & BEHAVIOR TESTS
===============================================================================

Tests:
1. R2-D2 Droid Emotion Mapping (Canonical and OLED aliases)
2. Frequency Sweeps (Chirps, Glissando, Warbles, Whistles)
3. Intensity Scaling (0.0, 0.25, 0.5, 0.75, 1.0, and boundary/invalid clamping)
4. Conversational Droid State Patterns (Thinking, Processing, Success, Error, Warning, Cannot Perform)
5. Intent Layering & Blending
6. ESP32 Command Serialization (JSON and compact String protocols)
7. Fault Tolerance & Graceful Degradation
8. Continuous-Phase WAV Synthesizer Integrity
===============================================================================
"""

import math
import unittest
import wave
import io
import sys
import os

# Ensure project software directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(root_dir, "software"))

from ikru.audio import SonicEmotionEngine, DroidStep


class TestSonicEmotionEngine(unittest.TestCase):

    def setUp(self):
        self.engine = SonicEmotionEngine()

    # -------------------------------------------------------------------------
    # 1. EMOTION MAPPING & VOCABULARY
    # -------------------------------------------------------------------------

    def test_required_core_emotions(self):
        """Verify all core required emotions generate non-empty, valid DroidStep sequences."""
        core_emotions = [
            "neutral", "happy", "excited", "sad", "angry", "confused",
            "surprised", "thinking", "sleepy", "affection", "success",
            "error", "warning", "processing", "cannot_perform"
        ]

        for emotion in core_emotions:
            with self.subTest(emotion=emotion):
                pattern = self.engine.generate_pattern(emotion, intensity=0.5)
                self.assertIsInstance(pattern, list)
                self.assertGreater(len(pattern), 0, f"Pattern for {emotion} should have at least 1 step")
                for step in pattern:
                    self.assertIsInstance(step, DroidStep)
                    self.assertGreaterEqual(step.start_freq, 0)
                    self.assertGreaterEqual(step.end_freq, 0)
                    self.assertGreater(step.duration_ms, 0)
                    self.assertGreaterEqual(step.pause_ms, 0)

    def test_ikru_oled_aliases_mapping(self):
        """Verify all existing 18 IKRU OLED emotions map cleanly to sonic signatures."""
        ikru_emotions = [
            "normal", "happy", "glee", "sad", "worried", "focused",
            "annoyed", "surprised", "skeptic", "frustrated", "unimpressed",
            "sleepy", "suspicious", "squint", "angry", "furious", "scared", "awe"
        ]

        for emotion in ikru_emotions:
            with self.subTest(emotion=emotion):
                pattern = self.engine.generate_pattern(emotion, intensity=0.5)
                self.assertIsInstance(pattern, list)
                self.assertGreater(len(pattern), 0)

    # -------------------------------------------------------------------------
    # 2. R2-D2 DROID SIGNATURE BEHAVIOR (SWEEPS & CHIRPS)
    # -------------------------------------------------------------------------

    def test_happy_signature_rising_chirps(self):
        """HAPPY should produce upward frequency sweeps (chirps)."""
        pattern = self.engine.generate_pattern("happy", intensity=0.5)
        self.assertGreaterEqual(len(pattern), 2)
        # Verify first and last chirps are rising
        self.assertGreater(pattern[0].end_freq, pattern[0].start_freq)
        self.assertGreater(pattern[-1].end_freq, pattern[0].start_freq)

    def test_sad_signature_descending_slide(self):
        """SAD should produce long downward sliding chirp (whooo-oo-op)."""
        pattern = self.engine.generate_pattern("sad", intensity=0.5)
        self.assertGreaterEqual(len(pattern), 2)
        # Contains a significant downward slide
        downward = any(s.start_freq > s.end_freq and (s.start_freq - s.end_freq) > 800 for s in pattern)
        self.assertTrue(downward, "Sad pattern must contain a deep downward pitch slide")

    def test_confused_question_mark_hook(self):
        """CONFUSED should end in a high upward questioning sweep."""
        pattern = self.engine.generate_pattern("confused", intensity=0.5)
        final_step = pattern[-1]
        self.assertGreater(final_step.end_freq, final_step.start_freq + 1000)

    def test_surprised_high_speed_sweep(self):
        """SURPRISED should have an explosive rocket sweep over 2000Hz range."""
        pattern = self.engine.generate_pattern("surprised", intensity=0.8)
        self.assertGreater(pattern[0].end_freq - pattern[0].start_freq, 2000)

    def test_cannot_perform_signature(self):
        """CANNOT PERFORM should produce descending double boop."""
        pattern = self.engine.generate_pattern("cannot_perform", intensity=0.5)
        self.assertEqual(len(pattern), 2)
        self.assertGreater(pattern[0].start_freq, pattern[0].end_freq)
        self.assertGreater(pattern[1].start_freq, pattern[1].end_freq)

    # -------------------------------------------------------------------------
    # 3. INTENSITY MODULATION (0.0 to 1.0)
    # -------------------------------------------------------------------------

    def test_intensity_scaling_levels(self):
        """Test intensity modulation across 0.0, 0.25, 0.5, 0.75, 1.0."""
        levels = [0.0, 0.25, 0.5, 0.75, 1.0]

        for emotion in ["happy", "excited", "sad", "angry", "thinking", "success", "error"]:
            for intensity in levels:
                pattern = self.engine.generate_pattern(emotion, intensity=intensity)
                self.assertGreater(len(pattern), 0)
                for step in pattern:
                    if step.start_freq > 0:
                        self.assertGreaterEqual(step.start_freq, 100)
                        self.assertLessEqual(step.start_freq, 6000)
                    if step.end_freq > 0:
                        self.assertGreaterEqual(step.end_freq, 100)
                        self.assertLessEqual(step.end_freq, 6000)

    def test_intensity_boundary_clamping(self):
        """Intensity outside [0.0, 1.0] or invalid values must be clamped safely without exceptions."""
        self.assertEqual(self.engine.clamp_intensity(-0.5), 0.0)
        self.assertEqual(self.engine.clamp_intensity(1.5), 1.0)
        self.assertEqual(self.engine.clamp_intensity(100), 1.0)
        self.assertEqual(self.engine.clamp_intensity(-999), 0.0)
        self.assertEqual(self.engine.clamp_intensity("invalid"), 0.5)
        self.assertEqual(self.engine.clamp_intensity(None), 0.5)
        self.assertEqual(self.engine.clamp_intensity(float("nan")), 0.5)
        self.assertEqual(self.engine.clamp_intensity(float("inf")), 0.5)

    # -------------------------------------------------------------------------
    # 4. EMOTION & INTENT LAYER BLENDING
    # -------------------------------------------------------------------------

    def test_blended_combinations(self):
        """Test layered emotion and intent pairs."""
        pairs = [
            ("happy", "success"),
            ("thinking", "confused"),
            ("sad", "error"),
            ("surprised", "warning"),
            ("excited", "success"),
        ]

        for emo, intent in pairs:
            with self.subTest(emo=emo, intent=intent):
                pattern = self.engine.generate_pattern(emotion=emo, intensity=0.8, intent=intent)
                self.assertIsInstance(pattern, list)
                self.assertGreater(len(pattern), 1)

    # -------------------------------------------------------------------------
    # 5. ESP32 COMMAND SERIALIZATION
    # -------------------------------------------------------------------------

    def test_build_esp32_command_named_json(self):
        """Verify named JSON command output for WebSocket."""
        cmd = self.engine.build_esp32_command("happy", intensity=0.8, mode="named")
        self.assertIsInstance(cmd, dict)
        self.assertEqual(cmd["type"], "sound")
        self.assertEqual(cmd["pattern"], "happy")
        self.assertEqual(cmd["intensity"], 0.8)

    def test_build_esp32_command_protocol_string(self):
        """Verify compact string protocol output."""
        cmd = self.engine.build_esp32_command("success", intensity=0.75, mode="protocol_named")
        self.assertEqual(cmd, "SOUND:SUCCESS:0.75")

    def test_build_esp32_command_raw_tones(self):
        """Verify explicit tone sequence export."""
        cmd_json = self.engine.build_esp32_command("neutral", intensity=0.5, mode="json_tones")
        self.assertEqual(cmd_json["type"], "tones")
        self.assertIsInstance(cmd_json["tones"], list)
        self.assertEqual(len(cmd_json["tones"][0]), 4)  # (start_freq, end_freq, dur, pause)

        cmd_proto = self.engine.build_esp32_command("neutral", intensity=0.5, mode="protocol_tones")
        self.assertTrue(cmd_proto.startswith("TONES:"))
        self.assertIn(",", cmd_proto)

    # -------------------------------------------------------------------------
    # 6. FAULT TOLERANCE & MALFORMED INPUT HANDLING
    # -------------------------------------------------------------------------

    def test_graceful_handling_invalid_inputs(self):
        """Invalid emotions, None values, or empty strings must fall back gracefully to neutral."""
        invalid_emotions = ["", None, "completely_unknown_xyz", 1234, False, "   "]

        for invalid in invalid_emotions:
            with self.subTest(invalid=invalid):
                pattern = self.engine.generate_pattern(invalid)
                self.assertIsInstance(pattern, list)
                self.assertGreater(len(pattern), 0)
                cmd = self.engine.build_esp32_command(invalid)
                self.assertIsInstance(cmd, dict)
                self.assertEqual(cmd["pattern"], "neutral")

    # -------------------------------------------------------------------------
    # 7. CONTINUOUS-PHASE WAV SYNTHESIZER INTEGRITY
    # -------------------------------------------------------------------------

    def test_wav_synthesis(self):
        """Verify continuous-phase WAV generation produces a valid 22.05kHz 16-bit PCM WAV stream."""
        pattern = self.engine.generate_pattern("happy", intensity=0.8)
        wav_io = self.engine.synthesize_wav(pattern, sample_rate=22050)

        self.assertIsInstance(wav_io, io.BytesIO)
        self.assertGreater(len(wav_io.getvalue()), 44)

        with wave.open(wav_io, "rb") as w:
            self.assertEqual(w.getnchannels(), 1)  # Mono
            self.assertEqual(w.getsampwidth(), 2)  # 16-bit
            self.assertEqual(w.getframerate(), 22050)
            frames = w.getnframes()
            self.assertGreater(frames, 0)
            duration = frames / 22050.0
    # -------------------------------------------------------------------------
    # 8. SENTENCE-TO-DROID PROSODY TESTS
    # -------------------------------------------------------------------------

    def test_sentence_to_droid_pattern(self):
        """Verify sentences are analyzed and translated into expressive R2-D2 droid vocalizations."""
        sentences = [
            ("I found your keys!", "happy"),
            ("What is that over there?", "confused"),
            ("Oh no, I am so sorry...", "sad"),
            ("Warning! Danger ahead!", "warning"),
            ("Good night, I am going to sleep.", "sleepy"),
            ("Let me think about that...", "thinking"),
        ]

        for sent, expected_emo in sentences:
            with self.subTest(sent=sent):
                emo, intensity, steps = self.engine.sentence_to_droid_pattern(sent)
                self.assertEqual(emo, expected_emo)
                self.assertGreater(len(steps), 0)
                wav_io = self.engine.synthesize_wav(steps)
                self.assertGreater(len(wav_io.getvalue()), 44)


if __name__ == "__main__":
    unittest.main()
