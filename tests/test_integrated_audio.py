"""
===============================================================================
UNIT & INTEGRATION TESTS — IKRU INTEGRATED R2-D2 AUDIO SYSTEM
===============================================================================
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(root_dir / "software") not in sys.path:
    sys.path.insert(0, str(root_dir / "software"))

from ikru.audio import SonicEmotionEngine, SonicClient, DroidStep
from ikru.robot import RobotController


class TestIntegratedAudio(unittest.TestCase):

    def setUp(self):
        self.engine = SonicEmotionEngine()
        self.sonic_client = SonicClient(ip="127.0.0.1", port=5000, enable_local_audio=False)

    def test_sonic_client_play_sentence(self):
        emo, inten, total_dur = self.sonic_client.play_sentence("I found the object you were looking for!")
        self.assertEqual(emo, "happy")
        self.assertGreater(total_dur, 1000)

    def test_robot_controller_integration(self):
        # Initialize RobotController without real WS server (offline mode)
        robot = RobotController(ip="127.0.0.1", port=81, audio_ip="127.0.0.1", audio_port=5000, enable_local_audio=False)
        self.assertIsNotNone(robot.sonic)
        self.assertIsInstance(robot.sonic.engine, SonicEmotionEngine)

        # Test speaking segments
        segments = [
            ("happy", "I found your keys!"),
            ("excited", "They were under the couch!")
        ]
        # Shouldn't throw exceptions even if hardware is offline
        robot.sonic.play_sentence(segments[0][1], emotion_override=segments[0][0])
        robot.close()


if __name__ == "__main__":
    unittest.main()
