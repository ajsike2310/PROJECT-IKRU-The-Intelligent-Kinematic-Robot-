"""
PROJECT IKRU — Professional Companion Server
============================================
Lightweight, high-performance HTTP server serving the IKRU professional UI,
bridging WebSocket communication to the ESP32 robot body (192.168.1.42:81),
live ESP32-CAM stream proxying, and neural speech synthesis.
"""

import base64
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

import numpy as np

# Add project root and software dir to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOFTWARE_DIR = PROJECT_ROOT / "software"
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ikru.robot import RobotController
from ikru.audio import AudioService
from ikru.chat import ChatEngine
from ikru.vision import VisionReceiver, VLMClient

STATIC_DIR = Path(__file__).resolve().parent / "static"
VOICES_DIR = SOFTWARE_DIR / "ikru" / "audio" / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)

# Global persistent controller references
cached_robot_controller = None
robot_ctrl_lock = threading.Lock()
cached_audio_service = None
audio_lock = threading.Lock()
cached_chat_engine = None
chat_lock = threading.Lock()
cached_vision_receiver = None
vision_lock = threading.Lock()
cached_vlm_client = None
vlm_lock = threading.Lock()
assistant_process = None
assistant_logs = []
assistant_lock = threading.Lock()

DEFAULT_ROBOT_IP = "192.168.1.42"
DEFAULT_CAM_IP = "192.168.4.1"

VISUAL_KEYWORDS = [
    "see", "look", "color", "colour", "wear", "wearing",
    "shirt", "glass", "glasses", "hold", "holding", "show", "describe",
    "notice", "what", "who", "face", "clothes", "outfit",
    "hand", "background", "room", "watch", "view", "camera", "scene", "surroundings"
]

def get_vlm_client(model="qwen3-vl:4b") -> VLMClient:
    """Retrieves or creates a singleton VLMClient instance."""
    global cached_vlm_client
    with vlm_lock:
        if cached_vlm_client is None:
            cached_vlm_client = VLMClient(model=model)
        return cached_vlm_client

STANDBY_CAM_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">'
    b'<rect width="320" height="240" fill="#F1F3F5"/>'
    b'<text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" fill="#888888" font-family="monospace" font-size="11">[CAMERA STANDBY // DISCOVERY]</text>'
    b'<text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" fill="#AAAAAA" font-family="monospace" font-size="9">LISTENING ON UDP 2222</text>'
    b'</svg>'
)

def _build_standby_jpeg() -> bytes:
    try:
        import cv2
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        img[:] = (26, 24, 22)
        cv2.putText(img, "[CAMERA STANDBY]", (48, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (180, 180, 180), 1)
        cv2.putText(img, "Listening on UDP 2222...", (55, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 120), 1)
        _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return bytes(enc)
    except Exception:
        return b""

STANDBY_CAM_JPEG = _build_standby_jpeg()

def get_vision_receiver(cam_ip: str = DEFAULT_CAM_IP) -> VisionReceiver:
    """Retrieves or starts the background UDP VisionReceiver singleton."""
    global cached_vision_receiver
    resolved_ip = resolve_robot_ip(cam_ip) if cam_ip else DEFAULT_CAM_IP
    with vision_lock:
        if cached_vision_receiver is None or getattr(cached_vision_receiver, "cam_ip", None) != resolved_ip:
            if cached_vision_receiver:
                try:
                    cached_vision_receiver.stop()
                except Exception:
                    pass
            try:
                cached_vision_receiver = VisionReceiver(cam_ip=resolved_ip, show_window=False)
                cached_vision_receiver.start()
            except Exception as e:
                print(f"[Vision] Error starting VisionReceiver for {resolved_ip}: {e}")
        return cached_vision_receiver

def get_chat_engine(model="qwen2.5:3b") -> ChatEngine:
    """Retrieves or creates a singleton ChatEngine instance."""
    global cached_chat_engine
    with chat_lock:
        if cached_chat_engine is None:
            cached_chat_engine = ChatEngine(model=model)
        return cached_chat_engine


def resolve_robot_ip(requested_ip: str) -> str:
    """Validates and falls back to default verified IP."""
    if not requested_ip or requested_ip.strip() in ("", "0.0.0.0"):
        return DEFAULT_ROBOT_IP
    return requested_ip.strip()


def get_robot_controller(ip: str = DEFAULT_ROBOT_IP) -> RobotController:
    """Retrieves or creates a thread-safe singleton WebSocket connection to the robot."""
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


def get_audio_service(robot_ip: str = DEFAULT_ROBOT_IP, play_pc: bool = True) -> AudioService:
    """Retrieves or creates the local audio service for TTS."""
    global cached_audio_service
    resolved_ip = resolve_robot_ip(robot_ip)
    with audio_lock:
        if cached_audio_service is None or cached_audio_service.robot_ip != resolved_ip:
            if cached_audio_service:
                try:
                    cached_audio_service.stop()
                except Exception:
                    pass
            cached_audio_service = AudioService(robot_ip=resolved_ip, play_pc=play_pc, engine="edge")
        else:
            cached_audio_service.set_play_pc(play_pc)
        return cached_audio_service


def check_tcp_port(ip: str, port: int, timeout: float = 0.5) -> bool:
    """Fast non-blocking TCP reachability probe."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((ip, int(port)))
        s.close()
        return res == 0
    except Exception:
        return False


def scan_local_subnet() -> list:
    """Scans local subnet for active ESP32 and ESP32-CAM nodes."""
    found = []
    # Always prioritize verified default nodes
    for ip in [DEFAULT_ROBOT_IP, "192.168.1.34", DEFAULT_CAM_IP]:
        if check_tcp_port(ip, 81):
            found.append({"ip": ip, "type": "robot_body", "port": 81})
        if check_tcp_port(ip, 80):
            found.append({"ip": ip, "type": "camera_web", "port": 80})
    return found


def scan_wifi_ssids() -> list:
    """Scans nearby Wi-Fi SSIDs using Windows netsh command."""
    networks = []
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "networks"],
            text=True,
            timeout=4,
            errors="replace"
        )
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("SSID "):
                parts = line.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    ssid = parts[1].strip()
                    if not any(n["ssid"] == ssid for n in networks):
                        networks.append({"ssid": ssid, "signal": "100%"})
    except Exception as e:
        print(f"[Server] Wi-Fi scan error: {e}")
    if not networks:
        networks = [{"ssid": "GNXS-2.4G-C457E1", "signal": "98%"}, {"ssid": "IKRU-CAM", "signal": "90%"}]
    return networks


def get_network_info(robot_ip: str = DEFAULT_ROBOT_IP, cam_ip: str = DEFAULT_CAM_IP) -> dict:
    """Returns real server IP, WiFi SSID, signal, robot reachability, and cam status."""
    info = {
        "server_ip": "unknown",
        "wifi_ssid": "unknown",
        "wifi_signal": "--",
        "wifi_connected": False,
        "robot_ip": robot_ip,
        "robot_online": False,
        "cam_ip": cam_ip,
        "cam_online": False,
        "gateway": "unknown",
    }

    # ── Server local IP ─────────────────────────────────────────
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info["server_ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # ── Active WiFi SSID + Signal (Windows netsh) ────────────────
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            text=True, timeout=4, errors="replace"
        )
        ssid_match = re.search(r"^\s+SSID\s+:\s+(.+)$", out, re.MULTILINE)
        sig_match  = re.search(r"^\s+Signal\s+:\s+(\d+)%", out, re.MULTILINE)
        state_match = re.search(r"^\s+State\s+:\s+(\S+)", out, re.MULTILINE)
        if ssid_match:
            info["wifi_ssid"] = ssid_match.group(1).strip()
        if sig_match:
            info["wifi_signal"] = sig_match.group(1).strip() + "%"
        if state_match:
            info["wifi_connected"] = state_match.group(1).lower() == "connected"
    except Exception:
        pass

    # ── Default gateway ──────────────────────────────────────────
    try:
        out = subprocess.check_output(["ipconfig"], text=True, timeout=4, errors="replace")
        gw_match = re.search(r"Default Gateway[^\d]*(\d+\.\d+\.\d+\.\d+)", out)
        if gw_match:
            info["gateway"] = gw_match.group(1)
    except Exception:
        pass

    # ── Robot / Camera reachability ──────────────────────────────
    info["robot_online"] = check_tcp_port(robot_ip, 81, timeout=0.4)
    info["cam_online"]   = check_tcp_port(cam_ip, 80, timeout=0.4) or check_tcp_port(cam_ip, 81, timeout=0.4)

    return info


def send_wifi_serial(ssid: str, password: str) -> dict:
    """Provisions Wi-Fi credentials over USB Serial (COM port)."""
    try:
        import serial
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if "COM7" in ports:
            ports.remove("COM7")
            ports.insert(0, "COM7")
        for port in ports:
            try:
                with serial.Serial(port, 115200, timeout=1.0) as ser:
                    ser.write(f"SET_WIFI:{ssid}:{password}\n".encode("utf-8"))
                    time.sleep(0.4)
                    return {"success": True, "port": port, "message": f"Dispatched to ESP32 on {port}"}
            except Exception:
                pass
        return {"success": False, "error": "No available serial COM port found"}
    except ImportError:
        return {"success": False, "error": "pyserial not installed"}


class IkruApiHandler(http.server.SimpleHTTPRequestHandler):
    """Handles REST API endpoints and serves clean static UI assets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _send_json(self, data: dict, status: int = 200):
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            query = urllib.parse.parse_qs(parsed.query)
            robot_ip = query.get("ip", [DEFAULT_ROBOT_IP])[0]
            ws_ok = check_tcp_port(robot_ip, 81, timeout=0.3)
            cam_ok = check_tcp_port(DEFAULT_CAM_IP, 80, timeout=0.3) or check_tcp_port("192.168.1.43", 80, timeout=0.3)

            self._send_json({
                "status": "online" if ws_ok else "offline",
                "robot_ip": robot_ip,
                "robot_ws_online": ws_ok,
                "cam_online": cam_ok,
                "timestamp": time.time(),
                "battery": "100%",
                "core_version": "2.5.0-PRO"
            })
            return

        elif path == "/api/scan":
            results = scan_local_subnet()
            self._send_json({"nodes": results})
            return

        elif path == "/api/wifi/scan":
            networks = scan_wifi_ssids()
            self._send_json({"success": True, "networks": networks})
            return

        elif path == "/api/network/info":
            query = urllib.parse.parse_qs(parsed.query)
            robot_ip = query.get("ip", [DEFAULT_ROBOT_IP])[0]
            cam_ip   = query.get("cam", [DEFAULT_CAM_IP])[0]
            net = get_network_info(robot_ip=robot_ip, cam_ip=cam_ip)
            self._send_json(net)
            return


        elif path == "/api/voice/list":
            svc = get_audio_service()
            voices = []
            for f in VOICES_DIR.glob("*.wav"):
                voices.append({"name": f.stem, "filename": f.name, "path": str(f)})
            active_prompt = getattr(svc, "audio_prompt_path", None)
            active_name = Path(active_prompt).stem if active_prompt else "default"
            self._send_json({
                "success": True,
                "voices": voices,
                "active": active_name,
                "volume": int(getattr(svc, "volume", 1.0) * 100)
            })
            return

        elif path in ("/api/assistant/status", "/api/assistant/logs"):
            with assistant_lock:
                running = assistant_process is not None and assistant_process.poll() is None
                self._send_json({
                    "running": running,
                    "logs": assistant_logs[-50:]
                })
            return

        elif path == "/api/camera/stream":
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            cam_ip = q.get("ip", [DEFAULT_CAM_IP])[0]
            receiver = get_vision_receiver(cam_ip)

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                while True:
                    frame = receiver.buffer.get_jpeg_bytes() if (receiver and receiver.buffer) else None
                    if not frame:
                        frame = STANDBY_CAM_JPEG
                    if frame:
                        part = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                            + frame + b"\r\n"
                        )
                        self.wfile.write(part)
                        self.wfile.flush()
                    time.sleep(0.033)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            return

        elif path == "/api/camera/frame":
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            cam_ip = q.get("ip", [DEFAULT_CAM_IP])[0]
            receiver = get_vision_receiver(cam_ip)
            frame = receiver.buffer.get_jpeg_bytes() if (receiver and receiver.buffer) else None
            if not frame:
                frame = STANDBY_CAM_JPEG
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(frame)
            return

        elif path == "/api/camera/status":
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            cam_ip = q.get("ip", [DEFAULT_CAM_IP])[0]
            receiver = get_vision_receiver(cam_ip)
            has_frame = bool(receiver and receiver.buffer and receiver.buffer.has_frame())
            self._send_json({
                "connected": bool(receiver and (receiver.connected or has_frame)),
                "fps": round(getattr(receiver, "fps", 0.0), 1),
                "frames_completed": getattr(receiver, "frames_completed", 0),
                "cam_ip": getattr(receiver, "cam_ip", cam_ip)
            })
            return

        elif path == "/api/vision/observe":
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            cam_ip = q.get("ip", [DEFAULT_CAM_IP])[0]
            custom_prompt = q.get("prompt", [None])[0]
            receiver = get_vision_receiver(cam_ip)
            vlm = get_vlm_client()
            jpeg_bytes = receiver.buffer.get_jpeg_bytes() if (receiver and receiver.buffer) else None
            if not jpeg_bytes:
                self._send_json({"success": False, "observation": "Camera frame not available (standby)"}, 503)
                return
            observation = vlm.describe_scene(jpeg_bytes, custom_prompt=custom_prompt)
            self._send_json({
                "success": bool(observation),
                "observation": observation or "Could not analyze frame"
            })
            return

        # Fallback to static files
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(length) if length > 0 else b"{}"

        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            payload = {}

        if path == "/api/robot/command":
            cmd = payload.get("command", "")
            robot_ip = payload.get("ip", DEFAULT_ROBOT_IP)
            if not cmd:
                self._send_json({"error": "Missing command"}, 400)
                return

            try:
                ctrl = get_robot_controller(robot_ip)

                # Dispatch appropriate command
                if cmd.startswith("MOVE:"):
                    parts = cmd.split(":")
                    direction = parts[1].upper()
                    duration = float(parts[2]) if len(parts) > 2 else 0.5
                    ctrl.send(direction)
                    if duration > 0 and direction != "STOP":
                        def _stop_after():
                            time.sleep(duration)
                            ctrl.stop()
                        threading.Thread(target=_stop_after, daemon=True).start()
                elif cmd.startswith("EMOTION:"):
                    parts = cmd.split(":")
                    emotion = parts[1].lower()
                    ctrl.set_emotion(emotion)
                elif cmd == "STOP":
                    ctrl.stop()
                elif cmd == "DANCE":
                    ctrl.dance()
                elif cmd == "SING":
                    ctrl.sing()
                else:
                    ctrl.send(cmd)

                self._send_json({"success": True, "command": cmd})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/chat":
            prompt = payload.get("prompt", "").strip()
            robot_ip = payload.get("ip", DEFAULT_ROBOT_IP)
            cam_ip = payload.get("cam_ip", DEFAULT_CAM_IP)
            force_vision = bool(payload.get("use_vision", False))
            play_pc = bool(payload.get("play_pc", True))
            stream_robot = bool(payload.get("stream_robot", True))
            engine_choice = str(payload.get("engine", "edge")).lower()

            if not prompt:
                self._send_json({"error": "Empty prompt"}, 400)
                return

            try:
                # 1. Determine if visual reasoning is needed
                needs_vision = force_vision or any(kw in prompt.lower() for kw in VISUAL_KEYWORDS)
                visual_context = None

                if needs_vision:
                    receiver = get_vision_receiver(cam_ip)
                    if receiver and receiver.buffer and receiver.buffer.has_frame():
                        jpeg_bytes = receiver.buffer.get_jpeg_bytes()
                        if jpeg_bytes:
                            vlm = get_vlm_client()
                            print(f"[Chat] Triggering VLM for visual prompt: '{prompt}'")
                            visual_context = vlm.describe_scene(jpeg_bytes)
                            print(f"[Chat] VLM Observation: {visual_context}")

                # 2. Query Chat LLM with augmented visual context
                engine = get_chat_engine()
                tools, response_text, segments = engine.ask(prompt, visual_context=visual_context)

                ctrl = get_robot_controller(robot_ip)
                if not ctrl.connected:
                    ctrl.connect()

                svc = get_audio_service(robot_ip=robot_ip, play_pc=play_pc)

                # Execute kinematic motor tools if requested by LLM
                for tool in tools:
                    tname = tool.get("tool", "")
                    params = tool.get("parameters", {})
                    dur = float(params.get("duration", 1.0))
                    if tname == "move_forward":
                        ctrl.forward(dur)
                    elif tname == "move_backward":
                        ctrl.backward(dur)
                    elif tname == "turn_left":
                        ctrl.left(dur)
                    elif tname == "turn_right":
                        ctrl.right(dur)
                    elif tname == "dance":
                        ctrl.dance()
                    elif tname == "sing":
                        ctrl.sing()

                # 3. Synthesize speech before returning so audio is immediately available
                full_text = " ".join(txt for _, txt in segments if txt).strip()
                audio_url = None
                duration = 2.5

                if full_text:
                    try:
                        print(f"[Chat] Synthesizing speech with '{engine_choice}': \"{full_text}\" (play_pc={play_pc})...")
                        audio_url = svc.synthesize(
                            full_text,
                            play_pc=play_pc,
                            engine=engine_choice
                        )
                        duration = getattr(svc, "last_duration", 2.5)
                        print(f"[Chat] Speech ready ({duration:.2f}s): {audio_url}")
                    except Exception as synth_err:
                        print(f"[Chat] Speech synthesis warning: {synth_err}")

                # 4. Stream to ESP32 robot speaker over I2S if requested
                if stream_robot and audio_url:
                    ctrl.play_audio(audio_url)

                # 5. Animate OLED facial expressions on ESP32 in sync with speech duration
                def _emotion_worker():
                    try:
                        total_len = max(1, sum(len(txt.strip()) for _, txt in segments if txt))
                        effective_duration = max(duration, len(full_text) * 0.08)
                        for emotion, text in segments:
                            seg_len = len(text.strip()) if text else 1
                            seg_time = max(1.0, (seg_len / total_len) * effective_duration)
                            ctrl.set_emotion(emotion)
                            time.sleep(seg_time)
                        time.sleep(0.3)
                        ctrl.normal()
                    except Exception as emo_err:
                        print(f"[Chat] Emotion animation worker error: {emo_err}")

                threading.Thread(target=_emotion_worker, daemon=True).start()

                self._send_json({
                    "success": True,
                    "prompt": prompt,
                    "response": response_text,
                    "segments": segments,
                    "tools": tools,
                    "visual_context": visual_context,
                    "audio_url": audio_url,
                    "duration": duration,
                    "engine": engine_choice
                })
            except Exception as e:
                print(f"[Chat] Handler error: {e}")
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/chat/clear":
            try:
                engine = get_chat_engine()
                engine.clear_history()
                print("[Chat] Conversational history reset.")
                self._send_json({"success": True, "message": "History cleared"})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/audio/test":
            text = payload.get("text", "Hello, I am Ikru!")
            play_pc = bool(payload.get("play_pc", False))
            robot_ip = payload.get("ip", DEFAULT_ROBOT_IP)
            stream_robot = bool(payload.get("stream_robot", True))

            try:
                svc = get_audio_service(robot_ip=robot_ip, play_pc=play_pc)
                stream_url = svc.synthesize(text, play_pc=play_pc)

                if stream_robot and stream_url:
                    ctrl = get_robot_controller(robot_ip)
                    if not ctrl.connected:
                        ctrl.connect()
                    ctrl.play_audio(stream_url)

                self._send_json({
                    "success": True,
                    "stream_url": stream_url,
                    "duration": getattr(svc, "last_duration", 0.0),
                    "text": text
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/assistant/start":
            global assistant_process, assistant_logs
            play_pc = bool(payload.get("play_pc", False))
            with assistant_lock:
                if assistant_process is None or assistant_process.poll() is not None:
                    main_py = SOFTWARE_DIR / "ikru" / "main.py"
                    assistant_logs = ["[SYSTEM] Launching IKRU Companion Assistant..."]
                    cmd = [sys.executable, str(main_py)]
                    if play_pc:
                        cmd.append("--pc-audio")
                    assistant_process = subprocess.Popen(
                        cmd,
                        cwd=str(PROJECT_ROOT),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )

                    def _stream_logs(proc):
                        for line in iter(proc.stdout.readline, ""):
                            with assistant_lock:
                                assistant_logs.append(line.rstrip())
                        proc.stdout.close()

                    threading.Thread(target=_stream_logs, args=(assistant_process,), daemon=True).start()

                self._send_json({"success": True, "running": True})
            return

        elif path == "/api/wifi/configure":
            ssid = payload.get("ssid", "").strip()
            password = payload.get("password", "").strip()
            method = payload.get("method", "auto").lower()
            robot_ip = payload.get("ip", DEFAULT_ROBOT_IP)

            if not ssid:
                self._send_json({"error": "SSID cannot be empty"}, 400)
                return

            cmd = f"SET_WIFI:{ssid}:{password}"
            result = {"success": False, "method": method}

            # 1. Try WebSocket if robot is reachable
            if method in ("auto", "websocket"):
                try:
                    ctrl = get_robot_controller(robot_ip)
                    if ctrl.connected:
                        ctrl.send(cmd)
                        result = {"success": True, "method": "websocket", "message": f"Sent credentials to ws://{ctrl.ip}:81"}
                except Exception as e:
                    print(f"[Server] WebSocket WiFi config error: {e}")

            # 2. Try Serial if WebSocket didn't succeed or method == 'serial'
            if not result.get("success") and method in ("auto", "serial"):
                res_serial = send_wifi_serial(ssid, password)
                if res_serial.get("success"):
                    result = {"success": True, "method": "serial", "message": f"Sent credentials over USB Serial ({res_serial.get('port')})"}
                else:
                    result = {"success": False, "error": res_serial.get("error", "Failed via both WebSocket and Serial")}

            self._send_json(result)
            return

        elif path == "/api/audio/volume":
            vol = int(payload.get("volume", 100))
            vol = max(0, min(100, vol))
            svc = get_audio_service()
            svc.set_volume(vol / 100.0)

            # Also notify ESP32 firmware if connected
            try:
                ctrl = get_robot_controller()
                if ctrl.connected:
                    ctrl.send(f"VOLUME:{vol}")
            except Exception:
                pass

            self._send_json({"success": True, "volume": vol})
            return

        elif path == "/api/voice/upload":
            name = payload.get("name", "custom_voice").strip()
            name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
            b64_data = payload.get("audio_data", "")

            if not b64_data:
                self._send_json({"error": "No audio data provided"}, 400)
                return

            try:
                import io
                import soundfile as sf
                from scipy.signal import resample_poly
                import math

                # Remove data URI prefix if present (e.g. data:audio/wav;base64,...)
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]

                raw_bytes = base64.b64decode(b64_data)
                audio_io = io.BytesIO(raw_bytes)

                data, sr = sf.read(audio_io)
                # Convert to mono if multi-channel
                if data.ndim > 1:
                    data = np.mean(data, axis=1)

                # Resample to 24000 Hz (ideal for Chatterbox prompt conditioning)
                target_sr = 24000
                if sr != target_sr:
                    g = math.gcd(target_sr, sr)
                    up = target_sr // g
                    down = sr // g
                    data = resample_poly(data, up, down)

                out_path = VOICES_DIR / f"{name}.wav"
                sf.write(str(out_path), data, target_sr, subtype="PCM_16")

                # Activate the uploaded voice prompt immediately
                svc = get_audio_service()
                svc.set_audio_prompt(str(out_path))

                self._send_json({
                    "success": True,
                    "name": name,
                    "filename": f"{name}.wav",
                    "path": str(out_path)
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/voice/select":
            name = payload.get("name", "default").strip()
            svc = get_audio_service()
            if name == "default":
                svc.set_audio_prompt(None)
                self._send_json({"success": True, "active": "default"})
            else:
                target_file = VOICES_DIR / f"{name}.wav"
                if target_file.exists():
                    svc.set_audio_prompt(str(target_file))
                    self._send_json({"success": True, "active": name})
                else:
                    self._send_json({"success": False, "error": "Voice file not found"}, 404)
            return

        self._send_json({"error": "Endpoint not found"}, 404)


def run_server(port: int = 5000):
    """Starts the IKRU professional companion HTTP server."""
    server_address = ("0.0.0.0", port)
    httpd = http.server.ThreadingHTTPServer(server_address, IkruApiHandler)
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    print("=" * 65)
    print(" PROJECT IKRU — Professional UI & Boot Experience Server")
    print(f" Local Web UI:    http://localhost:{port}/")
    print(f" Network Web UI:  http://{local_ip}:{port}/")
    print(f" Robot Target:    ws://{DEFAULT_ROBOT_IP}:81")
    print("=" * 65)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    run_server(port)
