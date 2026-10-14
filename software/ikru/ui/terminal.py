"""
TerminalUI: startup banner (mascot, clock, laptop specs) and a pinned bottom status bar with IKRU's
live eye face, state, clock, internet and robot link.

Display only. Every public method swallows its own errors, and when disabled / not a TTY every
method is a no-op (say() returns False so the caller prints normally), so the UI can never affect
the robot, mic, LLM or network code.
"""
import functools
import os
import random
import shutil
import socket
import sys
import threading
import time

from . import faces, mascot, sysinfo

GOLD, WHITE, DIM, RESET, BOLD = "\x1b[38;5;220m", "\x1b[97m", "\x1b[90m", "\x1b[0m", "\x1b[1m"

# state -> (face emotion, label)
STATES = {
    "idle": ("normal", "idle"),
    "listening": ("listening", "listening"),
    "thinking": ("thinking", "thinking"),
    "speaking": (None, "speaking"),      # face comes from the current emotion
    "sleeping": ("sleepy", "sleeping"),
}


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception:
            return False if fn.__name__ == "say" else None
    return wrapper


def _enable_vt():
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


class _LockedStdout:
    """Serialises writes from all threads with the status-bar redraw so lines never interleave."""

    def __init__(self, real, lock):
        self._real, self._lock = real, lock

    def write(self, s):
        with self._lock:
            return self._real.write(s)

    def flush(self):
        with self._lock:
            return self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


def sprite(eyes=("o", "o"), mouth="-"):
    l, r = eyes
    g, w, d = GOLD, WHITE, DIM
    return [
        f"{g}   ▄▄▄▄▄▄▄▄▄▄▄▄▄▄{RESET}",
        f"{g} ▄▄████████████████▄▄{RESET}",
        f"{w}  ▐{d}▓▓▓▓▓▓▓▓▓▓▓▓▓▓{w}▌{RESET}",
        f"{w}  ▐{d}▓{w}◖ {l} ◗{d}▓▓{w}◖ {r} ◗{d}▓{w}▌{RESET}",
        f"{w}  ▐{d}▓▓▓▓▓▓{w} {mouth} {d}▓▓▓▓▓▓{w}▌{RESET}",
        f"{w}   ▀▀▀▀▀▀▀▀▀▀▀▀▀▀{RESET}",
        f"{g}     ▀▀▀      ▀▀▀{RESET}",
    ]


class TerminalUI:
    def __init__(self, enabled=True, status_bar=False, show_mascot=True, mascot_path=None,
                 internet_check=True, mascot_style="sprite"):
        self.enabled = bool(enabled) and sys.stdout.isatty() and _enable_vt()
        self.status_bar, self.show_mascot = status_bar, show_mascot
        self.mascot_path, self.mascot_style = mascot_path, mascot_style
        self.internet_check = internet_check
        self.robot = None
        self.state, self.emotion, self._emotion_until = "idle", "normal", 0.0
        self.online = None            # None = checking, True/False
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._real_stdout = None
        self._rows = 0
        self._blink_until, self._next_blink = 0.0, time.time() + 3

    # ------------------------------------------------------------------ lifecycle
    @_safe
    def start(self):
        if not self.enabled:
            return
        self._real_stdout = sys.stdout
        sys.stdout = _LockedStdout(self._real_stdout, self._lock)
        if self.status_bar:
            self._apply_region()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ui-status")
        self._thread.start()
        if self.internet_check:
            threading.Thread(target=self._net_loop, daemon=True, name="ui-net").start()

    @_safe
    def stop(self):
        if not self.enabled or self._real_stdout is None:
            return
        self._stop.set()
        with self._lock:
            if self.status_bar and self._rows:
                self._raw(f"\x1b[r\x1b[{self._rows};1H\x1b[2K")   # drop scroll region, clear bar
            sys.stdout = self._real_stdout
            self._real_stdout = None
            print(RESET, end="", flush=True)

    # ------------------------------------------------------------------ public state API
    @_safe
    def set_state(self, state):
        self.state = state if state in STATES else "idle"
        if self.state in ("idle", "listening", "thinking", "sleeping"):
            self._emotion_until = 0.0
        self._draw()

    @_safe
    def set_emotion(self, emotion, seconds=6.0):
        self.emotion = (emotion or "normal").lower()
        self._emotion_until = time.time() + seconds
        self._draw()

    @_safe
    def say(self, emotion, text):
        """Prints IKRU's reply with its face. Returns True if handled (False -> caller prints itself)."""
        if not self.enabled:
            return False
        emotion = (emotion or "normal").lower()
        with self._lock:
            print(f"\n{BOLD}{GOLD}IKRU{RESET} {faces.face(emotion)}  {text}")
        self.set_emotion(emotion, 5.0)
        return True

    # ------------------------------------------------------------------ banner
    @_safe
    def banner(self, info_lines=()):
        if not self.enabled:
            print("=" * 50 + "\n  PROJECT IKRU - Robotic Assistant")
            for l in info_lines:
                print("  " + l)
            print("=" * 50)
            return
        art = []
        if self.show_mascot:
            # The user's own mascot image is always preferred; the built-in sprite is only a
            # fallback when the image or Pillow is unavailable.
            if self.mascot_path and os.path.isfile(self.mascot_path):
                art = mascot.render(self.mascot_path, width=22)
            if not art:
                l, r, m, _ = faces.FACES["normal"]
                art = sprite((l, r), m)
        specs = sysinfo.collect()

        def row(label, value):
            return f"{DIM}{label:<7}{RESET}{WHITE}{value}{RESET}"

        lines = list(info_lines)
        if len(lines) >= 3 and lines[1].startswith("brain") and lines[2].startswith("stt"):
            lines[1:3] = [lines[1] + "   " + lines[2]]      # brain / vision / stt on one row
        mem = specs["ram"] + (f"   {DIM}gpu{RESET} {WHITE}{specs['gpu']}" if specs["gpu"] else "")
        right = [
            f"{BOLD}{GOLD}PROJECT IKRU{RESET}  {DIM}Intelligent Kinematic Robot{RESET}",
            f"{WHITE}{time.strftime('%a %d %b %Y  %H:%M')}{RESET}",
            "",
            row("laptop", specs["machine"]),
            row("cpu", specs["cpu"]),
            row("memory", mem),
            row("system", f"{specs['os']} / Python {specs['python']}"),
            "",
            *[f"{WHITE}{l}{RESET}" for l in lines],
        ]
        art_w = max([len(_strip(a)) for a in art] + [0])
        gap = 4 if art else 0
        inner = art_w + gap + max(len(_strip(r)) for r in right)
        cols = shutil.get_terminal_size((120, 30)).columns
        inner = min(inner, max(40, cols - 6))
        n = max(len(art), len(right))
        top = (n - len(art)) // 2          # vertically centre the mascot against the text
        bc = "\x1b[38;5;214m"
        out = [f"{bc}╭{'─' * (inner + 2)}╮{RESET}"]
        for i in range(n):
            left = art[i - top] if 0 <= i - top < len(art) else ""
            txt = right[i] if i < len(right) else ""
            body = left + " " * (art_w + gap - len(_strip(left))) + txt
            pad = max(0, inner - len(_strip(body)))
            out.append(f"{bc}│{RESET} {body}{' ' * pad} {bc}│{RESET}")
        out.append(f"{bc}╰{'─' * (inner + 2)}╯{RESET}")
        print("\n".join(out) + "\n")

    # ------------------------------------------------------------------ internals
    def _raw(self, s):
        self._real_stdout.write(s)
        self._real_stdout.flush()

    def _apply_region(self):
        cols, rows = shutil.get_terminal_size((100, 30))
        if rows < 8:
            self.status_bar = False
            return
        self._rows = rows
        # scroll region = all rows but the last; park cursor inside it
        self._raw(f"\x1b[1;{rows - 1}r\x1b[{rows - 1};1H")

    def _face_emotion(self):
        if self.robot is not None and getattr(self.robot, "connected", True) is False:
            return "offline"
        base, _ = STATES[self.state]
        if base is not None:
            return base
        if time.time() < self._emotion_until:
            return self.emotion
        return "normal"

    def _draw(self):
        if not (self.enabled and self.status_bar and self._real_stdout and self._rows):
            return
        cols, rows = shutil.get_terminal_size((100, 30))
        with self._lock:
            if rows != self._rows:
                self._apply_region()
            emo = self._face_emotion()
            blink = time.time() < self._blink_until
            face = faces.face(emo, blink=blink)
            net = {None: f"\x1b[93m● checking{RESET}", True: f"\x1b[92m● online{RESET}",
                   False: f"\x1b[91m● offline{RESET}"}[self.online]
            if self.robot is None or getattr(self.robot, "connected", None) is None:
                link = f"{DIM}robot ?{RESET}"
            elif self.robot.connected:
                link = f"\x1b[92m● robot{RESET}"
            else:
                link = f"\x1b[91m● robot lost{RESET}"
            label = STATES[self.state][1] if self.state != "speaking" else f"speaking [{self.emotion}]"
            bar = f" {face}  {GOLD}{label}{RESET}  {DIM}│{RESET} {time.strftime('%H:%M:%S')} {DIM}│{RESET} net {net} {DIM}│{RESET} {link}"
            self._raw(f"\x1b7\x1b[{self._rows};1H\x1b[2K{bar}\x1b8")

    def _run(self):
        while not self._stop.wait(0.5):
            try:
                now = time.time()
                if now >= self._next_blink:
                    self._blink_until = now + 0.18
                    self._next_blink = now + random.uniform(2.5, 6.0)
                self._draw()
            except Exception:
                pass

    def _net_loop(self):
        while not self._stop.is_set():
            ok = False
            for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
                try:
                    socket.create_connection(host, timeout=1.5).close()
                    ok = True
                    break
                except OSError:
                    pass
            self.online = ok
            self._stop.wait(5.0)


def _strip(s):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)
