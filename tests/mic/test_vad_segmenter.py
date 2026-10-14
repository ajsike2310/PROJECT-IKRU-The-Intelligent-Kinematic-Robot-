"""Unit tests for the VAD speech segmenter (no microphone needed)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "software"))
from ikru.mic.vad import SpeechSegmenter, FRAME_SAMPLES, FRAME_MS

FRAME_BYTES = FRAME_SAMPLES * 2


def frame(tag):
    """A distinguishable fake frame (content is irrelevant to the segmenter)."""
    return bytes([tag % 256]) * FRAME_BYTES


def feed(seg, probs):
    events = []
    for i, p in enumerate(probs):
        for ev in seg.process(frame(i), p):
            events.append((i, *ev))
    return events


def frames_for(ms):
    return int(round(ms / FRAME_MS))


def test_start_needs_two_speech_frames():
    seg = SpeechSegmenter()
    events = feed(seg, [0.0, 0.9, 0.1, 0.9, 0.9])
    assert [(i, k) for i, k, _ in events] == [(4, "start")]


def test_utterance_ends_after_silence_and_includes_preroll():
    seg = SpeechSegmenter(silence_ms=500, preroll_ms=300)
    lead = [0.0] * 20
    speech = [0.9] * 20
    silence = [0.0] * frames_for(500)
    events = feed(seg, lead + speech + silence)
    kinds = [k for _, k, _ in events]
    assert kinds == ["start", "end"]
    end_idx, _, pcm = events[-1]
    assert end_idx == len(lead) + len(speech) + len(silence) - 1
    # Pre-roll: first bytes come from before the speech started
    first_frame_tag = pcm[0]
    assert first_frame_tag < len(lead)


def test_short_blip_is_dropped():
    seg = SpeechSegmenter(min_speech_ms=250)
    events = feed(seg, [0.9, 0.9] + [0.0] * frames_for(600))
    kinds = [k for _, k, _ in events]
    assert kinds == ["start", "drop"]


def test_long_utterance_is_force_cut():
    seg = SpeechSegmenter(max_utterance_s=2.0)
    events = feed(seg, [0.9] * frames_for(5000))
    ends = [e for e in events if e[1] == "end"]
    assert len(ends) >= 2
    assert all(len(pcm) <= frames_for(2000) * FRAME_BYTES for _, _, pcm in ends)


def test_hysteresis_keeps_flicker_in_one_segment():
    seg = SpeechSegmenter(threshold=0.5, silence_ms=500)
    # Probabilities dipping to 0.4 (above neg threshold 0.35) must not count as silence
    flicker = [0.9, 0.9] + [0.9, 0.4] * 30
    events = feed(seg, flicker + [0.0] * frames_for(500))
    kinds = [k for _, k, _ in events]
    assert kinds == ["start", "end"]


def test_brief_pause_does_not_split():
    seg = SpeechSegmenter(silence_ms=500)
    probs = [0.9] * 15 + [0.0] * frames_for(300) + [0.9] * 15 + [0.0] * frames_for(500)
    kinds = [k for _, k, _ in feed(seg, probs)]
    assert kinds == ["start", "end"]
