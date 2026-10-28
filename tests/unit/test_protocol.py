"""TC6-TC7: OLED scroll-time calculation. Technique: Boundary Value Analysis."""
import pytest


def test_tc6_scroll_time_empty_text_is_zero(protocol):
    # Lower boundary: no text
    assert protocol.calculate_speech_scroll_time("") == 0.0


def test_tc7_scroll_time_line_wrap_boundary(protocol):
    # Boundary at CHARS_PER_LINE (8): 8 chars fit one line, 9 chars need two
    one_line = protocol.calculate_speech_scroll_time("a" * 8)
    two_lines = protocol.calculate_speech_scroll_time("a" * 9)
    assert one_line == pytest.approx(3.46)
    assert two_lines - one_line == pytest.approx(18 * 0.030)
    assert protocol.calculate_speech_scroll_time("a") == pytest.approx(one_line)
