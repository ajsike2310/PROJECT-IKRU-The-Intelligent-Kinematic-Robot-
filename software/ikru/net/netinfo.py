"""
PC-side network introspection for IKRU.

Answers "which network is this PC on?" so connection failures can be explained
instead of silently retried. Uses Windows netsh/ipconfig with socket fallbacks.
"""
import ipaddress
import re
import socket
import subprocess

# IKRU-CAM hub topology (see firmware/head/head.ino and firmware/controller/controller.ino)
HUB_SSID = "IKRU-CAM"
HUB_PASSWORD = "ikru@potato"
HUB_SUBNET = ipaddress.ip_network("192.168.4.0/24")
CAM_IP = "192.168.4.1"
HUB_ROBOT_IP = "192.168.4.200"


def _run(cmd, timeout=4):
    try:
        return subprocess.check_output(
            cmd, text=True, timeout=timeout, errors="replace", stderr=subprocess.DEVNULL
        )
    except Exception:
        return ""


def pc_ssid():
    """SSID of the PC's connected Wi-Fi, or None (Ethernet only / not connected)."""
    out = _run(["netsh", "wlan", "show", "interfaces"])
    match = re.search(r"^\s+SSID\s+:\s+(.+)$", out, re.MULTILINE)
    return match.group(1).strip() if match else None


def pc_ipv4s():
    """All usable IPv4 addresses on this PC, across every adapter."""
    found = re.findall(r"IPv4 Address[.\s]*:\s*(\d+\.\d+\.\d+\.\d+)", _run(["ipconfig"]))
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except Exception:
        pass

    ips = []
    for ip in found:
        if ip.startswith(("127.", "169.254.")) or ip in ips:
            continue
        ips.append(ip)
    return ips


def visible_ssids():
    """SSIDs the PC's Wi-Fi adapter can currently see."""
    out = _run(["netsh", "wlan", "show", "networks"])
    ssids = []
    for match in re.finditer(r"^SSID \d+\s*:\s*(.*)$", out, re.MULTILINE):
        ssid = match.group(1).strip()
        if ssid and ssid not in ssids:
            ssids.append(ssid)
    return ssids


def is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def same_subnet(ip_a, ip_b, prefix=24):
    try:
        net = ipaddress.ip_network(f"{ip_a}/{prefix}", strict=False)
        return ipaddress.ip_address(ip_b) in net
    except ValueError:
        return False


def on_hub(ssid=None, ips=None):
    """True if the PC is connected to the IKRU-CAM hub network."""
    if ssid == HUB_SSID:
        return True
    return any(ipaddress.ip_address(ip) in HUB_SUBNET for ip in (ips or []))


def check_tcp_port(host, port, timeout=0.5):
    """Fast TCP reachability probe."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dual-adapter support: built-in Wi-Fi -> home internet, external -> IKRU-CAM
# ---------------------------------------------------------------------------

def parse_wlan_interfaces(out):
    """Parses `netsh wlan show interfaces` into one dict per Wi-Fi adapter."""
    adapters = []
    for line in out.splitlines():
        key, sep, value = line.partition(" : ")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Name":
            adapters.append({"name": value, "guid": None, "state": "", "ssid": None, "signal": None})
        elif adapters and key == "GUID":
            adapters[-1]["guid"] = value
        elif adapters and key == "State":
            adapters[-1]["state"] = value.lower()
        elif adapters and key == "SSID":
            adapters[-1]["ssid"] = value or None
        elif adapters and key == "Signal":
            adapters[-1]["signal"] = value
    return adapters


def wifi_interfaces():
    """Every Wi-Fi adapter on the PC: [{name, guid, state, ssid, signal}]."""
    return parse_wlan_interfaces(_run(["netsh", "wlan", "show", "interfaces"]))


def parse_ipconfig(out):
    """Parses `ipconfig` into {adapter name: {"ips": [...], "gateway": str|None}}."""
    adapters = {}
    current = None
    for line in out.splitlines():
        header = re.match(r"^\S.*adapter (.+):\s*$", line)
        if header:
            current = adapters.setdefault(header.group(1).strip(), {"ips": [], "gateway": None})
            continue
        if current is None:
            continue
        ip = re.search(r"IPv4 Address[.\s]*:\s*(\d+\.\d+\.\d+\.\d+)", line)
        if ip:
            current["ips"].append(ip.group(1))
        gw = re.search(r"Default Gateway[.\s]*:\s*(\d+\.\d+\.\d+\.\d+)", line)
        if gw:
            current["gateway"] = gw.group(1)
    return adapters


def adapter_info(name):
    """{"ips": [...], "gateway": ...} for one adapter, as shown by ipconfig."""
    return parse_ipconfig(_run(["ipconfig"])).get(name, {"ips": [], "gateway": None})


def hub_ip_of(name):
    """The adapter's 192.168.4.x address, or None if it has no hub lease yet."""
    for ip in adapter_info(name)["ips"]:
        if ipaddress.ip_address(ip) in HUB_SUBNET:
            return ip
    return None


def ssid_visible(ssid, interface=None):
    """True if the (given) adapter can currently see the SSID."""
    cmd = "netsh wlan show networks mode=bssid"
    if interface:
        cmd += f' interface="{interface}"'
    return any(re.match(rf"^SSID \d+\s*:\s*{re.escape(ssid)}\s*$", line.strip())
               for line in _run(cmd).splitlines())


def request_scan(guid):
    """Asks Windows to rescan Wi-Fi on one adapter now (WlanScan); results land in ~3 s.
    Doesn't disturb the adapter's current connection. Best-effort: False on failure."""
    try:
        import ctypes
        import uuid
        from ctypes import wintypes
        wlan = ctypes.windll.wlanapi
        handle = wintypes.HANDLE()
        version = wintypes.DWORD()
        if wlan.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle)) != 0:
            return False
        try:
            guid_struct = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
            return wlan.WlanScan(handle, ctypes.byref(guid_struct), None, None, None) == 0
        finally:
            wlan.WlanCloseHandle(handle, None)
    except Exception:
        return False


_PROFILE_XML = """<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{ssid}</name>
  <SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>auto</connectionMode>
  <MSM><security>
    <authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption>
    <sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey>
  </security></MSM>
</WLANProfile>
"""


def ensure_hub_profile(interface):
    """Installs an auto-connect IKRU-CAM profile on the hub adapter (current user, no admin),
    ranked first so the adapter rejoins IKRU-CAM rather than another saved network."""
    import os
    import tempfile
    listed = _run(f'netsh wlan show profiles interface="{interface}"')
    if not re.search(rf":\s*{re.escape(HUB_SSID)}\s*$", listed, re.MULTILINE):
        fd, path = tempfile.mkstemp(suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_PROFILE_XML.format(ssid=HUB_SSID, password=HUB_PASSWORD))
            _run(f'netsh wlan add profile filename="{path}" interface="{interface}" user=current')
        finally:
            os.remove(path)
    _run(f'netsh wlan set profileorder name="{HUB_SSID}" interface="{interface}" priority=1')


def connect_hub(interface):
    """Asks Windows to join IKRU-CAM on the given adapter. Returns immediately."""
    ensure_hub_profile(interface)
    _run(f'netsh wlan connect name="{HUB_SSID}" ssid="{HUB_SSID}" interface="{interface}"')


def has_internet(timeout=2.0):
    """True if the PC can reach the public internet over its default route."""
    return any(check_tcp_port(host, 443, timeout) for host in ("1.1.1.1", "8.8.8.8"))


def fix_hub_route_command(interface):
    """PowerShell command that stops Windows routing internet traffic through IKRU-CAM."""
    return f"Set-NetIPInterface -InterfaceAlias '{interface}' -InterfaceMetric 9000"


def run_elevated(ps_command):
    """Runs a PowerShell command as administrator (shows a UAC prompt). Returns True if launched."""
    import base64
    encoded = base64.b64encode(ps_command.encode("utf-16-le")).decode("ascii")
    launcher = (
        "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-EncodedCommand','{encoded}'"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", launcher], timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False
