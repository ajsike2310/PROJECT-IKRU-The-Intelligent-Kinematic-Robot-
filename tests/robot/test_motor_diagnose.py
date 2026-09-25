"""
Unit tests for the motor wiring diagnosis in test_motors.py. No robot needed:
    python -m pytest tests/robot/test_motor_diagnose.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_motors import diagnose


def answers(f="y", b="y", l="y", r="y"):
    return {"FORWARD": f, "BACKWARD": b, "LEFT": l, "RIGHT": r}


def joined(findings):
    return " ".join(findings).lower()


def test_all_good():
    assert "all motors ok" in joined(diagnose(answers()))


def test_nothing_moves_points_to_power():
    out = joined(diagnose(answers("n", "n", "n", "n")))
    assert "vm" in out and "nsleep" in out and "gnd" in out


def test_forward_backward_swapped_means_both_motors_reversed():
    out = joined(diagnose(answers(f="r", b="r")))
    assert "both motors are reversed" in out
    assert "left and right are swapped" not in out


def test_left_right_swapped_means_sides_swapped():
    out = joined(diagnose(answers(l="r", r="r")))
    assert "left and right are swapped" in out


def test_spin_instead_of_straight_means_one_motor_reversed():
    out = joined(diagnose(answers(f="w", b="w", l="w", r="w")))
    assert "one motor is wired backwards" in out


def test_one_wheel_only():
    out = joined(diagnose(answers(f="o", b="o")))
    assert "only one wheel turns" in out
    assert "forward, backward" in out


def test_forward_only_failure_suggests_safety_brake():
    out = joined(diagnose(answers(f="n")))
    assert "safety brake" in out


def test_blocked_forward_reported_as_brake_not_fault():
    out = joined(diagnose(answers(f="n"), blocked=["FORWARD"]))
    assert "blocked by the ultrasonic safety brake" in out
    assert "only forward fails" not in out


def test_single_turn_reversed():
    out = joined(diagnose(answers(l="r")))
    assert "only one of left/right is reversed" in out
