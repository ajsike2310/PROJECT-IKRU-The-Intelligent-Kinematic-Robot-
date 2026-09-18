"""
===============================================================================
PROJECT IKRU — MOTOR DIAGNOSTIC & WIRING TESTER
===============================================================================
Connects to the ESP32 Controller via WebSocket and tests motor commands.

Use this script to verify:
1. DRV8833 power supply (VM / battery switch).
2. ESP32 to DRV8833 pin wiring (IN1-IN4, nSLEEP).
3. Motor rotation direction (Left vs Right).
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


def test_motors(ip="172.24.239.144", port=81):
    ws_url = f"ws://{ip}:{port}/"
    print("\n" + "=" * 60)
    print("  PROJECT IKRU — Motor & DRV8833 Diagnostic Tool")
    print("=" * 60)
    print(f"Connecting to ESP32 at {ws_url}...")

    try:
        ws = websocket.create_connection(ws_url, timeout=5.0)
        print("[+] WebSocket connected successfully!")
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        return

    print("\nSelect a motor test:")
    print("  1. Move FORWARD for 3 seconds")
    print("  2. Move BACKWARD for 3 seconds")
    print("  3. Turn LEFT for 2 seconds")
    print("  4. Turn RIGHT for 2 seconds")
    print("  5. Continuous FORWARD (press Ctrl+C or Enter to stop — good for voltmeter/LED check)")
    print("  6. Emergency STOP")

    try:
        choice = input("\nEnter choice [1-6] (default: 1): ").strip()
    except (KeyboardInterrupt, EOFError):
        ws.close()
        return

    if not choice:
        choice = "1"

    if choice == "1":
        print("\n[+] Sending FORWARD for 3 seconds...")
        ws.send("FORWARD")
        time.sleep(3.0)
        ws.send("STOP")
        print("[+] Sent STOP. Test complete.")

    elif choice == "2":
        print("\n[+] Sending BACKWARD for 3 seconds...")
        ws.send("BACKWARD")
        time.sleep(3.0)
        ws.send("STOP")
        print("[+] Sent STOP. Test complete.")

    elif choice == "3":
        print("\n[+] Sending LEFT for 2 seconds...")
        ws.send("LEFT")
        time.sleep(2.0)
        ws.send("STOP")
        print("[+] Sent STOP. Test complete.")

    elif choice == "4":
        print("\n[+] Sending RIGHT for 2 seconds...")
        ws.send("RIGHT")
        time.sleep(2.0)
        ws.send("STOP")
        print("[+] Sent STOP. Test complete.")

    elif choice == "5":
        print("\n[+] Continuous FORWARD is ACTIVE.")
        print("    Check the DRV8833 input pins and motor terminals.")
        print("    Press Enter to STOP...\n")
        ws.send("FORWARD")
        try:
            input("Press [Enter] to STOP: ")
        except (KeyboardInterrupt, EOFError):
            pass
        ws.send("STOP")
        print("[+] Sent STOP.")

    elif choice == "6":
        ws.send("STOP")
        print("[+] Sent STOP.")

    ws.close()
    print("[+] Disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IKRU Motor Diagnostic")
    parser.add_argument("--ip", default="172.24.239.144", help="ESP32 Robot Controller IP")
    parser.add_argument("--port", type=int, default=81, help="WebSocket port (default: 81)")
    args = parser.parse_args()

    test_motors(ip=args.ip, port=args.port)
