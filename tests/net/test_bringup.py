"""
Unit tests for the structured bring-up (software/ikru/net/bringup.py) and the
dual-adapter helpers in netinfo. No robot or second adapter needed:
    python -m pytest tests/net
"""
import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "software"))

from ikru.net import bringup, netinfo

NETSH_TWO_ADAPTERS = """
There are 2 interfaces on the system:

    Name                   : Wi-Fi
    Description            : MediaTek Wi-Fi 6 MT7921 Wireless LAN Card
    GUID                   : 34333d81-5e9a-44c0-9b48-9f0ce3a81107
    State                  : connected
    SSID                   : HomeNet
    AP BSSID               : 94:f3:92:b2:9c:33
    Signal                 : 57%

    Name                   : Wi-Fi 2
    Description            : Realtek RTL8811CU Wireless LAN 802.11ac USB NIC
    State                  : disconnected
"""

IPCONFIG = """
Windows IP Configuration

Wireless LAN adapter Wi-Fi:

   IPv4 Address. . . . . . . . . . . : 192.168.1.32
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.1.1

Wireless LAN adapter Wi-Fi 2:

   IPv4 Address. . . . . . . . . . . : 192.168.4.2(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . :
"""


def _iface(name, state="disconnected", ssid=None):
    return {"name": name, "state": state, "ssid": ssid, "signal": None}


def test_parse_wlan_interfaces():
    adapters = netinfo.parse_wlan_interfaces(NETSH_TWO_ADAPTERS)
    assert [a["name"] for a in adapters] == ["Wi-Fi", "Wi-Fi 2"]
    assert adapters[0]["state"] == "connected" and adapters[0]["ssid"] == "HomeNet"
    assert adapters[0]["guid"] == "34333d81-5e9a-44c0-9b48-9f0ce3a81107"
    assert adapters[1]["state"] == "disconnected" and adapters[1]["ssid"] is None


def test_parse_ipconfig_per_adapter():
    adapters = netinfo.parse_ipconfig(IPCONFIG)
    assert adapters["Wi-Fi"] == {"ips": ["192.168.1.32"], "gateway": "192.168.1.1"}
    assert adapters["Wi-Fi 2"] == {"ips": ["192.168.4.2"], "gateway": None}


def test_pick_adapters_home_connected_external_free():
    interfaces = [_iface("Wi-Fi", "connected", "HomeNet"), _iface("Wi-Fi 2")]
    assert bringup.pick_adapters(interfaces) == ("Wi-Fi", "Wi-Fi 2")


def test_pick_adapters_external_already_on_hub():
    interfaces = [_iface("Wi-Fi", "connected", "HomeNet"), _iface("Wi-Fi 2", "connected", "IKRU-CAM")]
    assert bringup.pick_adapters(interfaces) == ("Wi-Fi", "Wi-Fi 2")


def test_pick_adapters_builtin_on_hub_swaps_roles():
    # Built-in joined IKRU-CAM by mistake while the external has internet
    interfaces = [_iface("Wi-Fi", "connected", "IKRU-CAM"), _iface("Wi-Fi 2", "connected", "HomeNet")]
    assert bringup.pick_adapters(interfaces) == ("Wi-Fi 2", "Wi-Fi")


def test_pick_adapters_saved_preferences_win():
    interfaces = [_iface("Wi-Fi", "connected", "HomeNet"), _iface("Wi-Fi 2")]
    assert bringup.pick_adapters(interfaces, "Wi-Fi 2", "Wi-Fi") == ("Wi-Fi 2", "Wi-Fi")


def test_pick_adapters_stale_preference_ignored():
    interfaces = [_iface("Wi-Fi", "connected", "HomeNet"), _iface("Wi-Fi 2")]
    assert bringup.pick_adapters(interfaces, "Wi-Fi 3", "Wi-Fi 4") == ("Wi-Fi", "Wi-Fi 2")


def test_pick_adapters_single_and_none():
    assert bringup.pick_adapters([_iface("Wi-Fi", "connected", "HomeNet")]) == ("Wi-Fi", "Wi-Fi")
    assert bringup.pick_adapters([]) == (None, None)


def test_pc_announcer_reaches_body():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as body:
        body.bind(("127.0.0.1", 0))
        body.settimeout(2.0)
        announcer = bringup.PcAnnouncer("127.0.0.1", targets=("127.0.0.1",), port=body.getsockname()[1])
        announcer.start()
        try:
            data, _ = body.recvfrom(64)
        finally:
            announcer.stop()
    assert data == b"IKRU-PC|127.0.0.1"
