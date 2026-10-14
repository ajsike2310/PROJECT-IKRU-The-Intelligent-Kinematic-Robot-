import os
import json
import time
import threading

BUILTIN_SEQUENCES = {
    "celebrate": [
        {"emotion": "glee", "sound": "laughter", "movement": "spin_left", "duration": 0.6, "gaze": [0.0, 0.2]},
        {"emotion": "happy", "sound": "giggle", "movement": "spin_right", "duration": 0.6, "gaze": [0.0, -0.1]},
        {"emotion": "glee", "sound": "success", "movement": "stop", "duration": 0.5, "gaze": [0.0, 0.0]}
    ],
    "happy_dance": [
        {"emotion": "glee", "sound": "laughter", "movement": "spin_left", "duration": 0.6, "gaze": [0.0, 0.2]},
        {"emotion": "happy", "sound": "giggle", "movement": "spin_right", "duration": 0.6, "gaze": [0.0, -0.1]},
        {"emotion": "glee", "sound": "success", "movement": "stop", "duration": 0.5, "gaze": [0.0, 0.0]}
    ],
    "confused_wiggle": [
        {"emotion": "skeptic", "sound": "confused", "movement": "left", "duration": 0.35, "gaze": [0.4, 0.0]},
        {"emotion": "suspicious", "sound": "skeptic", "movement": "right", "duration": 0.35, "gaze": [-0.4, 0.0]},
        {"emotion": "surprised", "sound": "gasp", "movement": "stop", "duration": 0.5, "gaze": [0.0, 0.2]}
    ],
    "scared_retreat": [
        {"emotion": "scared", "sound": "gasp", "movement": "backward", "duration": 0.5, "gaze": [0.0, 0.3]},
        {"emotion": "worried", "sound": "cry", "movement": "stop", "duration": 0.8, "gaze": [0.0, -0.2]}
    ],
    "victory_twirl": [
        {"emotion": "awe", "sound": "success", "movement": "forward", "duration": 0.4, "gaze": [0.0, 0.3]},
        {"emotion": "glee", "sound": "laughter", "movement": "spin_left", "duration": 0.8, "gaze": [0.0, 0.0]},
        {"emotion": "happy", "sound": "happy", "movement": "stop", "duration": 0.5, "gaze": [0.0, 0.0]}
    ],
    "curious_scan": [
        {"emotion": "focused", "sound": "thinking", "movement": "left", "duration": 0.4, "gaze": [0.5, 0.0]},
        {"emotion": "skeptic", "sound": "whisper", "movement": "right", "duration": 0.6, "gaze": [-0.5, 0.0]},
        {"emotion": "surprised", "sound": "gasp", "movement": "stop", "duration": 0.5, "gaze": [0.0, 0.0]}
    ],
    "disapproval_shake": [
        {"emotion": "annoyed", "sound": "groan", "movement": "wiggle", "duration": 0.6, "gaze": [-0.3, 0.0]},
        {"emotion": "unimpressed", "sound": "exhale", "movement": "stop", "duration": 0.6, "gaze": [0.0, -0.2]}
    ]
}


class SequenceRunner:
    """
    Executes multi-modal recorded emotion sequences combining:
    - OLED eye expression
    - Gaze directional offsets
    - R2-D2 SmartElex digital audio sweeps
    - Wheel motor movements
    """

    def __init__(self, robot_controller, sequences_dir=None):
        self.robot = robot_controller
        if sequences_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            sequences_dir = os.path.join(project_root, "data", "sequences")
        self.sequences_dir = sequences_dir
        os.makedirs(self.sequences_dir, exist_ok=True)
        self._lock = threading.Lock()

    def get_available_sequences(self):
        """Returns list of all available sequence names (built-in + JSON files)."""
        names = list(BUILTIN_SEQUENCES.keys())
        if os.path.exists(self.sequences_dir):
            for fname in os.listdir(self.sequences_dir):
                if fname.endswith(".json"):
                    seq_name = fname[:-5]
                    if seq_name not in names:
                        names.append(seq_name)
        return names

    def load_sequence(self, name):
        """Loads sequence steps by name from JSON file or built-in dictionary."""
        name = name.lower().strip()
        json_path = os.path.join(self.sequences_dir, f"{name}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Sequence] Error loading {json_path}: {e}")

        if name in BUILTIN_SEQUENCES:
            return BUILTIN_SEQUENCES[name]

        return None

    def play_sequence(self, sequence_name_or_list):
        """
        Executes a sequence step-by-step.
        Accepts sequence name (str) or a list of step dictionaries.
        """
        if isinstance(sequence_name_or_list, str):
            steps = self.load_sequence(sequence_name_or_list)
            seq_name = sequence_name_or_list
        else:
            steps = sequence_name_or_list
            seq_name = "custom"

        if not steps:
            print(f"[Sequence] Unknown sequence: {sequence_name_or_list}")
            return False

        print(f"[Sequence] Executing recorded sequence: [{seq_name.upper()}] ({len(steps)} steps)...")

        with self._lock:
            try:
                for i, step in enumerate(steps):
                    emotion = step.get("emotion", "normal")
                    sound = step.get("sound", None)
                    intensity = float(step.get("sound_intensity", 0.5))
                    movement = step.get("movement", "stop").lower()
                    duration = float(step.get("duration", 0.5))
                    gaze = step.get("gaze", None)
                    text = step.get("display_text", None)

                    # 1. Update OLED emotion & gaze
                    if hasattr(self.robot, emotion.lower()):
                        getattr(self.robot, emotion.lower())()
                    else:
                        self.robot.set_emotion(emotion)

                    if gaze and len(gaze) == 2:
                        self.robot.look_at(gaze[0], gaze[1])

                    # 2. Play Sound
                    if sound:
                        self.robot.play_sound(sound, intensity)

                    # 3. Display text if requested
                    if text:
                        self.robot.display(text)

                    # 4. Movement Action
                    if movement in ["left", "right", "forward", "backward", "spin_left", "spin_right", "wiggle"]:
                        move_method = getattr(self.robot, movement, None)
                        if move_method and callable(move_method):
                            move_method(duration=duration)
                        else:
                            self.robot.send(movement.upper())
                            time.sleep(duration)
                            self.robot.stop()
                    else:
                        self.robot.stop()
                        time.sleep(duration)

                # Reset to normal pose post-sequence
                self.robot.stop()
                self.robot.normal()
                self.robot.look_front()
                print(f"[Sequence] Sequence [{seq_name.upper()}] finished.")
                return True

            except Exception as e:
                print(f"[Sequence] Error running sequence {seq_name}: {e}")
                self.robot.stop()
                self.robot.normal()
                self.robot.look_front()
                return False
