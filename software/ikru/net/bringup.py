"""
Structured IKRU bring-up. The PC walks through the connection stages in order and
waits at each one (instead of failing) until it's done:

  1. PC network  built-in Wi-Fi has internet; the external adapter is free for IKRU-CAM
  2. Power on    wait for the IKRU-CAM network to appear (head unit booted)
  3. Join hub    external adapter joins IKRU-CAM; internet keeps routing via home Wi-Fi
  4. Body link   robot body found on the hub and linked over WebSocket

From stage 3 on, the PC announces itself to the body on UDP 4211 so the body's
OLED can show that the PC has arrived. Ctrl+C during a wait skips that stage.
"""
import itertools
import socket
import sys
import threading
import time

from . import netinfo

PC_ANNOUNCE_PORT = 4211
PC_ANNOUNCE_PREFIX = "IKRU-PC|"
STAGES = 4


class _Console:
    """Prints one '[n/4] Title ..... status' line per stage, with an in-place spinner while waiting."""

    SPINNER = "|/-\\"

    def __init__(self):
        self._spin = itertools.cycle(self.SPINNER)
        self._label = ""
        self._waiting = False

    def begin(self, n, title):
        self._label = f"  [{n}/{STAGES}] {title} ".ljust(26, ".") + " "

    def wait(self, msg):
        self._waiting = True
        sys.stdout.write(f"\r{self._label}{next(self._spin)} {msg}".ljust(100)[:100])
        sys.stdout.flush()

    def _end(self, mark, msg):
        prefix = "\r" if self._waiting else ""
        self._waiting = False
        print(f"{prefix}{self._label}{mark} {msg}".ljust(100))

    def done(self, msg):
        self._end("OK", msg)

    def warn(self, msg):
        self._end("!!", msg)

    def note(self, msg):
        """Extra indented detail under the current stage."""
        if self._waiting:
            print()
            self._waiting = False
        print(f"         {msg}")


class PcAnnouncer(threading.Thread):
    """Tells the robot body 'the PC is on the hub' once a second (UDP 4211)."""

    def __init__(self, pc_ip, targets=(netinfo.HUB_ROBOT_IP, "192.168.4.255"), port=PC_ANNOUNCE_PORT):
        super().__init__(daemon=True, name="ikru-pc-announce")
        self.pc_ip = pc_ip
        self.targets = targets
        self.port = port
        self._stop_event = threading.Event()

    def run(self):
        payload = f"{PC_ANNOUNCE_PREFIX}{self.pc_ip}".encode()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((self.pc_ip, 0))  # leave through the hub adapter, not home Wi-Fi
        except OSError:
            return
        with sock:
            while not self._stop_event.is_set():
                for target in self.targets:
                    try:
                        sock.sendto(payload, (target, self.port))
                    except OSError:
                        pass
                self._stop_event.wait(1.0)

    def stop(self):
        self._stop_event.set()


def pick_adapters(interfaces, internet_pref=None, hub_pref=None):
    """
    Decides which Wi-Fi adapter carries internet and which joins IKRU-CAM.
    Returns (internet_name, hub_name); they're the same name with a single adapter.
    """
    names = [i["name"] for i in interfaces]
    if not names:
        return None, None
    if len(names) == 1:
        return names[0], names[0]

    by_name = {i["name"]: i for i in interfaces}
    hub = hub_pref if hub_pref in by_name else None
    internet = internet_pref if internet_pref in by_name and internet_pref != hub else None

    if hub is None:
        on_hub = [n for n in names if by_name[n]["ssid"] == netinfo.HUB_SSID and n != internet]
        hub = on_hub[0] if on_hub else None
    if internet is None:
        online = [n for n in names if n != hub and by_name[n]["state"] == "connected"]
        internet = online[0] if online else next(n for n in names if n != hub)
    if hub is None:
        hub = next(n for n in names if n != internet)
    return internet, hub


class Bringup:
    def __init__(self, config, save_local=None, interactive=True):
        cfg = config.get("bringup", {})
        self.power_on_timeout = float(cfg.get("power_on_timeout_s", 180))
        self.join_timeout = float(cfg.get("join_timeout_s", 25))
        self.body_timeout = float(cfg.get("body_timeout_s", 60))
        self.internet_pref = config.get("internet_adapter")
        self.hub_pref = config.get("hub_adapter")
        self.save_local = save_local
        self.interactive = interactive

        self.console = _Console()
        self.internet_if = None
        self.hub_if = None
        self.single_adapter = False
        self.internet_ok = False
        self.hub_ip = None
        self.announcer = None

    # ------------------------------------------------------------------
    def run_network(self):
        """Stages 1-3. Returns True when the PC holds an IKRU-CAM address."""
        print("\n" + "=" * 50)
        print("  IKRU BRING-UP")
        print("=" * 50)
        self._stage_pc_network()
        if self.hub_if is None:
            return False
        if not self._stage_power_on():
            return False
        return self._stage_join_hub()

    def link_body(self, robot):
        """Stage 4. Waits for the robot body to appear on the hub and links to it."""
        c = self.console
        c.begin(4, "Body link")
        deadline = time.monotonic() + self.body_timeout
        try:
            while not robot.connected and time.monotonic() < deadline:
                left = int(deadline - time.monotonic())
                c.wait(f"waiting for the robot body to join {netinfo.HUB_SSID} ({left}s)")
                if not robot.connect(silent=True):
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass

        if robot.connected:
            c.done(f"robot {robot.ip} linked")
            robot.setup_status("PC linked")
            return True
        c.warn("robot body not found (skipped)")
        return False

    def finish(self):
        if self.announcer:
            self.announcer.stop()
            self.announcer = None

    # ------------------------------------------------------------------
    def _stage_pc_network(self):
        c = self.console
        c.begin(1, "PC network")
        c.wait("checking Wi-Fi adapters...")
        interfaces = netinfo.wifi_interfaces()
        self.internet_if, self.hub_if = pick_adapters(interfaces, self.internet_pref, self.hub_pref)

        if self.hub_if is None:
            c.warn("no Wi-Fi adapter found")
            return
        self.single_adapter = self.internet_if == self.hub_if
        if not self.single_adapter and self.save_local and (
            self.internet_if != self.internet_pref or self.hub_if != self.hub_pref
        ):
            self.save_local(internet_adapter=self.internet_if, hub_adapter=self.hub_if)

        by_name = {i["name"]: i for i in interfaces}
        home = by_name[self.internet_if]
        home_ssid = home["ssid"] if home["ssid"] != netinfo.HUB_SSID else None
        self.internet_ok = netinfo.has_internet()

        where = f"'{self.internet_if}' on {home_ssid}" if home_ssid else f"'{self.internet_if}'"
        if self.internet_ok:
            c.done(f"internet via {where}")
        else:
            c.warn(f"no internet on {where}")
            c.note("Voice recognition needs internet; the local LLM still works.")

        if self.single_adapter:
            c.note(f"Only one Wi-Fi adapter ('{self.hub_if}'). Plug in the external adapter so the PC")
            c.note("can stay on home Wi-Fi and IKRU-CAM at the same time.")
        else:
            c.note(f"IKRU-CAM adapter: '{self.hub_if}'   (edit hub_adapter in config.local.json to change)")

    def _hub_state(self):
        for i in netinfo.wifi_interfaces():
            if i["name"] == self.hub_if:
                return i
        return {"guid": None, "state": "", "ssid": None}

    def _on_hub(self):
        state = self._hub_state()
        return state["state"] == "connected" and state["ssid"] == netinfo.HUB_SSID

    def _stage_power_on(self):
        c = self.console
        c.begin(2, "Power on IKRU")
        if self._on_hub():
            c.done("IKRU-CAM already up")
            return True

        if self.single_adapter and self._hub_state()["state"] == "connected" and not self._confirm_single_switch():
            c.warn(f"staying on '{self._hub_state()['ssid']}' (robot + vision offline)")
            return False

        deadline = time.monotonic() + self.power_on_timeout
        next_scan = 0.0
        try:
            while time.monotonic() < deadline:
                if self._on_hub() or netinfo.ssid_visible(netinfo.HUB_SSID, self.hub_if):
                    c.done("IKRU-CAM is on the air")
                    return True
                if time.monotonic() >= next_scan:
                    # Windows only rescans about once a minute on its own
                    netinfo.request_scan(self._hub_state().get("guid"))
                    next_scan = time.monotonic() + 4.0
                left = int(deadline - time.monotonic())
                for _ in range(8):
                    c.wait(f"turn IKRU on - waiting for Wi-Fi '{netinfo.HUB_SSID}' ({left}s)")
                    time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        c.warn(f"'{netinfo.HUB_SSID}' never appeared (is the head unit powered?)")
        return False

    def _confirm_single_switch(self):
        if not self.interactive:
            return False
        try:
            answer = input(f"\n         Switch '{self.hub_if}' to {netinfo.HUB_SSID}? The PC loses internet. (y/N): ")
        except (KeyboardInterrupt, EOFError):
            return False
        return answer.strip().lower() == "y"

    def _stage_join_hub(self):
        c = self.console
        c.begin(3, "Join IKRU-CAM")
        deadline = time.monotonic() + self.join_timeout
        next_connect = 0.0
        try:
            while time.monotonic() < deadline:
                if self._on_hub():
                    self.hub_ip = netinfo.hub_ip_of(self.hub_if)
                    if self.hub_ip:
                        break
                    c.wait("joined, waiting for an address from the head...")
                elif time.monotonic() >= next_connect:
                    c.wait(f"connecting '{self.hub_if}' to {netinfo.HUB_SSID}...")
                    netinfo.connect_hub(self.hub_if)
                    next_connect = time.monotonic() + 5.0
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

        if not self.hub_ip:
            c.warn(f"'{self.hub_if}' couldn't join {netinfo.HUB_SSID}")
            return False

        self.announcer = PcAnnouncer(self.hub_ip)
        self.announcer.start()
        c.done(f"'{self.hub_if}' on {netinfo.HUB_SSID} as {self.hub_ip}")

        if self.single_adapter or not self.internet_ok:
            return True
        c.wait("checking internet still routes via home Wi-Fi...")
        if netinfo.has_internet():
            c.done("internet still routes via home Wi-Fi")
            return True
        self._fix_route()
        return True

    def _fix_route(self):
        """IKRU-CAM stole the default route: push its adapter behind home Wi-Fi."""
        c = self.console
        c.warn("internet broke after joining IKRU-CAM")
        if netinfo.adapter_info(self.hub_if)["gateway"] == netinfo.CAM_IP:
            c.note("The head unit is offering itself as a gateway. Re-flash firmware/head/head.ino.")
        cmd = netinfo.fix_hub_route_command(self.hub_if)
        c.note("One-time fix (admin): " + cmd)
        if not self.interactive:
            return
        try:
            answer = input("         Apply it now? A Windows admin prompt will appear. (Y/n): ")
        except (KeyboardInterrupt, EOFError):
            return
        if answer.strip().lower() in ("", "y", "yes"):
            if netinfo.run_elevated(cmd) and netinfo.has_internet():
                c.note("Fixed: internet routes via home Wi-Fi again.")
            else:
                c.note("Still no internet. Run the command above in an admin PowerShell.")
