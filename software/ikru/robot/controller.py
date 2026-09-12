import time
import threading
import websocket
from .protocol import calculate_speech_scroll_time, BOX_ANIM_DURATION_S


class RobotController:
    """
    Client interface to control IKRU ESP32 Body Controller (ws://{ip}:81):
    DRV8833 motors, OLED eye animations, and speech text box.
    """

    def __init__(
        self,
        ip="192.168.1.34",
        port=81,
        auto_reconnect=True,
        ping_interval=5,
        ping_timeout=3,
        **kwargs
    ):
        self.ip = ip
        self.port = port
        self.auto_reconnect = auto_reconnect
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.ws = None
        self.connected = False
        self._running = True
        self._lock = threading.Lock()

        self._connect(silent=False)

        # Start background heartbeat & auto-reconnect worker
        self._bg_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._bg_thread.start()

    def _connect(self, silent=False):
        import socket
        candidates = []
        if self.ip:
            candidates.append(self.ip)
        
        # Add mDNS hostnames first
        for host in ["ikru-robot.local", "ikru.local", "ikru-robot", "ikru"]:
            if host not in candidates:
                candidates.append(host)

        # Try mDNS socket resolution to get active IP if possible
        for host in ["ikru-robot.local", "ikru.local"]:
            try:
                resolved_ip = socket.gethostbyname(host)
                if resolved_ip and resolved_ip not in candidates:
                    candidates.insert(0, resolved_ip)
            except Exception:
                pass

        # Fallback known static IP candidates
        for candidate in ["192.168.1.42", "192.168.1.34", "192.168.4.2", "192.168.4.1", "192.168.1.37", "192.168.1.40"]:
            if candidate not in candidates:
                candidates.append(candidate)

        for target_ip in candidates:
            try:
                if not silent:
                    print(f"[Robot] Trying ws://{target_ip}:{self.port}...")
                timeout_s = 4.0 if target_ip in (self.ip, "ikru-robot.local") else 1.5
                new_ws = websocket.create_connection(
                    f"ws://{target_ip}:{self.port}",
                    timeout=timeout_s,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    http_proxy_host=None,
                    http_proxy_port=None
                )
                with self._lock:
                    self.ws = new_ws
                    self.ip = target_ip
                    self.connected = True
                print(f"[Robot] WebSocket connected successfully to {self.ip}!")
                return True
            except Exception:
                pass

        if not silent:
            print(f"[Robot] Connection failed on candidates {candidates}. Robot body/OLED offline.")
        with self._lock:
            self.connected = False
        return False

    def _handle_disconnect(self):
        with self._lock:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
                self.ws = None
            self.connected = False

    def _heartbeat_loop(self):
        """Continuously sends low-overhead ping frames and automatically reconnects if offline."""
        while self._running:
            time.sleep(self.ping_interval)
            if not self._running:
                break

            if self.connected and self.ws:
                try:
                    with self._lock:
                        if self.ws:
                            self.ws.ping()
                except Exception as e:
                    print(f"[Robot] Keep-alive ping failed ({e}). Reconnecting in background...")
                    self._handle_disconnect()
            elif not self.connected and self.auto_reconnect:
                # Attempt silent reconnection in background
                self._connect(silent=True)

    def send(self, cmd):
        """Sends a raw text command to the ESP32 Body controller."""
        if not self.connected or not self.ws:
            return
        try:
            with self._lock:
                if self.connected and self.ws:
                    self.ws.send(cmd)
        except Exception as e:
            print(f"[Robot] Send error: {e}")
            self._handle_disconnect()

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

    # Display & Speech Commands
    def display(self, text):
        self.send(f"DISPLAY:{text}")

    def display_open(self):
        self.send("DISPLAY_OPEN")
        time.sleep(BOX_ANIM_DURATION_S)

    def display_close(self):
        self.send("DISPLAY_CLOSE")
        time.sleep(BOX_ANIM_DURATION_S)

    def play_audio(self, url):
        """Tells ESP32 to stream and play a WAV audio URL over I2S."""
        print(f"[Robot] Dispatched SPEAK_URL to ESP32: {url}")
        self.send(f"SPEAK_URL:{url}")

    def stop_audio(self):
        """Stops active audio playback on ESP32."""
        self.send("STOP_AUDIO")

    def set_volume(self, volume: int):
        """Sets robot speaker volume (0 to 100)."""
        vol = max(0, min(100, int(volume)))
        print(f"[Robot] Setting speaker volume to {vol}%")
        return self.send(f"VOLUME:{vol}")

    def speak_segments(self, segments, audio_service=None, play_pc=None, stream_robot=True):
        """
        Coordinates speech response:
        - Synthesizes and streams natural voice audio over I2S (via AudioService).
        - Displays full-screen animated facial expressions on ESP32 Body OLED.
        - Synchronizes emotion transitions with the speech playback duration.
        """
        if not segments:
            return

        svc = audio_service or getattr(self, "audio_service", None)
        full_text = " ".join(txt for _, txt in segments if txt).strip()

        audio_url = None
        duration = 0.0

        if svc and full_text:
            print(f"[Robot] Synthesizing speech: \"{full_text}\" (play_pc={play_pc})...")
            audio_url = svc.synthesize(full_text, play_pc=play_pc)
            duration = getattr(svc, "last_duration", 0.0)
            print(f"[Robot] Speech ready ({duration:.2f}s): {audio_url}")

        # Start streaming natural voice via I2S to ESP32 speaker
        if stream_robot and audio_url:
            self.play_audio(audio_url)

        # Distribute playback duration across emotion segments with buffering
        total_len = max(1, sum(len(txt.strip()) for _, txt in segments if txt))
        effective_duration = max(duration, len(full_text) * 0.08)

        for emotion, text in segments:
            seg_len = len(text.strip()) if text else 1
            seg_time = max(1.2, (seg_len / total_len) * effective_duration)
            print(f"[Robot] Displaying OLED Expression: [{emotion.upper()}] ({seg_time:.1f}s)")
            self.set_emotion(emotion)
            time.sleep(seg_time)

        # Brief post-speech settling pause before returning to calm normal
        time.sleep(0.4)
        self.normal()

    # Emotions
    def set_emotion(self, emotion):
        method = getattr(self, emotion.lower(), None)
        if method and callable(method):
            method()
        else:
            self.happy()

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

    # Compatibility Aliases
    def set_face(self, emotion):
        self.set_emotion(emotion)

    def speak(self, url, duration=0):
        self.play_audio(url)

    def connect(self):
        self._connect(silent=False)

    def close(self):
        self._running = False
        self.auto_reconnect = False
        self._handle_disconnect()
        print("[Robot] Connection closed.")
