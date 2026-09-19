import os
import sys
import time

# Ensure parent directory (software) is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "software"))

from ikru.robot import RobotController, ProximityMonitor


def test_proximity():
    print("=" * 60)
    print("  IKRU FEATURE 3 TEST: ULTRASONIC PROXIMITY REACTIONS")
    print("=" * 60)
    print("Connecting to robot...")

    robot = RobotController()

    if not robot.connected:
        print("[FAIL] Robot WebSocket not connected. Check IP/WiFi.")
        return

    print("[SUCCESS] Robot Connected!")
    print("\nStarting ProximityMonitor daemon...")
    proximity = ProximityMonitor(robot, poll_interval=0.25)
    proximity.start()

    print("\n--- TEST PHASE 1: Real-time Proximity Polling (15 Seconds) ---")
    print("Move your hand or an object towards IKRU's ultrasonic sensor:")
    print("  - Zone CAUTION (10 - 30 cm): 👀 Surprised look up + curious whisper chirp")
    print("  - Zone DANGER  (< 10 cm):     🚨 Emergency retreat reflex (scared face + gasp + back up 0.4s)")

    for _ in range(15):
        dist = proximity.get_distance()
        zone = proximity.get_zone()
        ctx = proximity.get_sensor_context()
        print(f"Current Distance: {dist:.1f} cm | Zone: [{zone}] | Prompt Context: {ctx}")
        time.sleep(1.0)

    print("\nStopping ProximityMonitor and disconnecting...")
    proximity.stop()
    robot.close()
    print("Test Complete!")


if __name__ == "__main__":
    test_proximity()
