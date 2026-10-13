"""
===============================================================================
PROJECT IKRU — ULTRASONIC SENSOR LIVE DISTANCE
===============================================================================
Connects to the ESP32 Controller via WebSocket and shows the ultrasonic
distance (HC-SR04 on GPIO 18/19) in real time. Press Ctrl+C to exit.
===============================================================================
"""

import sys
import time
import json
import argparse
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "software"))
from ikru.net import Diagnosis, find_robot
from ikru.net.netinfo import HUB_ROBOT_IP

try:
    import websocket
except ImportError:
    print("Error: 'websocket-client' is required. Install via: pip install websocket-client")
    sys.exit(1)


def read_distance(ws, timeout=1.5):
    """Send GET_DISTANCE and wait for the {"type":"distance"} reply, skipping
    other broadcasts (obstacle_alert etc.). Returns cm, or None on timeout."""
    ws.send("GET_DISTANCE")
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(max(0.05, deadline - time.time()))
        try:
            reply = ws.recv()
        except websocket.WebSocketTimeoutException:
            return None
        if not reply or "distance" not in reply:
            continue
        try:
            data = json.loads(reply)
        except ValueError:
            continue
        if data.get("type") == "distance":
            return float(data.get("cm", -1.0))
    return None


def test_ultrasonic(ip=HUB_ROBOT_IP, port=81):
    result = find_robot([ip], port=port)
    if isinstance(result, Diagnosis):
        print(f"[-] Could not find the robot: {result.message}")
        for hint in result.hints:
            print(f"    -> {hint}")
        return

    ws_url = f"ws://{result.ip}:{port}/"
    try:
        ws = websocket.create_connection(ws_url, timeout=3.0)
    except Exception as e:
        print(f"[-] Found {result.ip} but the WebSocket failed: {e}")
        return

    print(f"[+] Connected to {result.describe()}. Live distance (Ctrl+C to exit):\n")
    try:
        while True:
            try:
                dist = read_distance(ws)
                if dist is None:
                    text = "no reply from ESP32"
                elif dist < 0 or dist >= 900:
                    text = "out of range"
                else:
                    text = f"{dist:6.1f} cm"
                print(f"\r  Distance: {text}" + " " * 20, end="", flush=True)
            except (websocket.WebSocketConnectionClosedException, ConnectionResetError, OSError):
                print("\n[-] Connection lost, reconnecting...")
                time.sleep(1.0)
                try:
                    ws = websocket.create_connection(ws_url, timeout=3.0)
                except Exception:
                    print("[-] Reconnect failed. Robot may be rebooting.")
                    break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[+] Stopped.")
    finally:
        try:
            ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IKRU Ultrasonic Live Distance")
    parser.add_argument("--ip", default=HUB_ROBOT_IP, help="ESP32 Controller IP")
    parser.add_argument("--port", type=int, default=81, help="WebSocket Port (default: 81)")
    args = parser.parse_args()

    test_ultrasonic(ip=args.ip, port=args.port)
