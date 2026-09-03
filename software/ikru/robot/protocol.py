import math

# ============================================================
# PROTOCOL CONSTANTS
# ============================================================

ALL_EMOTIONS = [
    "normal", "happy", "glee", "sad", "worried", "focused",
    "annoyed", "surprised", "skeptic", "frustrated", "unimpressed",
    "sleepy", "suspicious", "squint", "angry", "furious", "scared", "awe"
]

ALL_MOVEMENTS = [
    "forward", "backward", "left", "right", "stop", "dance", "sing"
]

# Display scroll timing constants (matching ESP32 firmware)
CHARS_PER_LINE = 8
SPEECH_LINE_HEIGHT = 18
SCROLL_MS_PER_PX = 0.030
START_PAUSE_S = 0.600
END_PAUSE_S = 0.400
BOX_ANIM_DURATION_S = 0.350


def calculate_speech_scroll_time(text):
    """
    Calculates the exact time required for text to scroll on the SSD1306 OLED screen.
    """
    if not text:
        return 0.0

    num_lines = max(1, math.ceil(len(text) / CHARS_PER_LINE))
    scroll_pixels = 64 + (num_lines * SPEECH_LINE_HEIGHT)
    scroll_time = scroll_pixels * SCROLL_MS_PER_PX
    return START_PAUSE_S + scroll_time + END_PAUSE_S
