"""
IKRU Companion Studio — Backend Server
======================================
Lightweight local HTTP API and web server (zero external pip requirements)
serving the IKRU portable launcher and diagnostic control dashboard.
"""

import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_DIR = PROJECT_ROOT / "software"
FIRMWARE_INO = PROJECT_ROOT / "firmware" / "controller" / "controller.ino"
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))

from ikru.robot import RobotController
from ikru.audio import AudioService

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Global states
assistant_process = None
assistant_logs = []
assistant_lock = threading.Lock()
cached_audio_service = None
audio_lock = threading.Lock()
cached_robot_controller = None
robot_ctrl_lock = threading.Lock()


def get_robot_controller(ip="192.168.1.42"):
    global cached_robot_controller
    resolved_ip = resolve_robot_ip(ip)
    with robot_ctrl_lock:
        if (
            cached_robot_controller is None
            or cached_robot_controller.ip != resolved_ip
            or not cached_robot_controller.connected
            or cached_robot_controller.ws is None
        ):
            if cached_robot_controller:
                try:
                    cached_robot_controller.close()
                except Exception:
                    pass
            cached_robot_controller = RobotController(ip=resolved_ip, auto_reconnect=True)
        return cached_robot_controller


def get_audio_service(robot_ip="192.168.1.42", voice="guy", play_pc=True):
    global cached_audio_service
    with audio_lock:
        if cached_audio_service is None or cached_audio_service.robot_ip != robot_ip:
            if cached_audio_service:
                cached_audio_service.stop()
            cached_audio_service = AudioService(robot_ip=robot_ip, voice=voice, play_pc=play_pc)
        else:
            cached_audio_service.set_play_pc(play_pc)
            if voice:
                cached_audio_service.set_voice(voice)
        return cached_audio_service


def detect_local_ip(target_ip="192.168.1.34"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_ip, 81))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def check_tcp_port(ip, port, timeout=0.6):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, int(port)))
        s.close()
        return result == 0
    except Exception:
        return False


def check_ollama():
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "IKRU"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                has_qwen = any("qwen2.5" in m for m in models)
                return {"running": True, "models": models, "has_qwen": has_qwen}
    except Exception as e:
        return {"running": False, "models": [], "has_qwen": False, "error": str(e)}
    return {"running": False, "models": [], "has_qwen": False}


def scan_network_for_robot(base_subnet=None):
    """Scans high-probability IPs and local subnet for reachable port 81 (ESP32)."""
    candidates = [
        "192.168.1.42", "192.168.1.34", "192.168.4.2", "192.168.1.37", "192.168.1.40",
        "192.168.4.3", "192.168.4.4", "192.168.1.85", "192.168.1.100"
    ]
    found = []

    # Check candidates first
    for ip in candidates:
        if check_tcp_port(ip, 81, timeout=0.4):
            if ip not in found:
                found.append(ip)

    # Fast scan local subnet if not found in top candidates
    if not found:
        local_ip = detect_local_ip()
        parts = local_ip.split(".")
        if len(parts) == 4:
            prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
            scan_ips = [f"{prefix}.{i}" for i in range(1, 60)]
            with ThreadPoolExecutor(max_workers=30) as executor:
                futures = {executor.submit(check_tcp_port, ip, 81, 0.4): ip for ip in scan_ips}
                for f in futures:
                    ip = futures[f]
                    try:
                        if f.result() and ip not in found:
                            found.append(ip)
                    except Exception:
                        pass

    return found


def get_firmware_wifi():
    try:
        if FIRMWARE_INO.exists():
            content = FIRMWARE_INO.read_text(encoding="utf-8")
            ssid_m = re.search(r'const\s+char\s*\*\s*primary_ssid\s*=\s*"([^"]*)";', content)
            pass_m = re.search(r'const\s+char\s*\*\s*primary_pass\s*=\s*"([^"]*)";', content)
            ssid = ssid_m.group(1) if ssid_m else "GNXS-2.4G-C457E1"
            pwd = pass_m.group(1) if pass_m else ""
            return {"ssid": ssid, "pass": pwd}
    except Exception as e:
        print(f"[Firmware Config] Read error: {e}")
    return {"ssid": "GNXS-2.4G-C457E1", "pass": "1234567890"}


def set_firmware_wifi(ssid: str, pwd: str):
    try:
        if FIRMWARE_INO.exists():
            content = FIRMWARE_INO.read_text(encoding="utf-8")
            content = re.sub(
                r'const\s+char\s*\*\s*primary_ssid\s*=\s*"[^"]*";',
                f'const char *primary_ssid = "{ssid}";',
                content
            )
            content = re.sub(
                r'const\s+char\s*\*\s*primary_pass\s*=\s*"[^"]*";',
                f'const char *primary_pass = "{pwd}";',
                content
            )
            FIRMWARE_INO.write_text(content, encoding="utf-8")
            return True
    except Exception as e:
        print(f"[Firmware Config] Write error: {e}")
    return False


def get_serial_ports():
    try:
        import serial.tools.list_ports
        return [{"port": p.device, "description": p.description} for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


def send_serial_wifi(port: str, ssid: str, pwd: str):
    try:
        import serial
        ser = serial.Serial(port, 115200, timeout=1)
        time.sleep(0.3)
        cmd = f"SET_WIFI:{ssid}:{pwd}\n"
        ser.write(cmd.encode("utf-8"))
        lines = []
        t_end = time.time() + 6.0
        while time.time() < t_end:
            if ser.in_waiting:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if line:
                    lines.append(line)
                    if "Connected!" in line or "IP Address:" in line:
                        break
            else:
                time.sleep(0.1)
        ser.close()
        return {"status": "ok", "message": "Wi-Fi credentials sent via USB Serial", "output": lines}
    except Exception as e:
        err_str = str(e)
        if "Access is denied" in err_str or "PermissionError" in err_str:
            return {"status": "error", "message": f"Port {port} is busy! Please close Arduino IDE Serial Monitor and retry."}
        return {"status": "error", "message": str(e)}


def resolve_robot_ip(target_ip: str) -> str:
    """Checks target_ip on port 81; if unreachable, auto-resolves to active robot IP."""
    if check_tcp_port(target_ip, 81, timeout=0.5):
        return target_ip
    for candidate in ["192.168.1.42", "192.168.1.34", "192.168.4.2", "192.168.1.37", "192.168.1.40"]:
        if candidate != target_ip and check_tcp_port(candidate, 81, timeout=0.3):
            return candidate
    found = scan_network_for_robot()
    if found:
        return found[0]
    return target_ip


def log_reader_thread(proc):
    global assistant_logs
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        with assistant_lock:
            assistant_logs.append(line.rstrip())
            if len(assistant_logs) > 200:
                assistant_logs.pop(0)


class StudioHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # Suppress routine GET logging to keep terminal clean

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            query = urllib.parse.parse_qs(parsed.query)
            target_ip = query.get("ip", ["192.168.1.42"])[0]
            cam_ip = query.get("cam_ip", ["192.168.4.1"])[0]

            robot_reachable = check_tcp_port(target_ip, 81, timeout=0.6)
            if not robot_reachable:
                resolved = resolve_robot_ip(target_ip)
                if resolved != target_ip and check_tcp_port(resolved, 81, timeout=0.3):
                    target_ip = resolved
                    robot_reachable = True

            cam_reachable = check_tcp_port(cam_ip, 2222, timeout=0.3)
            ollama_stat = check_ollama()
            local_ip = detect_local_ip(target_ip)

            is_running = assistant_process is not None and assistant_process.poll() is None

            data = {
                "robot_ip": target_ip,
                "robot_connected": robot_reachable,
                "cam_ip": cam_ip,
                "cam_connected": cam_reachable,
                "local_ip": local_ip,
                "ollama": ollama_stat,
                "assistant_running": is_running,
            }
            return self._send_json(data)

        elif path == "/api/scan":
            found = scan_network_for_robot()
            return self._send_json({"found_robots": found})

        elif path == "/api/assistant/logs":
            with assistant_lock:
                logs = list(assistant_logs)
            is_running = assistant_process is not None and assistant_process.poll() is None
            return self._send_json({"logs": logs, "running": is_running})

        elif path == "/api/wifi/config":
            return self._send_json(get_firmware_wifi())

        elif path == "/api/serial/ports":
            return self._send_json({"ports": get_serial_ports()})

        # Default static file handling
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            payload = json.loads(post_body.decode("utf-8"))
        except Exception:
            payload = {}

        # Wi-Fi Provisioning & Configuration
        if path == "/api/wifi/config":
            ssid = payload.get("ssid", "").strip()
            pwd = payload.get("pass", "").strip()
            ok = set_firmware_wifi(ssid, pwd)
            return self._send_json({"status": "ok" if ok else "error", "ssid": ssid})

        elif path == "/api/serial/wifi":
            port = payload.get("port", "COM7")
            ssid = payload.get("ssid", "").strip()
            pwd = payload.get("pass", "").strip()
            res = send_serial_wifi(port, ssid, pwd)
            status_code = 200 if res.get("status") == "ok" else 400
            return self._send_json(res, status=status_code)

        elif path == "/api/robot/wifi":
            target_ip = payload.get("ip", "192.168.1.34")
            resolved_ip = resolve_robot_ip(target_ip)
            ssid = payload.get("ssid", "").strip()
            pwd = payload.get("pass", "").strip()
            try:
                import websocket
                ws = websocket.create_connection(f"ws://{resolved_ip}:81", timeout=2.0)
                ws.send(f"SET_WIFI:{ssid}:{pwd}")
                ws.close()
                return self._send_json({"status": "ok", "resolved_ip": resolved_ip, "message": f"Sent Wi-Fi update to robot at {resolved_ip}"})
            except Exception as e:
                return self._send_json({"status": "error", "message": str(e)}, status=500)

        # 1. Test Emotion
        elif path == "/api/test/emotion":
            target_ip = payload.get("ip", "192.168.1.42")
            emotion = payload.get("emotion", "HAPPY").upper()
            try:
                robot = get_robot_controller(target_ip)
                if not robot.connected:
                    return self._send_json({"status": "error", "message": f"Could not reach robot at ws://{robot.ip}:81"}, status=500)
                robot.set_emotion(emotion)
                return self._send_json({"status": "ok", "emotion": emotion, "resolved_ip": robot.ip})
            except Exception as e:
                return self._send_json({"status": "error", "message": str(e)}, status=500)

        # 2. Test Movement
        elif path == "/api/test/move":
            target_ip = payload.get("ip", "192.168.1.42")
            action = payload.get("action", "STOP").upper()
            duration = float(payload.get("duration", 0.5))
            try:
                robot = get_robot_controller(target_ip)
                if not robot.connected:
                    return self._send_json({"status": "error", "message": f"Could not reach robot at ws://{robot.ip}:81"}, status=500)
                robot.send(action)
                if duration > 0 and action != "STOP":
                    time.sleep(duration)
                    robot.send("STOP")
                return self._send_json({"status": "ok", "action": action, "resolved_ip": robot.ip})
            except Exception as e:
                return self._send_json({"status": "error", "message": str(e)}, status=500)

        # 3. Test Speech
        elif path == "/api/test/speak":
            target_ip = payload.get("ip", "192.168.1.42")
            text = payload.get("text", "Hello! I am Ikru, your kinematic desk robot.")
            voice = payload.get("voice", "guy")
            play_pc = bool(payload.get("play_pc", False))

            try:
                robot = get_robot_controller(target_ip)
                resolved_ip = robot.ip
                svc = get_audio_service(robot_ip=resolved_ip, voice=voice, play_pc=play_pc)
                url = svc.synthesize(text, play_pc=play_pc, voice=voice)
                if url:
                    if robot.connected:
                        robot.play_audio(url)
                    return self._send_json({"status": "ok", "url": url, "resolved_ip": resolved_ip, "duration": svc.last_duration})
                else:
                    return self._send_json({"status": "error", "message": "TTS synthesis failed (requires internet for Edge-TTS)"}, status=500)
            except Exception as e:
                return self._send_json({"status": "error", "message": str(e)}, status=500)

        # 4. Start Assistant
        elif path == "/api/assistant/start":
            global assistant_process, assistant_logs
            with assistant_lock:
                if assistant_process is not None and assistant_process.poll() is None:
                    return self._send_json({"status": "already_running"})

                # Release studio-held robot WebSocket and audio server so main.py gets full ownership
                global cached_robot_controller, cached_audio_service
                with robot_ctrl_lock:
                    if cached_robot_controller is not None:
                        try:
                            cached_robot_controller.close()
                        except Exception:
                            pass
                        cached_robot_controller = None
                with audio_lock:
                    if cached_audio_service is not None:
                        cached_audio_service.stop()
                        cached_audio_service = None
                        time.sleep(0.3)

                assistant_logs = []
                target_ip = payload.get("ip", "192.168.1.34")
                cam_ip = payload.get("cam_ip", "192.168.4.1")
                play_pc = payload.get("play_pc", False)
                no_mic = payload.get("no_mic", False)
                no_vision = payload.get("no_vision", False)

                cmd = [
                    sys.executable,
                    str(SOFTWARE_DIR / "ikru" / "main.py"),
                    "--ip", target_ip,
                    "--cam-ip", cam_ip,
                ]
                if play_pc:
                    cmd.append("--pc-audio")
                if no_mic:
                    cmd.append("--no-mic")
                if no_vision:
                    cmd.append("--no-vision")

                assistant_logs.append(f"[Launcher] Starting: {' '.join(cmd)}")

                sub_env = os.environ.copy()
                sub_env["PYTHONIOENCODING"] = "utf-8"

                assistant_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(PROJECT_ROOT),
                    env=sub_env
                )

                t = threading.Thread(target=log_reader_thread, args=(assistant_process,), daemon=True)
                t.start()

                return self._send_json({"status": "started", "pid": assistant_process.pid})

        # 5. Stop Assistant
        elif path == "/api/assistant/stop":
            with assistant_lock:
                if assistant_process is not None and assistant_process.poll() is None:
                    assistant_process.terminate()
                    assistant_logs.append("[Launcher] Sent terminate signal to assistant.")
                    time.sleep(0.5)
                    if assistant_process.poll() is None:
                        assistant_process.kill()
                    assistant_process = None
                return self._send_json({"status": "stopped"})

        self.send_error(404, "Endpoint not found")


def run_studio_server(port=5000):
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), StudioHandler)
    server.allow_reuse_address = True
    print(f"\n========================================================")
    print(f"  PROJECT IKRU — Companion Studio & Control Dashboard")
    print(f"  Running at: http://localhost:{port}/")
    print(f"========================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        global cached_audio_service, cached_robot_controller, assistant_process
        if cached_robot_controller:
            try:
                cached_robot_controller.close()
            except Exception:
                pass
        if cached_audio_service:
            cached_audio_service.stop()
        if assistant_process and assistant_process.poll() is None:
            assistant_process.terminate()


if __name__ == "__main__":
    run_studio_server()
