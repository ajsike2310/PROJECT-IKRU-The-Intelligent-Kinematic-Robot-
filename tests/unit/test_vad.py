"""TC8-TC9: speech segmenter. Technique: Boundary Value Analysis on the speech threshold."""


def _frame(vad):
    return b"\x01\x00" * vad.FRAME_SAMPLES


def _run(vad, probs, **kwargs):
    seg = vad.SpeechSegmenter(**kwargs)
    events = []
    for p in probs:
        events += seg.process(_frame(vad), p)
    return events


def test_tc8_threshold_boundary(vad):
    # threshold = 0.5: exactly 0.5 counts as speech, 0.49 does not
    assert ("start", None) in _run(vad, [0.5, 0.5])
    assert _run(vad, [0.49, 0.49]) == []


def test_tc9_single_speech_frame_does_not_start(vad):
    # start_frames = 2: one loud frame followed by silence is ignored
    assert _run(vad, [0.9, 0.0, 0.9, 0.0]) == []


def test_utterance_ends_after_silence(vad):
    probs = [0.9] * 12 + [0.0] * 20
    kinds = [kind for kind, _ in _run(vad, probs)]
    assert kinds == ["start", "end"]


def test_short_burst_is_dropped(vad):
    # Fewer voiced frames than min_speech_ms -> dropped, not transcribed
    probs = [0.9] * 3 + [0.0] * 20
    kinds = [kind for kind, _ in _run(vad, probs)]
    assert kinds == ["start", "drop"]
