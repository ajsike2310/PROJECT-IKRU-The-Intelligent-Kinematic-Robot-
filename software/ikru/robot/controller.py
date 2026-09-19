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
    def forward(self, duration=0, check_proximity=True):
        if duration <= 0:
            self.send("FORWARD")
            return

        self.send("FORWARD")
        remaining = float(duration)

        while remaining > 0:
            if check_proximity and hasattr(self, "proximity_monitor") and self.proximity_monitor:
                dist = self.proximity_monitor.get_distance()
                if 0.0 < dist < 12.0:
                    print(f"[Robot] Obstacle detected at {dist:.1f} cm! Pausing forward movement...")
                    self.stop()
                    self.worried()

                    # Wait for obstacle to clear
                    while True:
                        time.sleep(0.15)
                        dist = self.proximity_monitor.get_distance()
                        if dist <= 0.0 or dist >= 14.0:
                            print("[Robot] Path cleared! Resuming forward movement...")
                            self.send("FORWARD")
                            self.happy()
                            break

            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk

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

    def spin_left(self, duration=0):
        self.left(duration)

    def spin_right(self, duration=0):
        self.right(duration)

    def wiggle(self, duration=0.8):
        step_t = max(0.1, duration / 4.0)
        self.left(step_t)
        self.right(step_t * 2)
        self.left(step_t)
        self.stop()

    def play_sequence(self, sequence_name_or_list):
        """Plays a multi-modal recorded emotion sequence by name or step list."""
        from .sequences import SequenceRunner
        runner = SequenceRunner(self)
        return runner.play_sequence(sequence_name_or_list)

    # Distance & Obstacle Avoidance Commands
    def get_distance(self, timeout=1.2) -> float:
        """
        Queries the ESP32 for the current ultrasonic distance in centimeters.
        Returns distance in cm (e.g. 25.4), or -1.0 if sensor timed out or offline.
        """
        if not self.connected or not self.ws:
            return -1.0
        try:
            with self._lock:
                if not (self.connected and self.ws):
                    return -1.0
                self.ws.send("GET_DISTANCE")
                self.ws.settimeout(timeout)
                start_t = time.time()
                while time.time() - start_t < timeout:
                    reply = self.ws.recv()
                    if not reply:
                        continue
                    if "distance" in reply:
                        import json
                        data = json.loads(reply)
                        return float(data.get("cm", -1.0))
        except Exception:
            pass
        finally:
            try:
                if self.ws:
                    self.ws.settimeout(self.ping_timeout)
            except Exception:
                pass
        return -1.0

    def set_obstacle_threshold(self, cm: float):
        """Sets the safety emergency brake threshold distance in centimeters."""
        self.send(f"SET_OBSTACLE_THRESHOLD:{float(cm):.1f}")

    def enable_obstacle_brake(self):
        """Enables the automatic emergency stop when an obstacle is close."""
        self.send("OBSTACLE_BRAKE_ON")

    def disable_obstacle_brake(self):
        """Disables the automatic emergency stop."""
        self.send("OBSTACLE_BRAKE_OFF")

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
        """Tells ESP32 to stream and play audio."""
        print(f"[Robot] Dispatched audio command to ESP32: {url}")
        if url.startswith("http://") or url.startswith("https://"):
            self.send(f"SPEAK_URL:{url}")
        else:
            self.send(f"SOUND:{url}")

    def play_sound(self, sound_name: str, intensity: float = 0.5):
        """Plays an authentic R2-D2 glissando frequency sweep on the SmartElex speaker."""
        print(f"[Robot] Playing Droid Sound: {sound_name} (intensity={intensity})")
        self.send(f"SOUND:{sound_name}:{intensity:.2f}")

    def stop_audio(self):
        """Stops active audio playback on ESP32."""
        self.send("STOP_AUDIO")

    def set_volume(self, volume: int):
        """Sets robot speaker volume (0 to 100)."""
        vol = max(0, min(100, int(volume)))
        print(f"[Robot] Setting speaker volume to {vol}%")
        return self.send(f"VOLUME:{vol}")

    def speak_segments(self, segments, audio_service=None, play_pc=None, stream_robot=True, interrupt_event=None):
        """
        Coordinates instant robotic speech & expression response:
        - Fires instant R2-D2 glissando chirps & warbles on the SmartElex digital speaker.
        - Synchronizes full-screen animated facial expressions on the ESP32 OLED.
        - Zero audio latency (<5ms) without requiring a live audio network streaming server.
        """
        if not segments:
            return

        import re
        sound_tag_pattern = re.compile(
            r'\[(sigh|gasp|giggle|chuckle|laugh|laughter|groan|clear_throat|throat|cry|sob|whisper|sniff|cough|sneeze|inhale|exhale|thinking|processing|success|error)\]',
            re.IGNORECASE
        )

        for emotion, text in segments:
            if interrupt_event and interrupt_event.is_set():
                break

            text_str = text.strip() if text else ""
            
            # Extract clean display text (strip tags)
            clean_text = re.sub(r'\[[^\]]*\]', '', text_str).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)

            # Check if this segment contains an inline paralinguistic sound tag
            sound_match = sound_tag_pattern.search(text_str) if text_str else None
            sound_tag = sound_match.group(1).lower() if sound_match else None

            if sound_tag:
                tag_method = getattr(self, sound_tag, None)
                if tag_method and callable(tag_method):
                    print(f"[Robot] Triggering Paralinguistic Sound: [{sound_tag.upper()}]")
                    tag_method()
                else:
                    self.play_sound(sound_tag)
            else:
                print(f"[Robot] Triggering Expression & Sound: [{emotion.upper()}]")
                self.set_emotion(emotion)

            # Send text to OLED speech box and let droid chatter play for the full duration of the scroll
            if clean_text:
                self.display(clean_text)
                scroll_time = calculate_speech_scroll_time(clean_text)
                
                # Sleep in chunks to allow rapid interruption
                chunk = 0.1
                elapsed = 0.0
                while elapsed < scroll_time:
                    if interrupt_event and interrupt_event.is_set():
                        break
                    time.sleep(chunk)
                    elapsed += chunk
            else:
                # No text, just pause slightly for the emotion/sound
                chunk = 0.1
                elapsed = 0.0
                while elapsed < 1.2:
                    if interrupt_event and interrupt_event.is_set():
                        break
                    time.sleep(chunk)
                    elapsed += chunk

            if interrupt_event and interrupt_event.is_set():
                self.stop_audio()
                self.send("DISPLAY_CLOSE")
                break

        # Brief post-speech settling pause before returning to calm normal
        if interrupt_event and interrupt_event.is_set():
            self.normal()
            return

        time.sleep(0.3)
        self.normal()

    # Visual Emotions (Triggers both OLED Eye Animation & Droid Tone on ESP32)
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

    # Eye Look & Blink Commands
    def blink(self): self.send("BLINK")
    def look_at(self, x: float, y: float): self.send(f"LOOK:{x:.2f}:{y:.2f}")
    def look_left(self): self.send("LOOK_LEFT")
    def look_right(self): self.send("LOOK_RIGHT")
    def look_front(self): self.send("LOOK_FRONT")
    def look_top(self): self.send("LOOK_TOP")
    def look_bottom(self): self.send("LOOK_BOTTOM")

    # Idle Yawn Micro-expression
    def yawn(self):
        """Triggers a realistic yawning idle micro-expression."""
        self.sleepy()
        self.exhale()
        time.sleep(1.2)
        self.normal()
        self.look_front()

    # Paralinguistic Vocal Sounds
    def sigh(self): self.send("SIGH")
    def gasp(self): self.send("GASP")
    def giggle(self): self.send("GIGGLE")
    def chuckle(self): self.send("GIGGLE")
    def laugh(self): self.send("LAUGH")
    def laughter(self): self.send("LAUGHTER")
    def groan(self): self.send("GROAN")
    def clear_throat(self): self.send("CLEAR_THROAT")
    def cry(self): self.send("CRY")
    def sob(self): self.send("CRY")
    def whisper(self): self.send("WHISPER")
    def sniff(self): self.send("SNIFF")
    def cough(self): self.send("COUGH")
    def sneeze(self): self.send("SNEEZE")
    def inhale(self): self.send("INHALE")
    def exhale(self): self.send("EXHALE")
    def thinking(self): self.send("THINKING")
    def success(self): self.send("SUCCESS")
    def error(self): self.send("ERROR")

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
