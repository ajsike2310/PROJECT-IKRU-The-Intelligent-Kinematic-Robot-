"""
USB serial fallback for IKRU: read the robot's IP or push Wi-Fi credentials
when it can't be reached over the network.
"""
import re
import time

GET_IP_PATTERN = re.compile(r"IP:(\S+) SSID:(.*?) MODE:(\w+)")


def _open(port):
    import serial
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = 115200
    ser.timeout = 0.2
    # Keep DTR/RTS low so opening the port doesn't reset the ESP32
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def list_ports():
    try:
        import serial.tools.list_ports
    except ImportError:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]


def query_ip(wait_s=3.0):
    """Sends GET_IP on each COM port. Returns (port, ip, ssid, mode) or None."""
    for port in list_ports():
        try:
            with _open(port) as ser:
                ser.reset_input_buffer()
                ser.write(b"GET_IP\n")
                deadline = time.monotonic() + wait_s
                while time.monotonic() < deadline:
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    match = GET_IP_PATTERN.search(line)
                    if match:
                        return port, match.group(1), match.group(2).strip(), match.group(3)
        except Exception:
            continue
    return None


def send_wifi(ssid, password):
    """Sends SET_WIFI to the first COM port that opens. Returns the port or None."""
    for port in list_ports():
        try:
            with _open(port) as ser:
                ser.write(f"SET_WIFI:{ssid}:{password}\n".encode("utf-8"))
                time.sleep(0.4)
                return port
        except Exception:
            continue
    return None
