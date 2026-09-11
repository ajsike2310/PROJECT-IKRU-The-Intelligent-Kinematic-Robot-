import os
import sys
import time
import threading

# Ensure UTF-8 output on Windows streams so emojis and symbols never crash
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure parent directory (containing 'ikru') is in sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from ikru.chat import ChatEngine
from ikru.robot import RobotController
from ikru.vision import VisionReceiver, VLMClient
from ikru.audio import AudioService

# Configuration
ROBOT_IP = "192.168.1.42"   # Body & OLED Controller (IP: 192.168.1.42)
CAM_IP = "192.168.4.1"      # Head Unit (Camera AP Gateway)
ENABLE_VISION = True       # Set to True when connected to IKRU-CAM
ENABLE_MIC = True          # Use microphone for voice commands instead of text input
ENABLE_AUDIO = True        # Stream natural TTS voice over I2S to ESP32 MAX98357A
PLAY_PC_AUDIO = False       # Set to True to hear sound on PC speakers, False for robot speaker only

LLM_MODEL = "qwen2.5:3b"
VLM_MODEL = "qwen3-vl:4b"

VISUAL_KEYWORDS = [
    "see", "look", "color", "colour", "wear", "wearing",
    "shirt", "glass", "glasses", "hold", "show", "describe",
    "notice", "what", "who", "face", "clothes", "outfit",
    "hand", "background", "room"
]


import argparse

def main():
    parser = argparse.ArgumentParser(description="PROJECT IKRU — Robotic Assistant")
    parser.add_argument("--ip", default=ROBOT_IP, help=f"ESP32 Robot Body IP address (default: {ROBOT_IP})")
    parser.add_argument("--cam-ip", default=CAM_IP, help=f"ESP32-CAM IP address (default: {CAM_IP})")
    parser.add_argument("--pc-audio", action="store_true", default=PLAY_PC_AUDIO, help="Also play audio through PC speakers")
    parser.add_argument("--tts-engine", choices=["chatterbox", "chatterbox_mtl", "edge"], default="chatterbox", help="TTS synthesis engine (default: chatterbox)")
    parser.add_argument("--voice", default="guy", help="Edge-TTS voice preset fallback ('guy', 'jenny', 'ana', 'ryan', etc.)")
    parser.add_argument("--voice-prompt", default=None, help="Reference WAV file for Chatterbox zero-shot voice cloning")
    parser.add_argument("--lang", default=None, help="Language code for Chatterbox Multilingual TTS (e.g. 'fr', 'zh', 'es')")
    parser.add_argument("--no-mic", action="store_true", help="Disable microphone and use text typing")
    parser.add_argument("--no-vision", action="store_true", help="Disable UDP vision camera feed")
    args = parser.parse_args()

    target_robot_ip = args.ip
    target_cam_ip = args.cam_ip
    play_pc = args.pc_audio
    enable_vision = ENABLE_VISION and not args.no_vision
    enable_mic = ENABLE_MIC and not args.no_mic

    print("=" * 50)
    print("  PROJECT IKRU — Robotic Assistant")
    print(f"  Target Robot IP: {target_robot_ip}")
    print(f"  TTS Engine: {args.tts_engine.upper()}")
    if args.voice_prompt:
        print(f"  Voice Prompt: {args.voice_prompt}")
    if args.lang:
        print(f"  Language: {args.lang}")
    print("  Type 'exit' to quit")
    print("=" * 50)

    # Initialize Subsystems
    robot = RobotController(ip=target_robot_ip)
    chat = ChatEngine(model=LLM_MODEL)
    audio_service = (
        AudioService(
            robot_ip=target_robot_ip,
            play_pc=play_pc,
            engine=args.tts_engine,
            voice=args.voice,
            audio_prompt_path=args.voice_prompt,
            language_id=args.lang,
        )
        if ENABLE_AUDIO
        else None
    )

    # Initialize Microphone if enabled
    use_mic = enable_mic
    mic_controller = None
    if use_mic:
        try:
            from ikru.mic import MicController
            mic_controller = MicController()
        except Exception as e:
            print(f"[Audio] Error initializing microphone: {e}")
            use_mic = False  # Fallback to text input

    vision = None
    vlm = None

    if enable_vision and target_cam_ip:
        try:
            print("[Vision] Initializing UDP Vision Receiver...")
            vision = VisionReceiver(cam_ip=target_cam_ip, show_window=True)
            vision.start()
            vlm = VLMClient(model=VLM_MODEL)
            print("[Vision] System ready.")
        except Exception as e:
            print(f"[Vision] Could not start vision receiver: {e}")

    def chat_loop():
        nonlocal use_mic
        while True:
            user_input = ""
            if use_mic and mic_controller:
                try:
                    user_input = mic_controller.listen()
                    if user_input:
                        print(f"You (Voice): {user_input}")
                    else:
                        continue
                except Exception as e:
                    print(f"  [Mic Error: {e}]")
                    use_mic = False
                    continue
            else:
                try:
                    user_input = input("\nYou: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

            if not user_input:
                continue

            if user_input.lower().strip() == "exit":
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

            # Display speech, stream natural voice, and animate face on OLED
            robot.speak_segments(segments, audio_service=audio_service)

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
            import re
            display_text = re.sub(r'\[[^\]]*\]', '', full_text)
            display_text = re.sub(r'\s+([.,!?;:])', r'\1', display_text)
            display_text = re.sub(r'\s+', ' ', display_text).strip()
            emotions_list = [emo.upper() for emo, _ in segments if emo]
            emotions_str = f" [{ ' / '.join(dict.fromkeys(emotions_list)) }]" if emotions_list else ""
            print(f"\nAssistant{emotions_str}: {display_text}")

            # Brief pause to let robot audio finish so mic doesn't re-trigger
            time.sleep(0.6)

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
        print("\n[IKRU] Shutting down...")
        if audio_service:
            audio_service.stop()
        if vision:
            vision.stop()
        robot.close()


if __name__ == "__main__":
    main()
