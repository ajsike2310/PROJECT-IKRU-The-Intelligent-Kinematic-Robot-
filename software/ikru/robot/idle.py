import time
import random
import threading


class IdleManager:
    """
    Background daemon manager for IKRU's Idle Behavior:
    - Periodic eye blinks & double-blinks
    - Random natural eye gaze drifts (saccades)
    - Occasional yawns, sighs, and curious micro-expressions
    Automatically pauses during active user listening, LLM thinking, or speech.
    """

    def __init__(self, robot_controller, min_idle_sec=3.0):
        self.robot = robot_controller
        self.min_idle_sec = min_idle_sec
        self.running = False
        self.paused = False
        self.last_activity_time = time.time()
        self.thread = None
        self._lock = threading.Lock()

    def start(self):
        """Starts the background idle behavior thread."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self.paused = False
            self.last_activity_time = time.time()
            self.thread = threading.Thread(target=self._idle_loop, daemon=True)
            self.thread.start()
            print("[Idle] Idle Behavior daemon started.")

    def stop(self):
        """Stops the idle behavior thread."""
        with self._lock:
            self.running = False
        print("[Idle] Idle Behavior daemon stopped.")

    def notify_activity(self):
        """Call when user starts speaking, LLM begins thinking, or motors run."""
        with self._lock:
            self.last_activity_time = time.time()
            self.paused = True

    def notify_speech_done(self):
        """Call when speaking/thinking finishes to resume idle countdown."""
        with self._lock:
            self.last_activity_time = time.time()
            self.paused = False

    def _idle_loop(self):
        next_blink_delay = random.uniform(3.0, 6.0)
        next_gaze_delay = random.uniform(4.0, 8.0)
        next_micro_delay = random.uniform(20.0, 35.0)

        last_blink = time.time()
        last_gaze = time.time()
        last_micro = time.time()

        while self.running:
            time.sleep(0.3)
            if not self.running:
                break

            now = time.time()

            with self._lock:
                if self.paused or (now - self.last_activity_time) < self.min_idle_sec:
                    last_blink = now
                    last_gaze = now
                    last_micro = now
                    continue

                if not (self.robot and self.robot.connected):
                    continue

            # 1. Periodic Blinks
            if now - last_blink >= next_blink_delay:
                last_blink = now
                next_blink_delay = random.uniform(3.5, 6.5)
                try:
                    self.robot.blink()
                    if random.random() < 0.15:
                        time.sleep(0.2)
                        self.robot.blink()
                except Exception:
                    pass

            # 2. Random Eye Gaze Drifts (Saccades)
            if now - last_gaze >= next_gaze_delay:
                last_gaze = now
                next_gaze_delay = random.uniform(4.5, 9.0)
                try:
                    if random.random() < 0.3:
                        self.robot.look_front()
                    else:
                        rx = random.uniform(-0.45, 0.45)
                        ry = random.uniform(-0.3, 0.3)
                        self.robot.look_at(rx, ry)
                except Exception:
                    pass

            # 3. Occasional Idle Micro-Expressions (Yawns, Sighs, Curious Glance)
            if now - last_micro >= next_micro_delay:
                last_micro = now
                next_micro_delay = random.uniform(25.0, 45.0)
                try:
                    choice = random.random()
                    if choice < 0.40:
                        print("[Idle] Micro-expression: Yawn/Sigh")
                        self.robot.yawn()
                    elif choice < 0.70:
                        print("[Idle] Micro-expression: Curious Glance")
                        self.robot.skeptic()
                        self.robot.look_left()
                        time.sleep(1.2)
                        self.robot.happy()
                        self.robot.look_right()
                        time.sleep(1.2)
                        self.robot.normal()
                        self.robot.look_front()
                    else:
                        print("[Idle] Micro-expression: Soft Whistle/Chirp")
                        self.robot.happy()
                        self.robot.whisper()
                        time.sleep(1.0)
                        self.robot.normal()
                except Exception:
                    pass
