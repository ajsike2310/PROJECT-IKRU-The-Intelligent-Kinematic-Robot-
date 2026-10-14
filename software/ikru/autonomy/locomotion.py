import time
import random

from .config import BURST_S, MAX_TURN_S, SONAR_SETTLE_S, ECHO_GUARD_S


class Locomotion:
    """
    Safe motion primitives shared by roaming and object search. Every move keeps
    the WorldModel's dead-reckoned pose in sync and bails out the moment
    `should_yield()` says the user needs the stage.
    """

    def __init__(self, robot, world, cfg, proximity_monitor=None, should_yield=None, on_sound=None):
        self.robot = robot
        self.world = world
        self.cfg = cfg
        self.proximity_monitor = proximity_monitor
        self.should_yield = should_yield or (lambda: False)
        self.on_sound = on_sound or (lambda seconds=ECHO_GUARD_S: None)

    # ------------------------------------------------------------------ #
    # Basics
    # ------------------------------------------------------------------ #

    def wait(self, seconds):
        """Sleeps in small chunks; returns False if we should yield."""
        end = time.time() + seconds
        while time.time() < end:
            if self.should_yield():
                return False
            time.sleep(min(0.05, max(0.0, end - time.time())))
        return True

    def stop(self):
        try:
            self.robot.stop()
        except Exception:
            pass

    def set_speed(self, pct):
        setter = getattr(self.robot, "set_speed", None)
        if setter:
            try:
                setter(pct)
            except Exception:
                pass

    def express(self, emotion):
        """Face changes also play a droid tone on the ESP32 — guard the mic against it."""
        self.on_sound()
        try:
            self.robot.set_emotion(emotion)
        except Exception:
            pass

    def read_distance(self):
        try:
            if self.proximity_monitor:
                return float(self.proximity_monitor.get_distance())
            return float(self.robot.get_distance(timeout=0.4))
        except Exception:
            return -1.0

    def sense(self):
        """Reads the ultrasonic sensor and feeds it to the world model. Returns (cm, surprise)."""
        dist = self.read_distance()
        return dist, self.world.observe_range(dist)

    # ------------------------------------------------------------------ #
    # Moves
    # ------------------------------------------------------------------ #

    def turn(self, deg):
        """Spins in place by roughly `deg` (positive = left) and updates the world model."""
        if abs(deg) < 5:
            return
        duration = min(abs(deg) / max(self.cfg["turn_deg_per_s"], 1.0), MAX_TURN_S)
        try:
            (self.robot.look_left if deg > 0 else self.robot.look_right)()
            (self.robot.left if deg > 0 else self.robot.right)(duration)
        except Exception as e:
            print(f"[Autonomy] Turn error: {e}")
            self.stop()
        self.world.apply_turn(duration * self.cfg["turn_deg_per_s"] * (1 if deg > 0 else -1))
        try:
            self.robot.look_front()
        except Exception:
            pass

    def turn_and_sense(self, deg):
        """Turn, let the sonar settle, and take a fresh reading. Returns cm (or None if yielding)."""
        self.turn(deg)
        if not self.wait(SONAR_SETTLE_S):
            return None
        return self.sense()[0]

    def drive_burst(self, duration):
        """Short forward scoot, watching the ultrasonic sensor and the user. Returns cm moved."""
        stop_cm = self.cfg["roam_stop_cm"]
        d = self.read_distance()
        if 0.0 < d < stop_cm:
            return 0.0
        t0 = time.time()
        try:
            self.robot.send("FORWARD")
            while time.time() - t0 < duration:
                if self.should_yield():
                    break
                d = self.read_distance()
                if 0.0 < d < stop_cm:
                    break
                time.sleep(0.05)
        finally:
            self.stop()
        moved = (time.time() - t0) * self.cfg["forward_cm_per_s"]
        self.world.apply_forward(moved)
        return moved

    def look_around(self):
        """Pause, glance left and right like it's taking in the scenery."""
        self.stop()
        self.express(random.choice(["focused", "skeptic", "happy", "normal"]))
        try:
            first, second = random.sample([self.robot.look_left, self.robot.look_right], 2)
            first()
            if not self.wait(random.uniform(0.5, 0.9)):
                return
            second()
            if not self.wait(random.uniform(0.5, 0.9)):
                return
            self.robot.look_front()
        except Exception:
            pass

    def explore_step(self, preferred_turn=None):
        """
        One planned hop: pick a heading (world model or `preferred_turn`), turn,
        and scoot forward if the way is clear. Returns the fresh distance reading.
        """
        step_cm = sum(BURST_S) / 2.0 * self.cfg["forward_cm_per_s"]
        turn = preferred_turn if preferred_turn is not None else self.world.choose_turn(step_cm)
        dist = self.read_distance()
        if abs(turn) > 10:
            dist = self.turn_and_sense(turn)
            if dist is None:
                return -1.0
        if 0.0 < dist < self.cfg["roam_stop_cm"]:
            return dist     # blocked this way; the grid now knows
        if random.random() < 0.15:
            try:
                self.robot.blink()
            except Exception:
                pass
        self.drive_burst(random.uniform(*BURST_S))
        self.wait(random.uniform(0.2, 0.7))     # scoot rhythm
        return dist

    def go_home(self, max_steps=12):
        """Rolls back toward the home spot (keeps dead-reckoning drift from piling up)."""
        stop_cm = self.cfg["roam_stop_cm"]
        for _ in range(max_steps):
            if self.should_yield():
                return
            d = self.world.distance_from_home()
            if d < 10.0:
                return
            turn = self.world.bearing_to_home()
            if abs(turn) > 15:
                self.turn(turn)
                if not self.wait(SONAR_SETTLE_S):
                    return
            dist, _ = self.sense()
            if 0.0 < dist < stop_cm:
                self.turn(random.choice([60, -60]))
                self.wait(SONAR_SETTLE_S)
                self.drive_burst(BURST_S[0])
                continue
            self.drive_burst(max(0.15, min(BURST_S[1], d / max(self.cfg["forward_cm_per_s"], 1.0))))
            self.wait(0.2)
