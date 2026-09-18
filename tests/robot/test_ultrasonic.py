"""
===============================================================================
PROJECT IKRU — ULTRASONIC SENSOR & SAFETY BRAKE DIAGNOSTIC TOOL
===============================================================================
Connects to the ESP32 Controller via WebSocket and tests:
1. Real-time ultrasonic distance readings (HC-SR04 / HC-SR04P on GPIO 18/19).
2. Live visual terminal distance meter.
3. Autonomous safety emergency brake (auto-stopping when distance < 12cm).
===============================================================================
"""

import sys
import time
import json
import argparse

try:
    import websocket
except ImportError:
    print("Error: 'websocket-client' is required. Install via: pip install websocket-client")
    sys.exit(1)


def render_distance_bar(dist_cm, max_cm=100, bar_length=30):
    if dist_cm < 0 or dist_cm >= 999:
        return "[ Out of Range / Timeout ]"
    
    clamped = max(0.0, min(float(dist_cm), float(max_cm)))
    filled_len = int(round(bar_length * (clamped / max_cm)))
    bar = "█" * filled_len + "░" * (bar_length - filled_len)
    return f"[{bar}] {dist_cm:5.1f} cm"


def test_ultrasonic(ip="192.168.1.34", port=81):
    candidates = [ip, "ikru-robot.local", "ikru.local", "192.168.1.42", "192.168.4.1"]
    ws = None
    connected_ip = None

    print("\n" + "=" * 65)
    print("  PROJECT IKRU — Ultrasonic Sensor & Safety Brake Diagnostic")
    print("=" * 65)
    
    for candidate in candidates:
        if not candidate:
            continue
        ws_url = f"ws://{candidate}:{port}/"
        try:
            print(f"Connecting to ESP32 at {ws_url}...")
            ws = websocket.create_connection(ws_url, timeout=3.0)
            connected_ip = candidate
            print(f"[+] Connected successfully to {candidate}!\n")
            break
        except Exception:
            continue

    if not ws:
        print("[-] Could not connect to ESP32. Please verify your robot's IP and Wi-Fi.")
        return

    print("Select Mode:")
    print("  1. Continuous Live Distance Monitor (Wave your hand in front of sensor)")
    print("  2. Test Safety Brake (Drives forward; verify it halts at obstacle)")
    print("  3. Custom Obstacle Threshold Config (e.g. set to 15 cm)")
    
    try:
        choice = input("\nEnter choice [1-3] (default: 1): ").strip()
    except (KeyboardInterrupt, EOFError):
        ws.close()
        return

    if not choice:
        choice = "1"

    if choice == "1":
        print("\n[+] Starting live distance monitor. Press Ctrl+C to exit...\n")
        timeout_count = 0
        try:
            while True:
                try:
                    ws.send("GET_DISTANCE")
                    ws.settimeout(1.5)
                    reply = ws.recv()
                    if reply and "distance" in reply:
                        data = json.loads(reply)
                        dist = float(data.get("cm", -1.0))
                        
                        if dist < 0 or dist >= 900:
                            timeout_count += 1
                        else:
                            timeout_count = 0

                        status = "🟢 PATH CLEAR"
                        if dist > 0 and dist < 12.0:
                            status = "🔴 OBSTACLE DETECTED (<12 cm) [BRAKE ACTIVE]"
                        elif dist > 0 and dist < 25.0:
                            status = "🟡 APPROACHING OBJECT"

                        meter = render_distance_bar(dist)
                        
                        hint = ""
                        if timeout_count >= 15:
                            hint = " 💡 [TIP: Check if VCC is connected to 5V/VIN and TRIG/ECHO are on GPIO 18/19]"
                        
                        print(f"\r  {meter}  |  {status}{hint}   ", end="", flush=True)
                except (websocket.WebSocketConnectionClosedException, ConnectionResetError, OSError) as conn_err:
                    print(f"\n[-] Connection interrupted: {conn_err}")
                    print("[*] Reconnecting in 1 second...")
                    time.sleep(1.0)
                    try:
                        ws = websocket.create_connection(ws_url, timeout=3.0)
                        print("[+] Reconnected!")
                    except Exception:
                        print("[-] Reconnect failed. Robot may be rebooting.")
                        break
                time.sleep(0.12)
        except KeyboardInterrupt:
            print("\n\n[+] Live monitor stopped.")

    elif choice == "2":
        print("\n[+] Safety Brake Test:")
        print("  Place an obstacle (like a box or your hand) ~30-40 cm in front of IKRU.")
        print("  IKRU will drive FORWARD. If the sensor works, it will automatically STOP before hitting it!")
        input("\nPress Enter to begin test...")
        
        print("\n[+] Sending FORWARD command...")
        ws.send("FORWARD")
        
        start_time = time.time()
        stopped = False
        while time.time() - start_time < 4.0:
            ws.send("GET_DISTANCE")
            try:
                reply = ws.recv()
                if reply and "distance" in reply:
                    data = json.loads(reply)
                    dist = float(data.get("cm", 999.0))
                    print(f"  Distance: {dist:.1f} cm")
                    if dist > 0 and dist < 12.0:
                        print("\n[+] Success! Obstacle detected, ESP32 auto-brake engaged!")
                        stopped = True
                        break
            except Exception:
                pass
            time.sleep(0.06)

        ws.send("STOP")
        if not stopped:
            print("\n[*] Timed out after 4 seconds.")

    elif choice == "3":
        try:
            th = input("\nEnter new obstacle safety threshold in cm (e.g. 15): ").strip()
            th_val = float(th)
            ws.send(f"SET_OBSTACLE_THRESHOLD:{th_val:.1f}")
            print(f"[+] Sent SET_OBSTACLE_THRESHOLD:{th_val:.1f}")
        except ValueError:
            print("[-] Invalid number.")

    ws.close()
    print("[+] Test completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IKRU Ultrasonic Diagnostic")
    parser.add_argument("--ip", default="192.168.1.34", help="ESP32 Controller IP")
    parser.add_argument("--port", type=int, default=81, help="WebSocket Port (default: 81)")
    args = parser.parse_args()

    test_ultrasonic(ip=args.ip, port=args.port)
