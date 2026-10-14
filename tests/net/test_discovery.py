"""
Unit tests for robot discovery (software/ikru/net/discovery.py).
Runs entirely on localhost — no robot needed:  python -m pytest tests/net
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "software"))

from ikru.net import Diagnosis, RobotFound, discovery, netinfo


def _free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeWsPort:
    """TCP listener standing in for the robot's WebSocket port."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]

    def close(self):
        self.sock.close()


def _no_default_hosts(monkeypatch):
    monkeypatch.setattr(discovery, "DEFAULT_HOSTS", [])


def test_parse_beacon():
    found = discovery.parse_beacon(b"IKRU-ROBOT|192.168.4.200|IKRU-CAM|-52|ws81")
    assert found == RobotFound(ip="192.168.4.200", method="beacon", ssid="IKRU-CAM", rssi=-52)
    assert discovery.parse_beacon(b"hello") is None
    assert discovery.parse_beacon(b"IKRU-ROBOT|not-an-ip") is None


def test_found_by_probe(monkeypatch):
    _no_default_hosts(monkeypatch)
    ws = FakeWsPort()
    try:
        result = discovery.find_robot(["127.0.0.1"], port=ws.port, timeout=2.0, beacon_port=_free_udp_port())
    finally:
        ws.close()
    assert isinstance(result, RobotFound)
    assert (result.ip, result.method) == ("127.0.0.1", "probe")


def test_found_by_beacon(monkeypatch):
    _no_default_hosts(monkeypatch)
    ws = FakeWsPort()
    beacon_port = _free_udp_port()

    def send_beacon():
        time.sleep(0.3)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(5):
                s.sendto(b"IKRU-ROBOT|127.0.0.1|IKRU-CAM|-40|ws81", ("127.0.0.1", beacon_port))
                time.sleep(0.1)

    threading.Thread(target=send_beacon, daemon=True).start()
    try:
        result = discovery.find_robot([], port=ws.port, timeout=2.0, beacon_port=beacon_port)
    finally:
        ws.close()
    assert isinstance(result, RobotFound)
    assert (result.ip, result.method, result.ssid) == ("127.0.0.1", "beacon", "IKRU-CAM")


def _fake_pc(monkeypatch, ssid, ips, visible):
    monkeypatch.setattr(netinfo, "pc_ssid", lambda: ssid)
    monkeypatch.setattr(netinfo, "pc_ipv4s", lambda: ips)
    monkeypatch.setattr(netinfo, "visible_ssids", lambda: visible)


def test_diagnosis_guest_network_isolation(monkeypatch):
    _fake_pc(monkeypatch, "MBCET-GUEST", ["10.30.2.5"], ["MBCET-GUEST", "IKRU-CAM"])
    diag = discovery.diagnose(["10.30.2.23"])
    assert isinstance(diag, Diagnosis) and diag.reason == "isolation"


def test_diagnosis_wrong_network(monkeypatch):
    _fake_pc(monkeypatch, "HomeNet", ["192.168.1.10"], ["HomeNet", "IKRU-CAM"])
    assert discovery.diagnose([netinfo.HUB_ROBOT_IP]).reason == "wrong_network"


def test_diagnosis_hub_missing(monkeypatch):
    _fake_pc(monkeypatch, "HomeNet", ["192.168.1.10"], ["HomeNet"])
    assert discovery.diagnose([netinfo.HUB_ROBOT_IP]).reason == "hub_missing"


def test_diagnosis_robot_missing_on_hub(monkeypatch):
    _fake_pc(monkeypatch, "IKRU-CAM", ["192.168.4.2"], ["IKRU-CAM"])
    assert discovery.diagnose([netinfo.HUB_ROBOT_IP]).reason == "robot_missing"


def test_diagnosis_port_blocked(monkeypatch):
    _fake_pc(monkeypatch, "IKRU-CAM", ["192.168.4.2"], ["IKRU-CAM"])
    assert discovery.diagnose([], beacon_ip="192.168.4.200").reason == "port_blocked"
