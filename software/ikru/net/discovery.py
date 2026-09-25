"""
Robot discovery for IKRU.

find_robot() locates the ESP32 body controller in ~3 s by combining:
  1. The UDP beacon the firmware broadcasts every 2 s on port 4210
     ("IKRU-ROBOT|<ip>|<ssid>|<rssi>|ws81").
  2. Parallel TCP probes of port 81 on a short list of hint hosts.
If nothing answers, it returns a Diagnosis explaining why and what to do.
"""
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional

from . import netinfo

BEACON_PORT = 4210
BEACON_PREFIX = "IKRU-ROBOT|"
DEFAULT_HOSTS = [netinfo.HUB_ROBOT_IP, "ikru-robot.local"]


@dataclass
class RobotFound:
    ip: str
    method: str  # "beacon" or "probe"
    ssid: Optional[str] = None
    rssi: Optional[int] = None

    def describe(self):
        extra = ""
        if self.ssid:
            extra = f" (WiFi {self.ssid}" + (f", {self.rssi} dBm)" if self.rssi is not None else ")")
        return f"{self.ip} via {self.method}{extra}"


@dataclass
class Diagnosis:
    reason: str  # wrong_network | hub_missing | isolation | robot_missing | port_blocked
    message: str
    hints: List[str] = field(default_factory=list)


def parse_beacon(data):
    """Parses a beacon payload into RobotFound, or None if it isn't one."""
    try:
        text = data.decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    if not text.startswith(BEACON_PREFIX):
        return None
    parts = text.split("|")
    if len(parts) < 2 or not netinfo.is_ip(parts[1]):
        return None
    rssi = None
    if len(parts) > 3:
        try:
            rssi = int(parts[3])
        except ValueError:
            pass
    return RobotFound(ip=parts[1], method="beacon", ssid=parts[2] if len(parts) > 2 else None, rssi=rssi)


class _BeaconListener(threading.Thread):
    def __init__(self, port=BEACON_PORT):
        super().__init__(daemon=True, name="ikru-beacon")
        self.port = port
        self.result = None
        self._stop_event = threading.Event()

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.port))
            sock.settimeout(0.2)
        except OSError:
            return  # Port busy or blocked — TCP probes still run
        with sock:
            while not self._stop_event.is_set() and self.result is None:
                try:
                    data, _addr = sock.recvfrom(256)
                except (socket.timeout, OSError):
                    continue
                self.result = parse_beacon(data)

    def stop(self):
        self._stop_event.set()


def _probe(host, port, timeout):
    """Returns the resolved IP if ws port answers, else None."""
    try:
        ip = host if netinfo.is_ip(host) else socket.gethostbyname(host)
    except Exception:
        return None
    return ip if netinfo.check_tcp_port(ip, port, timeout) else None


def _dedupe(hosts):
    out = []
    for host in hosts:
        host = (host or "").strip()
        if host and host not in out:
            out.append(host)
    return out


def find_robot(hint_hosts=None, port=81, timeout=3.0, probe_timeout=0.8, beacon_port=BEACON_PORT):
    """Locates the robot. Returns RobotFound, or Diagnosis if it can't be reached."""
    hosts = _dedupe(list(hint_hosts or []) + DEFAULT_HOSTS)
    deadline = time.monotonic() + timeout

    beacon = _BeaconListener(beacon_port)
    beacon.start()
    pool = ThreadPoolExecutor(max_workers=max(1, len(hosts)), thread_name_prefix="ikru-probe")
    pending = [pool.submit(_probe, host, port, probe_timeout) for host in hosts]
    beacon_ip = None

    try:
        while time.monotonic() < deadline:
            if beacon.result and beacon_ip is None:
                beacon_ip = beacon.result.ip
                if netinfo.check_tcp_port(beacon_ip, port, probe_timeout):
                    return beacon.result

            # Results in hint priority order, so a configured IP beats a stale one
            while pending and pending[0].done():
                ip = pending.pop(0).result()
                if ip:
                    return RobotFound(ip=ip, method="probe")
            time.sleep(0.05)
    finally:
        beacon.stop()
        pool.shutdown(wait=False, cancel_futures=True)

    # A later probe may have succeeded while an earlier one was still pending
    for fut in pending:
        if fut.done() and fut.result():
            return RobotFound(ip=fut.result(), method="probe")

    return diagnose(hosts, beacon_ip=beacon_ip)


def diagnose(hosts, beacon_ip=None):
    """Explains why the robot couldn't be reached, based on the PC's network state."""
    ssid = netinfo.pc_ssid()
    ips = netinfo.pc_ipv4s()
    where = f"'{ssid}'" if ssid else "no Wi-Fi"
    join_hint = f"Connect this PC to Wi-Fi '{netinfo.HUB_SSID}' (password: {netinfo.HUB_PASSWORD})"

    if beacon_ip:
        return Diagnosis(
            "port_blocked",
            f"The robot is announcing itself at {beacon_ip}, but its control port (81) isn't accepting connections.",
            ["Allow Python through Windows Firewall", "Power-cycle the robot"],
        )

    if not netinfo.on_hub(ssid, ips):
        if netinfo.HUB_SSID not in netinfo.visible_ssids():
            return Diagnosis(
                "hub_missing",
                f"This PC is on {where} and the '{netinfo.HUB_SSID}' network isn't visible.",
                ["Power on the head unit (ESP32-CAM) — it creates the IKRU-CAM network", join_hint],
            )
        same_net = [h for h in hosts if netinfo.is_ip(h) and any(netinfo.same_subnet(h, ip) for ip in ips)]
        if same_net:
            return Diagnosis(
                "isolation",
                f"This PC and {same_net[0]} are both on {where}, but the robot doesn't answer. "
                "Guest and campus networks usually block devices from reaching each other.",
                [join_hint],
            )
        return Diagnosis(
            "wrong_network",
            f"This PC is on {where} ({', '.join(ips) or 'no IP'}), not the robot's network.",
            [join_hint],
        )

    return Diagnosis(
        "robot_missing",
        f"This PC is on the {netinfo.HUB_SSID} hub, but the robot isn't answering at {netinfo.HUB_ROBOT_IP}.",
        [
            "Check the robot is powered on — its OLED should show 'Waiting for PC' and 192.168.4.200",
            "Ensure the head unit (IKRU-CAM) is powered on, then reset the robot body controller",
            "Plug the robot in over USB and pick [u] to read its IP over serial",
        ],
    )
