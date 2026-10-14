"""
===============================================================================
PROJECT IKRU — MOTOR DIAGNOSTIC & WIRING TESTER
===============================================================================
Connects to the ESP32 Controller (main firmware) via WebSocket and tests the DRV8833 motors.

  DRV8833 wiring:  IN1=GPIO26 IN2=GPIO27 (left, OUT1/OUT2)  IN3=GPIO14 IN4=GPIO12 (right, OUT3/OUT4)
                   EEP=GPIO13  ULT=GPIO32 (optional)  VCC=battery+ (2.7-10.8 V)  GND common

  1. Guided wiring check  — runs every direction, asks what IKRU did, then tells
                            you what's wrong (reversed motor, swapped sides, power...)
  2. Single move          — any direction for N seconds
  3. Hold forward         — runs until Enter (for voltmeter / LED checks)
  4. Keyboard drive       — WASD, Space = stop
  5. Emergency STOP

Every move ends with STOP, even on Ctrl+C, errors or a dropped connection.
Tip: put IKRU on a stand (wheels off the ground) for the first run.

    python tests/robot/test_motors.py [--ip 192.168.4.200] [--duration 2] [--auto]
===============================================================================
"""

import sys
import time
import json
import argparse
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "software"))
from ikru.net import Diagnosis, find_robot
from ikru.net.netinfo import HUB_ROBOT_IP

try:
    import websocket
except ImportError:
    print("Error: 'websocket-client' is required. Install via: pip install websocket-client")
    sys.exit(1)


DIRECTIONS = ["FORWARD", "BACKWARD", "LEFT", "RIGHT"]
EXPECTED = {
    "FORWARD": "straight forward",
    "BACKWARD": "straight backward",
    "LEFT": "turn / spin to the LEFT",
    "RIGHT": "turn / spin to the RIGHT",
}
ANSWER_HELP = (
    "  y = yes, correct\n"
    "  r = reversed (went the opposite way)\n"
    "  w = wrong kind of motion (spun instead of going straight, or went straight instead of turning)\n"
    "  o = only one wheel turned\n"
    "  n = nothing moved"
)


# ---------------------------------------------------------------------------
# Diagnosis (pure logic — unit tested in test_motor_diagnose.py)
# ---------------------------------------------------------------------------

def diagnose(answers, blocked=()):
    """
    answers: {"FORWARD": "y|r|w|o|n", "BACKWARD": ..., "LEFT": ..., "RIGHT": ...}
    blocked: directions the firmware's obstacle safety brake refused.
    Returns a list of human-readable findings.
    """
    a = {d: answers.get(d, "y") for d in DIRECTIONS}
    findings = []

    if all(v == "y" for v in a.values()):
        return ["All motors OK: every direction moved as expected."]

    if all(v == "n" for v in a.values()):
        return [
            "Nothing moves at all. Check: battery switch / VCC (VM) on the DRV8833, "
            "EEP (nSLEEP) on GPIO13 is HIGH, and a common GND between ESP32 and DRV8833."
        ]

    for d in blocked:
        findings.append(f"{d} was blocked by the ultrasonic safety brake. Clear the path and retest.")

    if a["FORWARD"] == "n" and "FORWARD" not in blocked and all(a[d] != "n" for d in DIRECTIONS if d != "FORWARD"):
        findings.append(
            "Only FORWARD fails. That's usually the ultrasonic safety brake (obstacle < threshold "
            "or a bad sensor reading). Run test_ultrasonic.py."
        )

    if any(v == "o" for v in a.values()):
        dirs = ", ".join(d for d in DIRECTIONS if a[d] == "o")
        findings.append(
            f"Only one wheel turns ({dirs}). The other motor isn't driven: check its DRV8833 "
            "channel (IN1/IN2 or IN3/IN4 from the ESP32, OUT1/OUT2 or OUT3/OUT4 to the motor), its solder joints and motor leads."
        )

    if any(a[d] == "w" for d in DIRECTIONS):
        findings.append(
            "One motor is wired backwards (FORWARD spins in place / turns go straight). "
            "Swap the two leads of the motor that spins backward on FORWARD "
            "(or swap its MOTOR_IN pins in firmware)."
        )

    if a["FORWARD"] == "r" and a["BACKWARD"] == "r":
        findings.append(
            "FORWARD and BACKWARD are swapped: both motors are reversed. "
            "Swap the leads on both motors (or swap MOTOR_IN1<->MOTOR_IN2 and MOTOR_IN3<->MOTOR_IN4 in firmware)."
        )
    elif a["FORWARD"] == "r" or a["BACKWARD"] == "r":
        findings.append("Only one of FORWARD/BACKWARD is reversed. Check the moveForward()/moveBackward() pin logic in firmware.")

    if a["LEFT"] == "r" and a["RIGHT"] == "r" and a["FORWARD"] in ("y", "r") and a["BACKWARD"] in ("y", "r"):
        findings.append(
            "LEFT and RIGHT are swapped: the left and right motors are on each other's "
            "DRV8833 channels. Swap OUT1/OUT2 with OUT3/OUT4 (or swap IN1/IN2 with IN3/IN4 in firmware)."
        )
    elif a["LEFT"] == "r" or a["RIGHT"] == "r":
        if not (a["LEFT"] == "r" and a["RIGHT"] == "r"):
            findings.append("Only one of LEFT/RIGHT is reversed. Check the moveLeft()/moveRight() pin logic in firmware.")

    partial_n = [d for d in DIRECTIONS if a[d] == "n" and d != "FORWARD"]
    if partial_n:
        findings.append(
            f"{', '.join(partial_n)} did nothing while other moves worked. "
            "Check that the firmware handles the command, and look for a loose IN pin."
        )

    return findings or ["Mixed results. Rerun the guided check, watching each wheel individually."]


# ---------------------------------------------------------------------------
# Driving helpers
# ---------------------------------------------------------------------------

def _poll_events(ws, wait_s):
    """Waits up to wait_s, returning any firmware event dicts received (e.g. obstacle_blocked)."""
    events = []
    ws.settimeout(max(0.01, wait_s))
    try:
        msg = ws.recv()
        if msg and msg.startswith("{"):
            try:
                events.append(json.loads(msg))
            except ValueError:
                pass
    except websocket.WebSocketTimeoutException:
        pass
    return events


def drive(ws, cmd, seconds):
    """Sends cmd, holds for `seconds`, ALWAYS sends STOP. Returns the obstacle distance if blocked."""
    blocked_at = None
    ws.send(cmd)
    end = time.time() + seconds
    try:
        while time.time() < end:
            for ev in _poll_events(ws, min(0.1, end - time.time())):
                if ev.get("event") == "obstacle_blocked":
                    blocked_at = ev.get("distance_cm")
                elif ev.get("event") == "motor_fault":
                    print("  [!] DRV8833 reported a FAULT (over-current / over-heat / low battery)")
    finally:
        safe_stop(ws)
    if blocked_at is not None:
        print(f"  [!] Safety brake blocked {cmd} (obstacle at {blocked_at} cm)")
    return blocked_at


def safe_stop(ws):
    try:
        ws.send("STOP")
    except Exception:
        pass


def _ask(prompt, default=""):
    try:
        return input(prompt).strip().lower() or default
    except EOFError:
        return default


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def guided_check(ws, seconds=1.5, auto=False):
    print("\n[Guided wiring check]")
    if auto:
        print("  Auto mode: cycling every direction (no questions).")
    else:
        print("  Watch IKRU after each move and answer:\n" + ANSWER_HELP)
        _ask("\nPress Enter to start...")

    answers, blocked = {}, []
    for d in DIRECTIONS:
        print(f"\n  -> {d} for {seconds:.1f}s (expected: {EXPECTED[d]})")
        if drive(ws, d, seconds) is not None:
            blocked.append(d)
        time.sleep(0.6)
        if auto:
            continue
        ans = ""
        while ans not in ("y", "r", "w", "o", "n"):
            ans = _ask(f"  Did IKRU {EXPECTED[d]}? [y/r/w/o/n] (default y): ", "y")
        answers[d] = ans

    if auto:
        print("\n[+] Auto cycle complete.")
        return
    print("\n" + "-" * 60 + "\n  DIAGNOSIS\n" + "-" * 60)
    for f in diagnose(answers, blocked):
        print(f"  * {f}")


def single_move(ws, default_s):
    for i, d in enumerate(DIRECTIONS, 1):
        print(f"  {i}. {d}")
    choice = _ask("  Direction [1-4]: ")
    if choice not in ("1", "2", "3", "4"):
        print("  Cancelled.")
        return
    try:
        seconds = float(_ask(f"  Seconds (default {default_s}): ", str(default_s)))
    except ValueError:
        seconds = default_s
    d = DIRECTIONS[int(choice) - 1]
    print(f"  -> {d} for {seconds:.1f}s")
    drive(ws, d, seconds)
    print("  [+] STOP sent.")


def hold_forward(ws):
    print("\n[+] Continuous FORWARD is ACTIVE. Check the DRV8833 input pins and motor terminals.")
    ws.send("FORWARD")
    try:
        _ask("Press [Enter] to STOP: ")
    finally:
        safe_stop(ws)
    print("[+] STOP sent.")


def keyboard_drive(ws):
    keymap = {"w": "FORWARD", "s": "BACKWARD", "a": "LEFT", "d": "RIGHT"}
    try:
        import msvcrt
    except ImportError:
        msvcrt = None

    if msvcrt is None:
        print("\n[Keyboard drive] Type w/a/s/d + Enter to move 0.5s, q to quit.")
        while True:
            k = _ask("  > ", "q")
            if k == "q":
                return
            if k in keymap:
                drive(ws, keymap[k], 0.5)
        return

    # Hold a key to drive. Windows waits ~0.5s before repeating a held key,
    # so we stop 0.6s after the last key event.
    release_s = 0.6
    print("\n[Keyboard drive] Hold W/A/S/D to move, U/J = fork up/down (0-45 deg, GPIO 15), "
          "SPACE = stop, Q = quit.")
    current, last_key, fork = "STOP", 0.0, 0
    ws.send("FORK:0")
    try:
        while True:
            if msvcrt.kbhit():
                k = msvcrt.getwch().lower()
                if k == "q":
                    break
                if k in ("u", "j"):
                    fork = max(0, min(45, fork + (2 if k == "u" else -2)))
                    ws.send(f"FORK:{fork}")
                    print(f"\r  {current:<10} fork {fork:>2} deg ", end="", flush=True)
                    continue
                cmd = keymap.get(k, "STOP")
                last_key = time.time()
                if cmd != current:
                    ws.send(cmd)
                    current = cmd
                    print(f"\r  {cmd:<10} fork {fork:>2} deg ", end="", flush=True)
            elif current != "STOP" and time.time() - last_key > release_s:
                ws.send("STOP")
                current = "STOP"
                print(f"\r  {'STOP':<10} fork {fork:>2} deg ", end="", flush=True)
            for ev in _poll_events(ws, 0.02):
                if ev.get("event") == "obstacle_blocked":
                    print(f"\n  [!] Safety brake: obstacle at {ev.get('distance_cm')} cm")
                elif ev.get("event") == "motor_fault":
                    print("\n  [!] DRV8833 FAULT (over-current / over-heat / low battery)")
    finally:
        safe_stop(ws)
        print("\n  [+] Keyboard drive ended (STOP sent).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_motor_test(ip=HUB_ROBOT_IP, port=81, duration=2.0, auto=False):
    print("\n" + "=" * 60)
    print("  PROJECT IKRU — Motor & DRV8833 Diagnostic Tool")
    print("=" * 60)

    result = find_robot([ip], port=port)
    if isinstance(result, Diagnosis):
        print(f"[-] Could not find the robot: {result.message}")
        for hint in result.hints:
            print(f"    -> {hint}")
        return

    ws_url = f"ws://{result.ip}:{port}/"
    try:
        print(f"Connecting to ESP32 at {ws_url}...")
        ws = websocket.create_connection(ws_url, timeout=3.0)
        print(f"[+] Connected to {result.describe()}!")
    except Exception as e:
        print(f"[-] Found {result.ip} but the WebSocket failed: {e}")
        return

    try:
        if auto:
            guided_check(ws, seconds=1.5, auto=True)
            return

        while True:
            print("\nSelect a motor test:")
            print("  1. Guided wiring check (all directions + diagnosis)")
            print(f"  2. Single move (default {duration:.1f}s)")
            print("  3. Hold FORWARD until Enter (voltmeter / LED check)")
            print("  4. Keyboard drive (WASD)")
            print("  5. Emergency STOP")
            print("  q. Quit")
            choice = _ask("\nEnter choice [1-5/q] (default: 1): ", "1")

            if choice == "1":
                guided_check(ws)
            elif choice == "2":
                single_move(ws, duration)
            elif choice == "3":
                hold_forward(ws)
            elif choice == "4":
                keyboard_drive(ws)
            elif choice == "5":
                safe_stop(ws)
                print("[+] STOP sent.")
            elif choice == "q":
                break
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
    except (websocket.WebSocketConnectionClosedException, ConnectionResetError, OSError) as e:
        print(f"\n[-] Connection lost: {e}. The firmware stops the motors when the link drops.")
    finally:
        safe_stop(ws)
        try:
            ws.close()
        except Exception:
            pass
        print("[+] STOP sent. Disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IKRU Motor Diagnostic")
    parser.add_argument("--ip", default=HUB_ROBOT_IP, help="ESP32 Robot Controller IP")
    parser.add_argument("--port", type=int, default=81, help="WebSocket port (default: 81)")
    parser.add_argument("--duration", type=float, default=2.0, help="Default seconds for a single move")
    parser.add_argument("--auto", action="store_true", help="Cycle all directions once without questions")
    args = parser.parse_args()

    run_motor_test(ip=args.ip, port=args.port, duration=args.duration, auto=args.auto)
