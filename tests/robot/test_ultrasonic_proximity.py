"""
Offline (no hardware) tests for the ultrasonic ProximityMonitor logic.

A fake robot feeds scripted distances so zone classification, reflexes,
pause behaviour and LLM context strings can be verified without the ESP32.
Run with:  pytest tests/robot/test_ultrasonic_proximity.py -v
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "software"))

from ikru.robot.proximity import ProximityMonitor


class FakeRobot:
    """Minimal stand-in for RobotController that records reflex calls."""

    def __init__(self, distances, connected=True):
        self.connected = connected
        self.distances = list(distances)
        self.calls = []

    def get_distance(self, timeout=0.6):
        # Hold the last reading once the script is exhausted.
        if len(self.distances) > 1:
            return self.distances.pop(0)
        return self.distances[0]

    def __getattr__(self, name):
        # stop(), scared(), gasp(), backward(), surprised(), ... -> record the call
        def _record(*args, **kwargs):
            self.calls.append(name)
        return _record


def run_monitor(distances, settle=0.4, paused=False, connected=True):
    robot = FakeRobot(distances, connected=connected)
    mon = ProximityMonitor(robot, poll_interval=0.02)
    if paused:
        mon.pause()
    mon.start()
    time.sleep(settle)
    mon.stop()
    time.sleep(0.05)
    return mon, robot


def test_initial_state_is_clear():
    mon = ProximityMonitor(FakeRobot([100.0]))
    assert mon.get_zone() == "CLEAR"
    assert mon.get_distance() == 999.0


def test_zone_classification():
    for dist, zone in [(5.0, "DANGER"), (20.0, "CAUTION"), (80.0, "CLEAR"), (999.0, "CLEAR")]:
        mon, _ = run_monitor([dist], settle=0.15)
        assert mon.get_zone() == zone, f"{dist} cm should be {zone}"
        assert mon.get_distance() == dist


def test_zone_boundaries():
    mon, _ = run_monitor([ProximityMonitor.DANGER_THRESHOLD_CM], settle=0.15)
    assert mon.get_zone() == "CAUTION"  # 10.0 is the first caution value
    mon, _ = run_monitor([ProximityMonitor.CAUTION_THRESHOLD_CM], settle=0.15)
    assert mon.get_zone() == "CAUTION"  # 30.0 still caution
    mon, _ = run_monitor([ProximityMonitor.CAUTION_THRESHOLD_CM + 0.1], settle=0.15)
    assert mon.get_zone() == "CLEAR"


def test_timeout_reading_is_clear():
    # Negative / zero readings mean sensor timeout and must not trigger DANGER.
    for dist in (-1.0, 0.0):
        mon, robot = run_monitor([dist], settle=0.15)
        assert mon.get_zone() == "CLEAR"
        assert "stop" not in robot.calls


def test_danger_reflex_fires_once_within_cooldown():
    _, robot = run_monitor([5.0], settle=0.4)
    for call in ("stop", "scared", "gasp", "backward", "worried"):
        assert call in robot.calls
    assert robot.calls.count("stop") == 1  # 2s cooldown prevents repeats


def test_caution_reflex_only_when_entering_from_clear():
    _, robot = run_monitor([100.0, 100.0, 20.0, 20.0, 20.0], settle=1.5)
    assert robot.calls.count("surprised") == 1
    assert "look_top" in robot.calls and "normal" in robot.calls
    assert "stop" not in robot.calls


def test_paused_suppresses_reflex_but_updates_distance():
    mon, robot = run_monitor([5.0], settle=0.3, paused=True)
    assert mon.get_zone() == "DANGER"
    assert mon.get_distance() == 5.0
    assert robot.calls == []


def test_resume_reenables_reflex():
    robot = FakeRobot([5.0])
    mon = ProximityMonitor(robot, poll_interval=0.02)
    mon.pause()
    mon.start()
    time.sleep(0.2)
    assert robot.calls == []
    mon.resume()
    time.sleep(0.3)
    mon.stop()
    assert "stop" in robot.calls


def test_disconnected_robot_is_not_polled():
    mon, robot = run_monitor([5.0], settle=0.2, connected=False)
    assert mon.get_distance() == 999.0
    assert robot.calls == []


def test_sensor_errors_do_not_kill_the_loop():
    class FlakyRobot(FakeRobot):
        n = 0

        def get_distance(self, timeout=0.6):
            FlakyRobot.n += 1
            if FlakyRobot.n < 3:
                raise OSError("socket glitch")
            return 50.0

    robot = FlakyRobot([50.0])
    mon = ProximityMonitor(robot, poll_interval=0.02)
    mon.start()
    time.sleep(0.3)
    mon.stop()
    assert mon.get_distance() == 50.0


def test_start_is_idempotent():
    mon = ProximityMonitor(FakeRobot([100.0]), poll_interval=0.02)
    mon.start()
    first = mon.thread
    mon.start()
    assert mon.thread is first
    mon.stop()


def test_sensor_context_strings():
    mon = ProximityMonitor(FakeRobot([100.0]))
    cases = [
        (5.0, "DANGER", "DANGER ALERT"),
        (20.0, "CAUTION", "CAUTION"),
        (60.0, "CLEAR", "Path clear (60.0 cm)"),
        (400.0, "CLEAR", "Path clear (>100 cm)"),
        (-1.0, "CLEAR", "Path clear (>100 cm)"),
    ]
    for dist, zone, expected in cases:
        mon.current_distance_cm = dist
        mon.current_zone = zone
        assert expected in mon.get_sensor_context()
