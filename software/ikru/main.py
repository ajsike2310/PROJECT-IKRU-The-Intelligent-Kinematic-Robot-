import os
import sys
import time
import threading

# Ensure parent directory (containing 'ikru') is in sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from ikru.chat import ChatEngine
from ikru.robot import RobotController
from ikru.vision import VisionReceiver, VLMClient

# Configuration
ROBOT_IP = "192.168.1.37"
CAM_IP = "192.168.4.1"       # AP mode default: 192.168.4.1 (or station IP if on home Wi-Fi)
ENABLE_VISION = True        # Set to True when connected to IKRU-CAM

LLM_MODEL = "qwen2.5:3b"
VLM_MODEL = "qwen3-vl:4b"

VISUAL_KEYWORDS = [
    "see", "look", "color", "colour", "wear", "wearing",
    "shirt", "glass", "glasses", "hold", "show", "describe",
    "notice", "what", "who", "face", "clothes", "outfit",
    "hand", "background", "room"
]


def main():
    print("=" * 50)
    print("  PROJECT IKRU — Robotic Assistant")
    print("  Type 'exit' to quit")
    print("=" * 50)

    # Initialize Subsystems
    robot = RobotController(ip=ROBOT_IP)
    chat = ChatEngine(model=LLM_MODEL)

    vision = None
    vlm = None

    if ENABLE_VISION and CAM_IP:
        try:
            print("[Vision] Initializing UDP Vision Receiver...")
            vision = VisionReceiver(cam_ip=CAM_IP, show_window=True)
            vision.start()
            vlm = VLMClient(model=VLM_MODEL)
            print("[Vision] System ready.")
        except Exception as e:
            print(f"[Vision] Could not start vision receiver: {e}")

    def chat_loop():
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            if user_input.lower() == "exit":
                break

            # Indicate thinking state on OLED
            robot.focused()
            print("  [Thinking...]")

            # Optional visual reasoning
            visual_context = None
            if vision and vlm and any(kw in user_input.lower() for kw in VISUAL_KEYWORDS):
                jpeg_bytes = vision.buffer.get_jpeg_bytes()
                if jpeg_bytes:
                    print("[Vision] Querying VLM for visual observation...")
                    visual_context = vlm.describe_scene(jpeg_bytes)
                    if visual_context:
                        print(f"[Vision] Context: {visual_context}")

            # Query Chat LLM
            tools, response_text, segments = chat.ask(user_input, visual_context=visual_context)

            # Display speech and animate face on OLED
            robot.speak_segments(segments)

            # Execute movement actions
            for t in tools:
                action = t.get("action", "").lower()
                duration = float(t.get("duration", 0))

                method = getattr(robot, action, None)
                if method and callable(method):
                    print(f"Executing: {action} ({duration}s)")
                    if action in ["forward", "backward", "left", "right", "stop"]:
                        method(duration)
                    else:
                        method()

            full_text = " ".join(txt for _, txt in segments).strip()
            print(f"\nAssistant: {full_text}")

    # Run chat in thread while pumping vision display on main thread
    chat_thread = threading.Thread(target=chat_loop, daemon=True)
    chat_thread.start()

    try:
        while chat_thread.is_alive():
            if vision and vision.show_window:
                vision.update_display()
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[IKRU] Exiting...")
    finally:
        if vision:
            vision.stop()
        robot.close()


if __name__ == "__main__":
    main()
