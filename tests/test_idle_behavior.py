import os
import sys
import time

# Ensure parent directory (software) is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "software"))

from ikru.robot import RobotController, IdleManager


def test_idle():
    print("=" * 60)
    print("  IKRU FEATURE 1 TEST: IDLE BEHAVIOR & MICRO-MOVEMENTS")
    print("=" * 60)
    print("Connecting to robot...")

    robot = RobotController()

    if not robot.connected:
        print("[FAIL] Robot WebSocket not connected. Check IP/WiFi.")
        return

    print("[SUCCESS] Robot Connected!")
    print("\nStarting IdleManager daemon...")
    idle = IdleManager(robot, min_idle_sec=1.5)
    idle.start()

    print("\n--- TEST PHASE 1: Autonomous Idle (15 Seconds) ---")
    print("Observe IKRU for:")
    print("  1. Periodic blinks & double blinks")
    print("  2. Random natural eye saccades/drifts")
    print("  3. Yawn / Sigh micro-expressions")
    time.sleep(15)

    print("\n--- TEST PHASE 2: Simulating Speech & Pause ---")
    print("Simulating IKRU speaking a sentence...")
    idle.notify_activity()
    robot.happy()
    robot.display("Hello world! Idle is paused.")
    time.sleep(3.0)
    robot.display_close()
    idle.notify_speech_done()

    print("Speech done! Idle countdown resumed. Observing for 15 more seconds...")
    time.sleep(15)

    print("\n--- TEST PHASE 3: Triggering Yawn Micro-expression Directly ---")
    print("Triggering yawn...")
    robot.yawn()
    time.sleep(2)

    print("\nStopping IdleManager and disconnecting...")
    idle.stop()
    robot.close()
    print("Test Complete!")


if __name__ == "__main__":
    test_idle()
