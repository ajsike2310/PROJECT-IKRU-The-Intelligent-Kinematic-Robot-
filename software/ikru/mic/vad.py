"""
Voice Activity Detection (VAD) for IKRU's microphone.

SpeechSegmenter is a pure state machine: feed it 16 kHz int16 frames together with
their speech probability and it tells you when speech starts and hands back the full
utterance when speech ends. load_vad() returns the probability model (Silero, with a
webrtcvad fallback).
"""
from collections import deque

import numpy as np

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512                                   # Silero requires 512 samples @ 16 kHz
FRAME_MS = FRAME_SAMPLES * 1000 / SAMPLE_RATE         # 32 ms


class SpeechSegmenter:
    """
    Turns a stream of (frame, speech_prob) into utterances.

    process() returns a list of events:
        ("start", None)       speech just began
        ("end", pcm_bytes)    speech ended; pcm_bytes is the whole utterance incl. pre-roll
    """

    def __init__(self, threshold=0.5, silence_ms=500, min_speech_ms=250,
                 max_utterance_s=12.0, preroll_ms=300, start_frames=2):
        self.threshold = threshold
        self.neg_threshold = max(0.05, threshold - 0.15)  # hysteresis
        self.silence_frames = max(1, int(round(silence_ms / FRAME_MS)))
        self.min_speech_frames = max(1, int(round(min_speech_ms / FRAME_MS)))
        self.max_frames = max(1, int(round(max_utterance_s * 1000 / FRAME_MS)))
        self.start_frames = start_frames
        self._preroll = deque(maxlen=max(1, int(round(preroll_ms / FRAME_MS))))
        self.reset()

    def reset(self):
        self.in_speech = False
        self._frames = []
        self._speech_run = 0      # consecutive speech frames before start
        self._silence_run = 0     # consecutive non-speech frames while in speech
        self._voiced = 0          # voiced frames inside the current utterance
        self._preroll.clear()

    def process(self, frame: bytes, prob: float):
        events = []
        if not self.in_speech:
            self._preroll.append(frame)
            self._speech_run = self._speech_run + 1 if prob >= self.threshold else 0
            if self._speech_run >= self.start_frames:
                self.in_speech = True
                self._frames = list(self._preroll)
                self._preroll.clear()
                self._voiced = self._speech_run
                self._silence_run = 0
                events.append(("start", None))
            return events

        self._frames.append(frame)
        if prob < self.neg_threshold:
            self._silence_run += 1
        else:
            self._silence_run = 0
            if prob >= self.threshold:
                self._voiced += 1

        if self._silence_run >= self.silence_frames or len(self._frames) >= self.max_frames:
            events.append(self._finish())
        return events

    def _finish(self):
        # Trim the trailing silence (keep a little tail so words aren't clipped)
        keep_tail = min(self._silence_run, 4)
        frames = self._frames[:len(self._frames) - self._silence_run + keep_tail]
        voiced = self._voiced
        self.reset()
        if voiced < self.min_speech_frames:
            return ("drop", None)
        return ("end", b"".join(frames))


def load_vad(kind="silero"):
    """Returns (name, fn) where fn(frame_bytes) -> speech probability 0..1."""
    if kind == "silero":
        try:
            import torch
            from silero_vad import load_silero_vad
            model = load_silero_vad(onnx=True)

            def silero_prob(frame):
                audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
                return float(model(torch.from_numpy(audio), SAMPLE_RATE))

            return "silero", silero_prob
        except Exception as e:
            print(f"[VAD] Silero unavailable ({e}), falling back to webrtcvad.")

    import webrtcvad
    vad = webrtcvad.Vad(3)
    sub = int(SAMPLE_RATE * 0.010) * 2  # webrtcvad takes 10/20/30 ms slices; 10 ms in bytes

    def webrtc_prob(frame):
        slices = [frame[i:i + sub] for i in range(0, len(frame) - sub + 1, sub)]
        voiced = sum(vad.is_speech(s, SAMPLE_RATE) for s in slices)
        return voiced / max(1, len(slices))

    return "webrtc", webrtc_prob
