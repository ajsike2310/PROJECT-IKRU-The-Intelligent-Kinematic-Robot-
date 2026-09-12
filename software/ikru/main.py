import os
import sys
import time
import threading
import json
import random

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



# Configuration Defaults (overridden by config.json if present)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.json")
config_data = {}
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    except Exception as e:
        print(f"[Config] Warning loading config.json: {e}")

ROBOT_IP = config_data.get("robot_ip", "ikru-robot.local")
CAM_IP = config_data.get("cam_ip", "192.168.4.1")
ENABLE_VISION = config_data.get("enable_vision", True)
ENABLE_MIC = config_data.get("enable_mic", True)
ENABLE_AUDIO = True
PLAY_PC_AUDIO = config_data.get("play_pc_audio", False)
TTS_ENGINE = config_data.get("tts_engine", "chatterbox")
VOICE_PRESET = config_data.get("voice", "guy")
DEFAULT_VOLUME = config_data.get("volume", 80)

LLM_MODEL = config_data.get("llm_model", "qwen2.5:3b")
VLM_MODEL = config_data.get("vlm_model", "qwen3-vl:4b")

VISUAL_KEYWORDS = [
    "see", "look", "color", "colour", "wear", "wearing",
    "shirt", "glass", "glasses", "hold", "show", "describe",
    "notice", "what", "who", "face", "clothes", "outfit",
    "hand", "background", "room"
]


import argparse
import getpass


def _prompt_robot_ip(current_ip):
    """Ask the user for the Robot IP at startup."""
    print(f"\n  [Robot] Current Robot IP/Hostname: {current_ip}")
    try:
        change = input("  Change Robot IP? (y/N): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  [Robot] Skipped. Using current IP.")
        return current_ip
        
    if change != "y":
        return current_ip

    print("\n" + "=" * 50)
    print("  ROBOT IP CONFIGURATION")
    print("=" * 50)
    try:
        new_ip = input("  Enter Robot IP or Hostname: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  [Robot] Cancelled. Using current IP.")
        return current_ip

    if not new_ip:
        print("  [Robot] No IP entered. Using current IP.")
        return current_ip

    # Save to config.json for future runs
    config_data["robot_ip"] = new_ip
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        print(f"  [Robot] IP saved to config.json")
    except Exception as e:
        print(f"  [Robot] Warning: could not save config: {e}")

    return new_ip


def _prompt_wifi_credentials():
    """Ask the user for home WiFi credentials at startup.

    Credentials are saved to config.json so they only need to be entered once.
    Returns (ssid, password) tuple.
    """
    saved_ssid = config_data.get("wifi_ssid", "")
    saved_pass = config_data.get("wifi_pass", "")

    if saved_ssid:
        print(f"\n  [WiFi] Saved home network: {saved_ssid}")
        try:
            change = input("  Change WiFi credentials? (y/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  [WiFi] Skipped. Using saved credentials.")
            return saved_ssid, saved_pass
        if change != "y":
            return saved_ssid, saved_pass

    print("\n" + "=" * 50)
    print("  HOME Wi-Fi CONFIGURATION")
    print("  (Required for audio streaming & internet access)")
    print("=" * 50)
    try:
        ssid = input("  Enter Wi-Fi SSID: ").strip()
        password = input("  Enter Wi-Fi Password: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  [WiFi] Cancelled. Using fallback network.")
        return "", ""

    if not ssid:
        print("  [WiFi] No SSID entered. Using fallback network.")
        return "", ""

    # Save to config.json for future runs
    config_data["wifi_ssid"] = ssid
    config_data["wifi_pass"] = password
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        print(f"  [WiFi] Credentials saved to config.json")
    except Exception as e:
        print(f"  [WiFi] Warning: could not save config: {e}")

    return ssid, password


def main():
    parser = argparse.ArgumentParser(description="PROJECT IKRU — Robotic Assistant")
    parser.add_argument("--ip", default=ROBOT_IP, help=f"ESP32 Robot Body IP or Hostname (default: {ROBOT_IP})")
    parser.add_argument("--cam-ip", default=CAM_IP, help=f"ESP32-CAM IP address (default: {CAM_IP})")
    parser.add_argument("--volume", type=int, default=DEFAULT_VOLUME, help=f"Speaker volume 0-100% (default: {DEFAULT_VOLUME}%)")
    parser.add_argument("--pc-audio", action="store_true", default=PLAY_PC_AUDIO, help="Also play audio through PC speakers")
    parser.add_argument("--tts-engine", choices=["chatterbox", "chatterbox_mtl", "edge"], default=TTS_ENGINE, help=f"TTS synthesis engine (default: {TTS_ENGINE})")
    parser.add_argument("--voice", default=VOICE_PRESET, help=f"Edge-TTS voice preset fallback ('guy', 'jenny', 'ana', 'ryan', etc.) (default: {VOICE_PRESET})")
    parser.add_argument("--voice-prompt", default=None, help="Reference WAV file for Chatterbox zero-shot voice cloning")
    parser.add_argument("--lang", default=None, help="Language code for Chatterbox Multilingual TTS (e.g. 'fr', 'zh', 'es')")
    parser.add_argument("--no-mic", action="store_true", help="Disable microphone and use text typing")
    parser.add_argument("--no-vision", action="store_true", help="Disable UDP vision camera feed")
    parser.add_argument("--no-wifi-setup", action="store_true", help="Skip WiFi credential prompt")
    args = parser.parse_args()

    target_robot_ip = args.ip
    target_cam_ip = args.cam_ip
    play_pc = args.pc_audio
    enable_vision = ENABLE_VISION and not args.no_vision
    enable_mic = ENABLE_MIC and not args.no_mic

    # ============================================================
    # STEP 1: Ask for Robot IP and home WiFi credentials
    # ============================================================
    wifi_ssid, wifi_pass = "", ""
    if not args.no_wifi_setup:
        target_robot_ip = _prompt_robot_ip(target_robot_ip)
        wifi_ssid, wifi_pass = _prompt_wifi_credentials()

    print("\n" + "=" * 50)
    print("  PROJECT IKRU — Robotic Assistant")
    print(f"  Target Robot IP: {target_robot_ip}")
    print(f"  TTS Engine: {args.tts_engine.upper()}")
    print(f"  Speaker Volume: {args.volume}%")
    if wifi_ssid:
        print(f"  Home WiFi: {wifi_ssid}")
    if args.voice_prompt:
        print(f"  Voice Prompt: {args.voice_prompt}")
    if args.lang:
        print(f"  Language: {args.lang}")
    print("  Type 'exit' to quit")
    print("=" * 50)

    # ============================================================
    # STEP 2: Connect to ESP32 (on whatever network it's on)
    # ============================================================
    robot = RobotController(ip=target_robot_ip)

    # ============================================================
    # STEP 3: If home WiFi credentials provided, tell ESP32 to
    #         switch to home WiFi, then reconnect
    # ============================================================
    if wifi_ssid and robot.connected:
        print(f"\n[WiFi] Sending home WiFi credentials to ESP32: {wifi_ssid}")
        try:
            robot.send(f"SET_WIFI:{wifi_ssid}:{wifi_pass}")
            print("[WiFi] ESP32 is switching networks... waiting 15 seconds...")
            robot.close()
            time.sleep(15)  # Give ESP32 time to reconnect to home WiFi

            # Reconnect — the ESP32 should now be on the home WiFi
            print("[WiFi] Reconnecting to ESP32 on home network...")
            robot = RobotController(ip=target_robot_ip)
            if robot.connected:
                print("[WiFi] Successfully reconnected to ESP32 on home WiFi!")
            else:
                print("[WiFi] Warning: Could not reconnect. ESP32 may still be switching.")
        except Exception as e:
            print(f"[WiFi] Error during network switch: {e}")
            print("[WiFi] Continuing on current network...")
            robot = RobotController(ip=target_robot_ip)

    # ============================================================
    # STEP 4: Initialize remaining subsystems
    # ============================================================
    chat = ChatEngine(model=LLM_MODEL)
    
    # Create permanent cache directory for audio files
    audio_cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio", "cache")
    os.makedirs(audio_cache_dir, exist_ok=True)
    
    audio_service = (
        AudioService(
            robot_ip=target_robot_ip,
            play_pc=play_pc,
            engine=args.tts_engine,
            voice=args.voice,
            audio_prompt_path=args.voice_prompt,
            language_id=args.lang,
            cache_dir=audio_cache_dir,
        )
        if ENABLE_AUDIO
        else None
    )

    if audio_service:
        audio_service.set_volume(args.volume / 100.0)
        print("\n[IKRU] Pre-generating thinking filler audios...")
        audio_service.pregenerate_fillers()
    if robot:
        robot.set_volume(args.volume)

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

            thinking_event = threading.Event()

            def play_filler():
                # Wait 10 seconds, if thinking_event is NOT set by then, play a filler sound
                if not thinking_event.wait(10.0):
                    if audio_service:
                        filler_url, filler_text = audio_service.get_random_filler()
                        if filler_url:
                            print(f"  [Filler] {filler_text}")
                            try:
                                # Play the pre-generated URL directly
                                robot.play_audio(filler_url)
                                if play_pc and getattr(audio_service, 'play_pc', False):
                                    # Optional: play on PC if requested
                                    pass
                            except Exception:
                                pass

            filler_thread = threading.Thread(target=play_filler, daemon=True)
            filler_thread.start()

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
            
            # Stop the filler timer in case we finished before 10s
            thinking_event.set()

            # Display speech, stream natural voice, and animate face on OLED
            try:
                robot.speak_segments(segments, audio_service=audio_service)
            except Exception as e:
                print(f"  [Audio Error: {e}] — continuing without audio")

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
