"""Terminal 'eye' faces for IKRU's emotions (mirrors the OLED emotion names in chat/parser.py)."""

# name: (left eye, right eye, mouth, ANSI colour)
FACES = {
    "normal":       ("o", "o", "-", "37"),
    "happy":        ("^", "^", "u", "92"),
    "glee":         ("^", "^", "D", "93"),
    "sad":          ("T", "T", "n", "94"),
    "worried":      ("o", "o", "~", "96"),
    "focused":      ("O", "O", "_", "97"),
    "annoyed":      ("-", "-", "_", "33"),
    "surprised":    ("O", "O", "o", "95"),
    "skeptic":      ("o", "-", "~", "36"),
    "frustrated":   (">", "<", "~", "91"),
    "unimpressed":  ("-", "-", "-", "90"),
    "sleepy":       ("-", "-", "z", "34"),
    "suspicious":   ("o", "-", "_", "35"),
    "squint":       (">", "<", "-", "33"),
    "angry":        (">", "<", "^", "31"),
    "furious":      ("#", "#", "A", "91"),
    "scared":       ("0", "0", "o", "95"),
    "awe":          ("*", "*", "o", "93"),
    "listening":    ("O", "O", "-", "96"),
    "thinking":     ("o", "o", ".", "93"),
    "offline":      ("x", "x", "_", "90"),
}


def face(emotion: str = "normal", blink: bool = False, color: bool = True) -> str:
    l, r, m, col = FACES.get((emotion or "normal").lower(), FACES["normal"])
    if blink and emotion not in ("sleepy", "unimpressed", "offline"):
        l = r = "-"
    s = f"( {l} {m} {r} )"
    return f"\x1b[{col}m{s}\x1b[0m" if color else s
