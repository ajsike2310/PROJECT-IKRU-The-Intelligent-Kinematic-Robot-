import os
import sys
import time
import threading
import json
import random
import re

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
from ikru.robot import RobotController, IdleManager, ProximityMonitor, AutonomousBrain
from ikru.vision import VisionReceiver, VLMClient
from ikru.audio import AudioService
from ikru.memory import MemoryManager
from ikru.net import Diagnosis, serial_link
from ikru.net.bringup import Bringup
from ikru.net.netinfo import HUB_ROBOT_IP



# Configuration Defaults (overridden by config.json if present)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.json")
# Git-ignored overrides for secrets (Wi-Fi credentials) — merged over config.json
CONFIG_LOCAL_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "config.local.json")


def _load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Config] Warning loading {os.path.basename(path)}: {e}")
        return {}


def _save_config(path=CONFIG_FILE, **updates):
    """Read-modify-write one config file so local secrets never leak into config.json."""
    config_data.update(updates)
    data = _load_json(path)
    data.update(updates)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Config] Warning: could not save {os.path.basename(path)}: {e}")
        return False


config_data = {**_load_json(CONFIG_FILE), **_load_json(CONFIG_LOCAL_FILE)}

ROBOT_IP = config_data.get("robot_ip", HUB_ROBOT_IP)
ROBOT_LAST_IP = config_data.get("robot_last_ip", "")
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

LLM_KEEP_ALIVE = config_data.get("llm_keep_alive", "30m")
MIC_CONFIG = config_data.get("mic", {})

# Only clearly visual requests trigger the camera VLM (loading it evicts the chat LLM from VRAM)
VISUAL_PATTERN = re.compile(
    r"\b(what do you see|can you see|do you see|what you see|look at|looking at|look here|"
    r"what is this|what's this|what is that|what's that|who am i|"
    r"what am i (wearing|holding|doing)|how do i look|describe|wearing|holding|"
    r"colou?rs?|shirt|glasses|outfit|clothes|in front of you|show you|notice|camera)\b",
    re.IGNORECASE,
)

EXIT_PHRASES = [
    "exit", "tata", "good bye", "goodbye", "bye bye", "shut down", "see you", "sleep",
    "power off", "quit", "later", "catch you later", "turn off", "adios", "cya",
]


def _is_exit(text):
    lowered = text.lower()
    return any(phrase in lowered for phrase in EXIT_PHRASES)


import argparse
import getpass


def _print_diagnosis(diag):
    print("\n" + "-" * 50)
    print("  ROBOT NOT REACHABLE")
    print("-" * 50)
    print(f"  {diag.message}")
    for hint in diag.hints:
        print(f"   -> {hint}")
    print("-" * 50)


def _prompt_wifi_credentials():
    """Asks for Wi-Fi credentials to provision onto the robot. Saved to config.local.json."""
    saved_ssid = config_data.get("wifi_ssid", "")
    print("\n" + "=" * 50)
    print("  ROBOT Wi-Fi PROVISIONING")
    print("  (The robot joins IKRU-CAM first; this network is its fallback)")
    print("=" * 50)
    try:
        ssid = input(f"  Wi-Fi SSID [{saved_ssid}]: ").strip() or saved_ssid
        password = getpass.getpass("  Wi-Fi Password: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  [WiFi] Cancelled.")
        return "", ""
    if not ssid:
        print("  [WiFi] No SSID entered.")
        return "", ""
    if ":" in ssid:
        print("  [WiFi] SSIDs containing ':' can't be sent to the robot.")
        return "", ""

    _save_config(CONFIG_LOCAL_FILE, wifi_ssid=ssid, wifi_pass=password)
    print("  [WiFi] Credentials saved to config.local.json")
    return ssid, password


def _usb_serial_menu(robot):
    """Reads the robot's IP over USB, optionally provisioning Wi-Fi."""
    if not serial_link.list_ports():
        print("  [USB] No serial ports found. Plug the robot in with a data USB cable.")
        return
    print("  [USB] Asking the robot for its IP over serial...")
    reply = serial_link.query_ip()
    if not reply:
        print("  [USB] No reply. If the board just reset, wait ~10 s for it to boot and try again.")
    else:
        port, ip, ssid, mode = reply
        print(f"  [USB] {port}: robot is at {ip} on '{ssid}' ({mode} mode)")
        if mode == "STA" and ip != "0.0.0.0":
            robot.extra_hosts = [ip] + [h for h in robot.extra_hosts if h != ip]

    try:
        send = input("  Send Wi-Fi credentials to the robot over USB? (y/N): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return
    if send == "y":
        ssid, password = _prompt_wifi_credentials()
        if ssid:
            port = serial_link.send_wifi(ssid, password)
            print(f"  [USB] Sent to {port}. The robot is switching networks..." if port
                  else "  [USB] Could not open a serial port.")


def _connection_wizard(robot, interactive):
    """Explains why the robot isn't reachable and offers ways to fix it."""
    while not robot.connected:
        if isinstance(robot.last_result, Diagnosis):
            _print_diagnosis(robot.last_result)
        if not interactive:
            print("[Robot] Continuing offline. Reconnecting in the background.")
            return
        try:
            choice = input("  [r]etry  [m]anual IP  [u]sb serial  [c]ontinue offline: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            choice = "c"

        if choice == "m":
            try:
                new_ip = input("  Robot IP or hostname: ").strip()
            except (KeyboardInterrupt, EOFError):
                continue
            if new_ip:
                robot.ip = new_ip
                _save_config(robot_ip=new_ip)
                print(f"  [Robot] Saved robot_ip={new_ip} to config.json")
        elif choice == "u":
            _usb_serial_menu(robot)
        elif choice != "r":
            print("[Robot] Continuing offline. IKRU will connect automatically when the robot appears.")
            return
        robot.connect()


def _provision_wifi_over_ws(robot):
    """Pushes Wi-Fi credentials to a connected robot, then reconnects."""
    ssid, password = _prompt_wifi_credentials()
    if not ssid:
        return
    print(f"\n[WiFi] Sending Wi-Fi credentials to robot: {ssid}")
    robot.send(f"SET_WIFI:{ssid}:{password}")
    robot._handle_disconnect()
    print("[WiFi] Robot is switching networks... waiting 15 seconds...")
    time.sleep(15)
    if robot.connect():
        print("[WiFi] Reconnected to robot.")
    else:
        print("[WiFi] Could not reconnect yet. The robot may be on a network this PC can't reach.")


def _remember_robot_ip(ip):
    if ip != config_data.get("robot_last_ip"):
        _save_config(robot_last_ip=ip)


def main():
    parser = argparse.ArgumentParser(description="PROJECT IKRU — Robotic Assistant")
    parser.add_argument("--ip", default=ROBOT_IP, help=f"ESP32 Robot Body IP or Hostname (default: {ROBOT_IP})")
    parser.add_argument("--cam-ip", default=CAM_IP, help=f"ESP32-CAM IP address (default: {CAM_IP})")
    parser.add_argument("--volume", type=int, default=DEFAULT_VOLUME, help=f"Speaker volume 0-100%% (default: {DEFAULT_VOLUME}%%)")
    parser.add_argument("--pc-audio", action="store_true", default=PLAY_PC_AUDIO, help="Also play audio through PC speakers")
    parser.add_argument("--voice-mode", choices=["r2d2", "tts"], default="r2d2", help="Voice output mode: 'r2d2' (instant droid glissando chirps via SmartElex speaker, default) or 'tts' (neural speech streaming)")
    parser.add_argument("--tts-engine", choices=["chatterbox", "chatterbox_mtl", "edge"], default=TTS_ENGINE, help=f"TTS synthesis engine (default: {TTS_ENGINE})")
    parser.add_argument("--voice", default=VOICE_PRESET, help=f"Edge-TTS voice preset fallback ('guy', 'jenny', 'ana', 'ryan', etc.) (default: {VOICE_PRESET})")
    parser.add_argument("--voice-prompt", default=None, help="Reference WAV file for Chatterbox zero-shot voice cloning")
    parser.add_argument("--lang", default=None, help="Language code for Chatterbox Multilingual TTS (e.g. 'fr', 'zh', 'es')")
    parser.add_argument("--no-mic", action="store_true", help="Disable microphone and use text typing")
    parser.add_argument("--no-vision", action="store_true", help="Disable UDP vision camera feed")
    parser.add_argument("--no-wizard", "--no-wifi-setup", dest="no_wizard", action="store_true", help="Skip the interactive connection menu if the robot isn't found")
    parser.add_argument("--provision-wifi", action="store_true", help="Send new Wi-Fi credentials to the robot after connecting")
    args = parser.parse_args()

    target_cam_ip = args.cam_ip
    play_pc = args.pc_audio
    enable_vision = ENABLE_VISION and not args.no_vision
    enable_mic = ENABLE_MIC and not args.no_mic

    print("\n" + "=" * 50)
    print("  PROJECT IKRU — Robotic Assistant")
    print(f"  Robot: {args.ip}  |  Camera: {target_cam_ip}")
    print(f"  Voice Mode: {args.voice_mode.upper()} {'(Instant Glissando Droid Speaker)' if args.voice_mode == 'r2d2' else f'({args.tts_engine.upper()})'}")
    print(f"  Speaker Volume: {args.volume}%")
    if args.voice_prompt:
        print(f"  Voice Prompt: {args.voice_prompt}")
    if args.lang:
        print(f"  Language: {args.lang}")
    print("  Type 'exit' to quit")
    print("=" * 50)

    # ============================================================
    # STEP 1: Structured bring-up
    #   PC network -> IKRU power-on -> PC joins IKRU-CAM -> body link
    # ============================================================
    bringup = Bringup(
        config_data,
        save_local=lambda **kw: _save_config(CONFIG_LOCAL_FILE, **kw),
        interactive=not args.no_wizard,
    )
    bringup.run_network()

    app_ready = threading.Event()

    def _on_robot_connect(ip):
        _remember_robot_ip(ip)
        if app_ready.is_set():
            # Robot rebooted mid-session: skip its setup screen straight to the face
            robot.setup_done()

    robot = RobotController(
        ip=args.ip,
        extra_hosts=[ROBOT_LAST_IP] if ROBOT_LAST_IP else [],
        on_connect=_on_robot_connect,
        connect_now=False,
    )
    bringup.link_body(robot)

    # ============================================================
    # STEP 2: Not found -> explain why and offer fixes
    # ============================================================
    if not robot.connected:
        _connection_wizard(robot, interactive=not args.no_wizard)

    # ============================================================
    # STEP 3: Optional Wi-Fi provisioning (only when asked for)
    # ============================================================
    if args.provision_wifi:
        if robot.connected:
            _provision_wifi_over_ws(robot)
        else:
            print("[WiFi] --provision-wifi needs a connected robot. Use [u]sb serial in the menu instead.")

    # ============================================================
    # STEP 4: Initialize remaining subsystems
    # ============================================================
    # Initialize persistent memory (SQLite + Qdrant)
    memory_cfg = config_data.get("memory", {})
    memory_enabled = memory_cfg.get("enabled", True)
    memory = None
    if memory_enabled:
        robot.setup_status("Loading memory")
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(project_root, memory_cfg.get("sqlite_path", "data/memory/ikru_history.db"))
        qdrant_path = os.path.join(project_root, memory_cfg.get("qdrant_path", "data/memory/qdrant"))
        try:
            memory = MemoryManager(db_path=db_path, qdrant_path=qdrant_path)
            stats = memory.get_stats()
            print(f"[Memory] Loaded: {stats['messages']} messages, {stats['facts']} facts, {stats['vector_memories']} vectors")
        except Exception as e:
            print(f"[Memory] Warning: Memory init failed ({e}), running without memory.")
            memory = None

    robot.setup_status("Waking brain")
    chat = ChatEngine(model=LLM_MODEL, memory=memory, keep_alive=LLM_KEEP_ALIVE)
    # Load the LLM into VRAM while the rest of the system starts up
    threading.Thread(target=chat.warm_up, daemon=True).start()
    
    voice_mode = args.voice_mode.lower()
    audio_service = None
    if voice_mode == "tts" and ENABLE_AUDIO:
        robot.setup_status("Warming voice")
        # Create permanent cache directory for audio files
        audio_cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio", "cache")
        os.makedirs(audio_cache_dir, exist_ok=True)
        audio_service = AudioService(
            robot_ip=robot.ip,
            play_pc=play_pc,
            engine=args.tts_engine,
            voice=args.voice,
            audio_prompt_path=args.voice_prompt,
            language_id=args.lang,
            cache_dir=audio_cache_dir,
        )
        if audio_service:
            audio_service.set_volume(args.volume / 100.0)
            print("\n[IKRU] Pre-generating thinking filler audios...")
            audio_service.pregenerate_fillers()
    else:
        print("\n[IKRU] Voice Output: R2-D2 Droid Astromech (SmartElex Hardware Speaker — Zero Latency)")
    if robot:
        robot.set_volume(args.volume)

    idle_manager = IdleManager(robot)
    idle_manager.start()

    proximity_monitor = ProximityMonitor(robot, idle_manager=idle_manager)
    proximity_monitor.start()
    robot.proximity_monitor = proximity_monitor

    # Hardware-level safety: enable obstacle brake so autonomous roaming can't crash IKRU
    try:
        robot.set_obstacle_threshold(12.0)
        robot.enable_obstacle_brake()
    except Exception as e:
        print(f"[Robot] Warning: could not enable obstacle brake ({e}).")

    # Initialize Microphone if enabled
    use_mic = enable_mic
    mic_controller = None
    if use_mic:
        robot.setup_status("Opening ears")
        try:
            from ikru.mic import MicController
            mic_controller = MicController(**MIC_CONFIG)
        except Exception as e:
            print(f"[Audio] Error initializing microphone: {e}")
            use_mic = False  # Fallback to text input

    vision = None
    vlm = None

    if enable_vision and target_cam_ip:
        try:
            print("[Vision] Initializing UDP Vision Receiver...")
            robot.setup_status("Opening eyes")
            vision = VisionReceiver(cam_ip=target_cam_ip, show_window=True)
            vision.start()
            vlm = VLMClient(model=VLM_MODEL)
            print("[Vision] System ready.")
        except Exception as e:
            print(f"[Vision] Could not start vision receiver: {e}")

    # Autonomous Brain — spontaneous LLM-driven thoughts, movement, and commentary
    autonomous_brain = AutonomousBrain(
        robot=robot,
        memory=memory,
        vision=vision,
        vlm=vlm,
        idle_manager=idle_manager,
        proximity_monitor=proximity_monitor,
        audio_service=audio_service,
        model=LLM_MODEL,
        keep_alive=LLM_KEEP_ALIVE,
    )
    autonomous_brain.start()

    import queue
    mic_queue = queue.Queue()
    interrupt_event = threading.Event()
    stop_listening = None
    # While IKRU is thinking/speaking/moving (plus a short echo guard after), speech is
    # ignored unless it's an exit command — replaces the old sleep-then-flush approach.
    busy = threading.Event()
    busy_until = [0.0]

    if use_mic and mic_controller:
        def on_text(text, t_end):
            if _is_exit(text):
                # Hard-interrupt the current speech and queue the exit
                interrupt_event.set()
                mic_queue.put((text, t_end))
                return
            if busy.is_set() or t_end < busy_until[0]:
                print(f"  [Mic] Ignored while busy: {text}")
                return
            mic_queue.put((text, t_end))

        def on_speech_start():
            if not busy.is_set():
                idle_manager.notify_activity()

        stop_listening = mic_controller.start_background_listening(on_text, on_speech_start)
        print("[Mic] Background listener started. (Say 'exit' to quit)")

    # --------------------------------------------------------
    # SETUP COMPLETE: robot plays its ready animation, face wakes up
    # --------------------------------------------------------
    bringup.finish()
    app_ready.set()
    robot.setup_done()
    time.sleep(2.5)  # let the ready animation finish before the first expression

    # --------------------------------------------------------
    # GREETING ON WAKE
    # --------------------------------------------------------
    if memory:
        personal_facts = memory.db.get_facts_by_category("personal")
        user_name = None
        for row in personal_facts:
            fact_str = row['fact']
            if "name is" in fact_str.lower():
                user_name = fact_str.split("is")[-1].strip()
                break
        
        greeting_text = f"Hi {user_name}! I am online and ready." if user_name else "Hello! I am online and ready."
        print(f"\nAssistant [HAPPY]: {greeting_text}")
        busy.set()
        robot.speak_segments([("HAPPY", greeting_text)], audio_service=audio_service)
        busy_until[0] = time.time() + 0.3
        busy.clear()

    def chat_loop():
        nonlocal use_mic
        while True:
            user_input = ""
            t_heard = None
            interrupt_event.clear()

            if use_mic and mic_controller:
                try:
                    user_input, t_heard = mic_queue.get()
                    print(f"\nYou (Voice): {user_input}")
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

            busy.set()
            t_turn = time.time()
            # Notify IdleManager of activity (pauses idle animations)
            idle_manager.notify_activity()
            # Pause background systems while IKRU is thinking / speaking / moving
            proximity_monitor.pause()
            autonomous_brain.pause()

            # Check for any exit phrases
            if _is_exit(user_input):
                # Sleepy Exit Routine (just animation and sound)
                print("\n[IKRU] Going to sleep...")
                robot.sleepy()
                robot.play_sound("SIGH")
                time.sleep(1.0)
                break

            # Indicate thinking state on OLED & SmartElex speaker
            robot.focused()
            if hasattr(robot, "thinking"):
                robot.thinking()
            print("  [Thinking...]")

            thinking_event = threading.Event()

            def play_filler():
                # Wait 10 seconds, if thinking_event is NOT set by then and audio_service exists, play a filler sound
                if audio_service and not thinking_event.wait(10.0):
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
            if vision and vlm and VISUAL_PATTERN.search(user_input):
                jpeg_bytes = vision.buffer.get_jpeg_bytes()
                if jpeg_bytes:
                    print("[Vision] Querying VLM for visual observation...")
                    visual_context = vlm.describe_scene(jpeg_bytes)
                    if visual_context:
                        print(f"[Vision] Context: {visual_context}")

            # Collect proximity sensor context for LLM injection
            prox_context = proximity_monitor.get_sensor_context()
            if prox_context:
                print(f"[Proximity] Context: {prox_context}")

            # Query Chat LLM
            t_llm = time.time()
            tools, response_text, segments = chat.ask(
                user_input,
                visual_context=visual_context,
                sensor_context=prox_context,
            )
            t_done = time.time()
            timing = f"prep {int((t_llm - t_turn) * 1000)}ms | LLM {int((t_done - t_llm) * 1000)}ms"
            if t_heard:
                timing += f" | end-of-speech → reply {t_done - t_heard:.1f}s"
            print(f"  [Timing] {timing}")

            # Stop the filler timer in case we finished before 10s
            thinking_event.set()

            # Display speech, stream natural voice, and animate face on OLED
            try:
                robot.speak_segments(segments, audio_service=audio_service, interrupt_event=interrupt_event)
            except Exception as e:
                print(f"  [Audio Error: {e}] — continuing without audio")

            if interrupt_event.is_set():
                print("  [Exit command detected, interrupting...]")
                # Resume background systems so they're not stuck paused after this skip
                idle_manager.notify_speech_done()
                proximity_monitor.resume()
                autonomous_brain.resume()
                busy.clear()
                # Skip executing tools; the queued exit command is handled next turn
                continue

            # Execute movement actions & sequences
            for t in tools:
                action = t.get("action", "").lower()
                duration = float(t.get("duration", 0))

                if action in ["play_sequence", "sequence"]:
                    seq_name = t.get("sequence", t.get("name", "celebrate"))
                    print(f"Executing Sequence: {seq_name}")
                    robot.play_sequence(seq_name)
                    continue

                method = getattr(robot, action, None)
                if method and callable(method):
                    print(f"Executing: {action} ({duration}s)")
                    if action in ["forward", "backward", "left", "right", "stop"]:
                        method(duration)
                    else:
                        method()

            full_text = " ".join(txt for _, txt in segments).strip()
            display_text = re.sub(r'\[[^\]]*\]', '', full_text)
            display_text = re.sub(r'\s+([.,!?;:])', r'\1', display_text)
            display_text = re.sub(r'\s+', ' ', display_text).strip()
            emotions_list = [emo.upper() for emo, _ in segments if emo]
            emotions_str = f" [{ ' / '.join(dict.fromkeys(emotions_list)) }]" if emotions_list else ""
            print(f"\nAssistant{emotions_str}: {display_text}")

            # Short echo guard: speech that ended within 0.3 s of IKRU finishing is ignored
            busy_until[0] = time.time() + 0.3
            busy.clear()

            # Resume idle, proximity reflexes, and autonomous thoughts now that all activity is done
            idle_manager.notify_speech_done()
            proximity_monitor.resume()
            autonomous_brain.resume()

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
        if stop_listening:
            stop_listening(wait_for_stop=False)
        if audio_service:
            audio_service.stop()
        if vision:
            vision.stop()
        idle_manager.stop()
        if proximity_monitor:
            proximity_monitor.stop()
        if autonomous_brain:
            autonomous_brain.stop()
        robot.close()


if __name__ == "__main__":
    main()
