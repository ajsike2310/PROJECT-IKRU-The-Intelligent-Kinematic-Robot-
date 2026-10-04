"""
PROJECT IKRU — Deterministic Connection State Machine
=====================================================
Manages subsystem discovery, state transitions, fault isolation, and health monitoring
for Robot Body (WebSocket:81), ESP32-CAM (UDP:2222/2223), and Ollama LLM (HTTP:11434).
"""

import enum
import logging
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ikru import config

logger = logging.getLogger("IKRU.Connection")


class ConnectionState(enum.Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    VERIFYING = "VERIFYING"
    READY = "READY"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


@dataclass
class SubsystemHealth:
    name: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    target_ip: str = ""
    port: int = 0
    latency_ms: float = 0.0
    last_check: float = 0.0
    retry_count: int = 0
    error_message: str = ""


def probe_tcp_port(ip: str, port: int, timeout: float = config.PROBE_TIMEOUT_S) -> tuple[bool, float]:
    """Fast non-blocking TCP port probe returning (is_open, latency_ms)."""
    if not ip or ip == "unknown":
        return False, 0.0
    t0 = time.perf_counter()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((ip, int(port)))
        s.close()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return res == 0, elapsed_ms
    except Exception:
        return False, 0.0


def scan_local_wifi_interfaces() -> dict:
    """Discovers local server IP, Wi-Fi SSID, and signal strength via netsh."""
    info = {
        "server_ip": "127.0.0.1",
        "wifi_ssid": "unknown",
        "wifi_signal": "--",
        "wifi_connected": False,
        "gateway": "unknown",
    }
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info["server_ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            text=True, timeout=3, errors="replace"
        )
        ssid_match = re.search(r"^\s+SSID\s+:\s+(.+)$", out, re.MULTILINE)
        sig_match = re.search(r"^\s+Signal\s+:\s+(\d+)%", out, re.MULTILINE)
        state_match = re.search(r"^\s+State\s+:\s+(\S+)", out, re.MULTILINE)
        if ssid_match:
            info["wifi_ssid"] = ssid_match.group(1).strip()
        if sig_match:
            info["wifi_signal"] = sig_match.group(1).strip() + "%"
        if state_match:
            info["wifi_connected"] = state_match.group(1).lower() == "connected"
    except Exception:
        pass

    return info


class ConnectionManager:
    """
    Centralized Deterministic Connection State Machine.
    Coordinates initialization order and subsystem fault isolation.
    """

    def __init__(self, robot_ip: str = config.DEFAULT_ROBOT_IP, cam_ip: str = config.DEFAULT_CAM_IP):
        self._lock = threading.Lock()
        self.robot_ip = robot_ip
        self.cam_ip = cam_ip

        self.subsystems: Dict[str, SubsystemHealth] = {
            "robot_body": SubsystemHealth(
                name="robot_body",
                state=ConnectionState.DISCONNECTED,
                target_ip=robot_ip,
                port=config.ROBOT_WS_PORT,
            ),
            "esp32_cam": SubsystemHealth(
                name="esp32_cam",
                state=ConnectionState.DISCONNECTED,
                target_ip=cam_ip,
                port=config.CAM_VIDEO_PORT,
            ),
            "ollama_llm": SubsystemHealth(
                name="ollama_llm",
                state=ConnectionState.DISCONNECTED,
                target_ip="127.0.0.1",
                port=11434,
            ),
        }

        self._callbacks: List[Callable[[str, ConnectionState], None]] = []
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None

    def register_state_callback(self, callback: Callable[[str, ConnectionState], None]):
        """Registers listener for state change events."""
        with self._lock:
            self._callbacks.append(callback)

    def _set_state(self, name: str, new_state: ConnectionState, error_msg: str = "", latency_ms: float = 0.0):
        sub = self.subsystems.get(name)
        if not sub:
            return
        with self._lock:
            old_state = sub.state
            sub.state = new_state
            sub.last_check = time.time()
            sub.error_message = error_msg
            if latency_ms > 0:
                sub.latency_ms = latency_ms

        if old_state != new_state:
            print(f"[ConnectionManager] Subsystem '{name}': {old_state.value} -> {new_state.value} ({error_msg or 'OK'})")
            for cb in self._callbacks:
                try:
                    cb(name, new_state)
                except Exception as e:
                    print(f"[ConnectionManager] Callback error: {e}")

    def probe_robot(self, override_ip: Optional[str] = None) -> bool:
        """Executes verification sequence for ESP32 Robot Body."""
        ip = override_ip or self.robot_ip
        self._set_state("robot_body", ConnectionState.CONNECTING)
        is_open, lat = probe_tcp_port(ip, config.ROBOT_WS_PORT)

        if is_open:
            self.robot_ip = ip
            self.subsystems["robot_body"].target_ip = ip
            self._set_state("robot_body", ConnectionState.READY, latency_ms=lat)
            return True
        else:
            # Candidate scan fallback
            for cand in config.CANDIDATE_ROBOT_IPS:
                if cand == ip:
                    continue
                c_open, c_lat = probe_tcp_port(cand, config.ROBOT_WS_PORT, timeout=0.2)
                if c_open:
                    self.robot_ip = cand
                    self.subsystems["robot_body"].target_ip = cand
                    self._set_state("robot_body", ConnectionState.READY, latency_ms=c_lat)
                    return True

            self._set_state(
                "robot_body",
                ConnectionState.DEGRADED,
                error_msg=f"Robot WebSocket port {config.ROBOT_WS_PORT} unreachable on {ip}. Operating in local audio mode.",
            )
            return False

    def probe_camera(self, override_ip: Optional[str] = None) -> bool:
        """Executes verification sequence for ESP32-CAM."""
        ip = override_ip or self.cam_ip
        self._set_state("esp32_cam", ConnectionState.CONNECTING)
        # Probe video or web fallback port
        is_open, lat = probe_tcp_port(ip, 80)
        if not is_open:
            is_open, lat = probe_tcp_port(ip, 81)

        if is_open:
            self.cam_ip = ip
            self.subsystems["esp32_cam"].target_ip = ip
            self._set_state("esp32_cam", ConnectionState.READY, latency_ms=lat)
            return True
        else:
            self._set_state("esp32_cam", ConnectionState.DEGRADED, error_msg="Camera endpoint offline (Standby mode active)")
            return False

    def probe_ollama(self) -> bool:
        """Verifies local Ollama LLM server reachability."""
        is_open, lat = probe_tcp_port("127.0.0.1", 11434)
        if is_open:
            self._set_state("ollama_llm", ConnectionState.READY, latency_ms=lat)
            return True
        else:
            self._set_state("ollama_llm", ConnectionState.FAILED, error_msg="Ollama HTTP server (127.0.0.1:11434) not responding")
            return False

    def probe_all(self) -> dict:
        """Runs complete deterministic initialization probe sequence across all subsystems."""
        self.probe_ollama()
        self.probe_robot()
        self.probe_camera()
        return self.get_summary()

    def get_summary(self) -> dict:
        """Returns structured JSON-serializable health snapshot."""
        net = scan_local_wifi_interfaces()
        with self._lock:
            subs = {
                k: {
                    "state": v.state.value,
                    "target_ip": v.target_ip,
                    "port": v.port,
                    "latency_ms": round(v.latency_ms, 1),
                    "error": v.error_message,
                }
                for k, v in self.subsystems.items()
            }
        return {
            "server_ip": net["server_ip"],
            "wifi_ssid": net["wifi_ssid"],
            "wifi_signal": net["wifi_signal"],
            "wifi_connected": net["wifi_connected"],
            "robot": subs["robot_body"],
            "camera": subs["esp32_cam"],
            "llm": subs["ollama_llm"],
            "timestamp": time.time(),
        }

    def start_background_monitoring(self, interval_s: float = 10.0):
        """Starts background periodic health verification loop."""
        if self._monitoring:
            return
        self._monitoring = True

        def _loop():
            while self._monitoring:
                time.sleep(interval_s)
                if not self._monitoring:
                    break
                try:
                    self.probe_all()
                except Exception as e:
                    print(f"[ConnectionManager] Background monitor error: {e}")

        self._monitor_thread = threading.Thread(target=_loop, daemon=True)
        self._monitor_thread.start()

    def stop_background_monitoring(self):
        self._monitoring = False


# Global singleton instance
connection_manager = ConnectionManager()
