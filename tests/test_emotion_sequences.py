import os
import sys
import time

# Ensure parent directory (software) is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "software"))

from ikru.robot import RobotController, SequenceRunner, BUILTIN_SEQUENCES


def test_sequences():
    print("=" * 60)
    print("  IKRU FEATURE 2 TEST: RECORDED EMOTION SEQUENCES")
    print("=" * 60)
    print("Connecting to robot...")

    robot = RobotController()

    if not robot.connected:
        print("[FAIL] Robot WebSocket not connected. Check IP/WiFi.")
        return

    print("[SUCCESS] Robot Connected!")
    runner = SequenceRunner(robot)

    sequences_to_test = [
        "celebrate",
        "confused_wiggle",
        "scared_retreat",
        "victory_twirl",
        "curious_scan",
        "disapproval_shake"
    ]

    print(f"\nAvailable Sequences: {runner.get_available_sequences()}")

    for seq in sequences_to_test:
        print(f"\n---> Playing Sequence: [{seq.upper()}] <---")
        robot.play_sequence(seq)
        # Avin: Increased delay to allow emotion animation to finish
        time.sleep(3.0)


    print("\nDisconnecting from robot...")
    robot.close()
    print("Test Complete!")


if __name__ == "__main__":
    test_sequences()
