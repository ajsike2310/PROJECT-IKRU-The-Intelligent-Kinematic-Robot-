"""
Calibrates IKRU's roaming speeds so the world model's dead reckoning (and the
leash that keeps IKRU near its home spot) matches reality.

Put IKRU on the FLOOR or a large clear surface, then run:
    python tests/robot/test_roam_calibration.py
It drives forward for 1 s and spins left for 1 s at the roam speed, asks you what
you measured, and saves forward_cm_per_s / turn_deg_per_s into config.json.
"""
import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "software"))

from ikru.robot import RobotController

CONFIG = os.path.join(ROOT, "config.json")


def ask_float(prompt):
    while True:
        try:
            return float(input(prompt).strip())
        except ValueError:
            print("  Please enter a number.")


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)
    auto = config.setdefault("autonomous", {})
    speed = int(auto.get("roam_speed_pct", 55))

    robot = RobotController(ip=config.get("robot_ip", "192.168.4.200"))
    if not robot.connected:
        print("[FAIL] Robot not connected.")
        return
    robot.setup_done()
    time.sleep(2.0)
    robot.set_speed(speed)
    print(f"Roam speed set to {speed}% (needs firmware with SPEED: support; older firmware runs at 100%).")

    input("\nMark IKRU's position, then press Enter to drive FORWARD for 1.0 s...")
    robot.forward(1.0, check_proximity=False)
    cm = ask_float("How many cm did it travel? ")

    input("\nMark IKRU's heading, then press Enter to spin LEFT for 1.0 s...")
    robot.left(1.0)
    deg = ask_float("How many degrees did it turn? ")

    robot.set_speed(100)
    robot.close()

    auto["forward_cm_per_s"] = round(cm, 1)
    auto["turn_deg_per_s"] = round(deg, 1)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"\nSaved: forward_cm_per_s={cm:.1f}, turn_deg_per_s={deg:.1f} -> config.json")


if __name__ == "__main__":
    main()
