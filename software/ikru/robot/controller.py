import time
import websocket
from .protocol import calculate_speech_scroll_time, BOX_ANIM_DURATION_S
from ikru.audio import SonicClient


class RobotController:
    """
    Unified client interface to control IKRU:
    1. ESP32 Body Controller (ws://{ip}:81) -> DRV8833 motors, OLED eyes, text speech box.
    2. ESP32-CAM Head Unit ({audio_ip}:5000) -> SmartElex speaker with R2-D2 Astromech audio.
    """

    def __init__(
        self,
        ip="192.168.1.37",
        port=81,
        audio_ip="192.168.4.1",
        audio_port=5000,
        enable_local_audio=True,
        volume=0.20
    ):
        self.ip = ip
        self.port = port
        self.ws = None
        self.connected = False
        self._connect()

        # Initialize Sonic Audio Client targeting ESP32-CAM Head Unit
        self.sonic = SonicClient(
            ip=audio_ip,
            port=audio_port,
            enable_local_audio=enable_local_audio,
            volume=volume
        )

    def _connect(self):
        try:
            print(f"[Robot] Connecting to ws://{self.ip}:{self.port}...")
            self.ws = websocket.create_connection(
                f"ws://{self.ip}:{self.port}",
                timeout=3,
                http_proxy_host=None,
                http_proxy_port=None
            )
            self.connected = True
            print("[Robot] WebSocket connected successfully!")
        except Exception as e:
            print(f"[Robot] Connection failed: {e}")
            self.connected = False

    def send(self, cmd):
        """Sends a raw text command to the ESP32 Body controller."""
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
        self.sonic.play_emotion("excited", 0.9)

    def sing(self):
        self.send("SING")
        self.sonic.play_emotion("happy", 0.8)

    # Display & Speech Commands
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
        Coordinates full speech response:
        - Animates eye expressions on ESP32 Body OLED.
        - Scrolls text response across OLED speech box.
        - Simultaneously plays speech-paced R2-D2 droid vocalizations on the ESP32-CAM Head Speaker!
        """
        if not segments:
            return

        self.display_open()
        for emotion, text in segments:
            # 1. Update eye animation on OLED
            self.set_emotion(emotion)

            if text:
                # 2. Trigger R2-D2 Droid Vocalization on ESP32-CAM Head Speaker
                self.sonic.play_sentence(text, emotion_override=emotion)

                # 3. Display text and wait for scroll completion
                self.display(text)
                wait_time = calculate_speech_scroll_time(text)
                time.sleep(wait_time)

        self.display_close()

    def speak_droid(self, text, emotion=None):
        """Helper to speak any sentence directly in R2-D2 droid vocalizations."""
        self.sonic.play_sentence(text, emotion_override=emotion)

    def play_sound(self, emotion, intensity=0.5):
        """Helper to play a canned emotion sound signature."""
        self.sonic.play_emotion(emotion, intensity=intensity)

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
