import time
import threading


class ProximityMonitor:
    """
    Background Ultrasonic Proximity Safety & Reaction System:
    - Continuously polls HC-SR04 ultrasonic sensor in the background regardless of robot state.
    - DANGER (< 10cm): Triggers instant emergency retreat reflex (stops forward motors, backs up, scared face + gasp).
    - CAUTION (10cm - 30cm): Triggers curious/startled glance (surprised face, glance up, chirp).
    - CLEAR (> 30cm): Normal clear state.
    - Provides real-time sensor context formatted for LLM prompts.
    """

    DANGER_THRESHOLD_CM = 10.0
    CAUTION_THRESHOLD_CM = 30.0

    def __init__(self, robot_controller, idle_manager=None, poll_interval=0.25):
        self.robot = robot_controller
        self.idle_manager = idle_manager
        self.poll_interval = poll_interval
        self.running = False
        self.paused = False
        self.current_distance_cm = 999.0
        self.current_zone = "CLEAR"  # "DANGER", "CAUTION", or "CLEAR"
        self.thread = None
        self._lock = threading.Lock()
        self.last_danger_time = 0
        self.last_caution_time = 0

    def start(self):
        """Starts the background ultrasonic proximity monitoring thread."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            print("[Proximity] Ultrasonic Proximity Monitor started.")

    def stop(self):
        """Stops the proximity monitoring thread."""
        with self._lock:
            self.running = False
        print("[Proximity] Ultrasonic Proximity Monitor stopped.")

    def pause(self):
        """Suppress reflex reactions while IKRU is speaking / executing tools.
        Distance polling continues so sensor context stays fresh for the LLM."""
        with self._lock:
            self.paused = True

    def resume(self):
        """Re-enable reflex reactions after IKRU finishes its turn."""
        with self._lock:
            self.paused = False

    def get_distance(self):
        """Returns the latest measured distance in cm."""
        with self._lock:
            return self.current_distance_cm

    def get_zone(self):
        """Returns the current proximity zone ('DANGER', 'CAUTION', or 'CLEAR')."""
        with self._lock:
            return self.current_zone

    def get_sensor_context(self):
        """Generates real-time proximity context formatted for LLM prompts."""
        dist = self.get_distance()
        zone = self.get_zone()

        if dist < 0 or dist > 350.0:
            return "[Proximity Sensor: Path clear (>100 cm)]"
        
        if zone == "DANGER":
            return f"[Proximity Sensor: DANGER ALERT! An object/hand is extremely close at {dist:.1f} cm! You are startled and backing up.]"
        elif zone == "CAUTION":
            return f"[Proximity Sensor: CAUTION! An object or hand is close at {dist:.1f} cm.]"
        else:
            return f"[Proximity Sensor: Path clear ({dist:.1f} cm)]"

    def _monitor_loop(self):
        while self.running:
            time.sleep(self.poll_interval)
            if not self.running:
                break

            if not (self.robot and self.robot.connected):
                continue

            try:
                # Query ESP32 ultrasonic distance
                cm = self.robot.get_distance(timeout=0.6)
                now = time.time()

                with self._lock:
                    self.current_distance_cm = cm

                    # Update Zone
                    if 0.0 < cm < self.DANGER_THRESHOLD_CM:
                        new_zone = "DANGER"
                    elif self.DANGER_THRESHOLD_CM <= cm <= self.CAUTION_THRESHOLD_CM:
                        new_zone = "CAUTION"
                    else:
                        new_zone = "CLEAR"

                    old_zone = self.current_zone
                    self.current_zone = new_zone
                    paused = self.paused

                # Skip physical reflexes while paused (user is talking / IKRU is speaking).
                # Distance & zone are still updated so the LLM sees fresh sensor context.
                if paused:
                    continue

                # 1. DANGER REFLEX (< 10cm) — High priority real-time reaction
                if new_zone == "DANGER":
                    if now - self.last_danger_time > 2.0:
                        self.last_danger_time = now
                        print(f"\n[Proximity] 🚨 DANGER REFLEX! Object encroaching at {cm:.1f} cm! Backing up...")
                        try:
                            # Immediate physical emergency reaction
                            self.robot.stop()
                            self.robot.scared()
                            self.robot.gasp()
                            self.robot.backward(duration=0.4)
                            self.robot.worried()
                        except Exception as e:
                            print(f"[Proximity] Reaction error: {e}")

                # 2. CAUTION REFLEX (10cm - 30cm) — Subtle glance reaction
                elif new_zone == "CAUTION":
                    if now - self.last_caution_time > 3.5 and old_zone == "CLEAR":
                        self.last_caution_time = now
                        print(f"\n[Proximity] 👀 CAUTION: Object detected close at {cm:.1f} cm.")
                        try:
                            self.robot.surprised()
                            self.robot.look_top()
                            self.robot.whisper()
                            time.sleep(0.8)
                            self.robot.normal()
                            self.robot.look_front()
                        except Exception as e:
                            print(f"[Proximity] Reaction error: {e}")

            except Exception as e:
                pass
