"""
===============================================================================
PROJECT IKRU — R2-D2 DROID SPEAKER DIAGNOSTIC & EMOTION SOUND TESTER
===============================================================================
Connects to the ESP32 Controller via WebSocket and triggers R2-D2 droid sounds
and OLED face animations on the SmartElex Digital Speaker Module (GPIO 25).

Use this script to:
1. Test your SmartElex speaker wiring (VCC -> 5V, GND -> GND, IN -> GPIO 25).
2. Adjust the volume using the blue potentiometer trimmer on the speaker module.
3. Preview and verify all 28 emotions and paralinguistic sounds.
===============================================================================
"""

import sys
import time
import argparse

try:
    import websocket
except ImportError:
    print("Error: 'websocket-client' is required. Install via: pip install websocket-client")
    sys.exit(1)


EMOTIONS_AND_SOUNDS = [
    # Visual OLED + Droid Voices
    "HAPPY",
    "GLEE",
    "SAD",
    "WORRIED",
    "FOCUSED",
    "ANNOYED",
    "SURPRISED",
    "SKEPTIC",
    "FRUSTRATED",
    "UNIMPRESSED",
    "SLEEPY",
    "SUSPICIOUS",
    "SQUINT",
    "ANGRY",
    "FURIOUS",
    "SCARED",
    "AWE",
    "NORMAL",
    # Paralinguistic Vocal Sounds
    "SIGH",
    "GASP",
    "GIGGLE",
    "LAUGHTER",
    "GROAN",
    "CLEAR_THROAT",
    "CRY",
    "WHISPER",
    "SNIFF",
    "COUGH",
    "SNEEZE",
    "INHALE",
    "EXHALE",
    "THINKING",
    "SUCCESS",
    "ERROR",
]


def test_robot_speaker(ip="192.168.1.34", port=81):
    ws_url = f"ws://{ip}:{port}/"
    print("\n" + "=" * 60)
    print("  PROJECT IKRU — SmartElex R2-D2 Speaker Diagnostic")
    print("=" * 60)
    print(f"Connecting to ESP32 at {ws_url}...")

    try:
        ws = websocket.create_connection(ws_url, timeout=7.0)
        print("[+] WebSocket connected successfully!")
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print("  1. Verify the ESP32 IP address matches your network.")
        print("  2. Ensure the ESP32 is powered on and running the updated controller firmware.")
        return

    print("\nSelect an option:")
    print("  1. Run quick sound sweep (Happy -> Sigh -> Gasp -> Giggle -> Groan -> Success)")
    print("  2. Run full 28-sound showcase (All expressions & vocalizations)")
    print("  3. Interactive sound prompt (Type any emotion/sound name or 'exit')")
    print("  4. Volume adjustment test tone (Loops a chirp so you can turn the blue trimmer)")

    try:
        choice = input("\nEnter choice [1-4] (default: 1): ").strip()
    except (KeyboardInterrupt, EOFError):
        ws.close()
        return

    if not choice:
        choice = "1"

    if choice == "1":
        demo_sounds = ["HAPPY", "SIGH", "GASP", "GIGGLE", "GROAN", "CLEAR_THROAT", "SUCCESS"]
        print(f"\n[+] Running quick sound sweep ({len(demo_sounds)} sounds)...")
        for snd in demo_sounds:
            print(f"  -> Triggering: [{snd}]")
            ws.send(snd)
            time.sleep(1.2)
        ws.send("NORMAL")
        print("[+] Done! Returned to normal.")

    elif choice == "2":
        print(f"\n[+] Running full sound showcase ({len(EMOTIONS_AND_SOUNDS)} sounds)...")
        for snd in EMOTIONS_AND_SOUNDS:
            print(f"  -> Playing: [{snd}]")
            ws.send(snd)
            time.sleep(1.3)
        ws.send("NORMAL")
        print("[+] Showcase complete!")

    elif choice == "3":
        print("\n[+] Entering interactive mode. Type sound name (e.g., 'happy', 'sigh', 'gasp') or 'exit':")
        while True:
            try:
                cmd = input("IKRU Sound > ").strip().upper()
            except (KeyboardInterrupt, EOFError):
                break
            if not cmd or cmd == "EXIT":
                break
            print(f"  -> Sending: {cmd}")
            ws.send(cmd)

        ws.send("NORMAL")

    elif choice == "4":
        print("\n[+] Continuous volume test tone active.")
        print("    Turn the BLUE POTENTIOMETER TRIMMER on the SmartElex module")
        print("    with a small screwdriver until the volume is comfortable.")
        print("    Press Ctrl+C to stop.\n")
        try:
            while True:
                ws.send("HAPPY")
                time.sleep(1.0)
                ws.send("SIGH")
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[+] Stopped test tone.")
            ws.send("STOP_AUDIO")
            ws.send("NORMAL")

    ws.close()
    print("[+] Test finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IKRU R2-D2 Speaker Diagnostic")
    parser.add_argument("--ip", default="192.168.1.34", help="ESP32 Robot Controller IP")
    parser.add_argument("--port", type=int, default=81, help="WebSocket port (default: 81)")
    args = parser.parse_args()

    test_robot_speaker(ip=args.ip, port=args.port)
