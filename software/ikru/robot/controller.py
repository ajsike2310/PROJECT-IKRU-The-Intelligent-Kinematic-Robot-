import time
import websocket
from .protocol import calculate_speech_scroll_time, BOX_ANIM_DURATION_S


class RobotController:
    """
    WebSocket client interface to control IKRU ESP32 robot body, motors, and OLED expressions.
    """

    def __init__(self, ip="192.168.1.37", port=81):
        self.ip = ip
        self.port = port
        self.ws = None
        self.connected = False
        self._connect()

    def _connect(self):
        try:
            print(f"[Robot] Connecting to ws://{self.ip}:{self.port}...")
            self.ws = websocket.create_connection(
                f"ws://{self.ip}:{self.port}",
                timeout=5,
                http_proxy_host=None,
                http_proxy_port=None
            )
            self.connected = True
            print("[Robot] WebSocket connected successfully!")
        except Exception as e:
            print(f"[Robot] Connection failed: {e}")
            self.connected = False

    def send(self, cmd):
        """Sends a raw text command to the ESP32."""
        if not self.connected or not self.ws:
            return
        try:
            self.ws.send(cmd)
            try:
                reply = self.ws.recv()
                print(f"[Robot] {reply.strip()}")
            except Exception:
                pass
        except Exception as e:
            print(f"[Robot] Send error: {e}")
            self.connected = False

    # Movement Commands
    def forward(self, duration=0):
        self.send("FORWARD")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def backward(self, duration=0):
        self.send("BACKWARD")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def left(self, duration=0):
        self.send("LEFT")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def right(self, duration=0):
        self.send("RIGHT")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def stop(self, duration=0):
        self.send("STOP")

    def dance(self):
        self.send("DANCE")

    def sing(self):
        self.send("SING")

    # Display Commands
    def display(self, text):
        self.send(f"DISPLAY:{text}")

    def display_open(self):
        self.send("DISPLAY_OPEN")
        time.sleep(BOX_ANIM_DURATION_S)

    def display_close(self):
        self.send("DISPLAY_CLOSE")
        time.sleep(BOX_ANIM_DURATION_S)

    def speak_segments(self, segments):
        """
        Coordinates full speech response on OLED with dynamic face expressions.
        """
        if not segments:
            return

        self.display_open()
        for emotion, text in segments:
            # Set expression
            self.set_emotion(emotion)

            # Display and wait for scroll
            if text:
                self.display(text)
                wait_time = calculate_speech_scroll_time(text)
                time.sleep(wait_time)

        self.display_close()

    # Emotions
    def set_emotion(self, emotion):
        method = getattr(self, emotion.lower(), None)
        if method and callable(method):
            method()
        else:
            self.normal()

    def normal(self): self.send("NORMAL")
    def happy(self): self.send("HAPPY")
    def glee(self): self.send("GLEE")
    def sad(self): self.send("SAD")
    def worried(self): self.send("WORRIED")
    def focused(self): self.send("FOCUSED")
    def annoyed(self): self.send("ANNOYED")
    def surprised(self): self.send("SURPRISED")
    def skeptic(self): self.send("SKEPTIC")
    def frustrated(self): self.send("FRUSTRATED")
    def unimpressed(self): self.send("UNIMPRESSED")
    def sleepy(self): self.send("SLEEPY")
    def suspicious(self): self.send("SUSPICIOUS")
    def squint(self): self.send("SQUINT")
    def angry(self): self.send("ANGRY")
    def furious(self): self.send("FURIOUS")
    def scared(self): self.send("SCARED")
    def awe(self): self.send("AWE")

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.connected = False
            print("[Robot] Connection closed.")
