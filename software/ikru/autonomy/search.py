import math
import time
import random

from .config import CAMERA_SETTLE_S, SONAR_SETTLE_S
from .world_model import clean_label, labels_match


FOUND_LINES = [
    "[glee]Found it! The {target} is right here in front of me [laughter]!",
    "[awe]There it is [gasp]! I found the {target}!",
    "[happy]Mission complete [giggle]! The {target} was hiding right here.",
]
NOT_IT_LINES = [
    "[skeptic]Hmm, that's a {what}, not the {target}. [focused]Still looking!",
    "[unimpressed]Just a {what} [sigh]. The search continues!",
    "[focused]Nope, a {what}. Where are you hiding, {target}?",
]
GIVE_UP_LINES = [
    "[sad]I searched all around my patch of desk but couldn't find the {target} [sigh]. Maybe it's further away than I'm allowed to roll?",
    "[worried]No {target} anywhere nearby [sigh]. Could you point me in the right direction?",
]


class SearchTask:
    """State of one 'go find X' request."""

    CHECKED_RADIUS_CM = 15.0

    def __init__(self, target, timeout_s):
        self.target = clean_label(target)
        self.started = time.time()
        self.deadline = self.started + float(timeout_s)
        self.status = "active"            # active | found | gave_up | cancelled
        self.checked = []                 # [(x, y, label)] obstacles already inspected
        self.found_label = None
        self.tried_hint = False           # headed to where the world model last saw it

    def expired(self):
        return time.time() > self.deadline

    def already_checked(self, x, y):
        return any(math.hypot(x - cx, y - cy) <= self.CHECKED_RADIUS_CM for cx, cy, _ in self.checked)

    def mark_checked(self, x, y, label):
        self.checked.append((x, y, label))


def classify_obstacle(vlm, jpeg, target):
    """
    Asks the VLM what the obstacle in front of IKRU is and whether it's `target`.
    Returns {"what": str, "match": bool, "confidence": float} or None.
    """
    if hasattr(vlm, "classify_target"):
        return vlm.classify_target(jpeg, target)
    # Older VLM clients: fall back to naming objects and matching words
    if hasattr(vlm, "list_objects"):
        res = vlm.list_objects(jpeg)
        if not res:
            return None
        objects = res.get("objects") or []
        hit = next((o for o in objects if labels_match(o, target)), None)
        return {"what": hit or (objects[0] if objects else "something"),
                "match": hit is not None, "confidence": 0.7 if hit else 0.0}
    return None


class ObjectSearcher:
    """
    Searches the desk for a named object. It roams with the same planner as free
    roaming, but whenever the ultrasonic sensor finds an obstacle it stops, sends
    the camera frame of that obstacle to the VLM, and asks whether it is the
    target. Not it -> remember the spot (never re-check it), say so, turn away and
    keep searching. It is -> announce it and finish. Out of time -> give up.
    """

    def __init__(self, loco, world, cfg, vision=None, vlm=None, speak=None, should_yield=None):
        self.loco = loco
        self.world = world
        self.cfg = cfg
        self.vision = vision
        self.vlm = vlm
        self.speak = speak or (lambda text: print(f"[Search] {text}"))
        self.should_yield = should_yield or (lambda: False)

    def can_search(self):
        return bool(self.vision and self.vlm)

    # ------------------------------------------------------------------ #

    def inspect(self, task):
        """Stops in front of the obstacle and asks the VLM about it. None if no verdict."""
        self.loco.stop()
        self.loco.express("focused")
        try:
            self.loco.robot.look_front()
        except Exception:
            pass
        if not self.loco.wait(CAMERA_SETTLE_S):
            return None
        try:
            jpeg = self.vision.buffer.get_jpeg_bytes()
        except Exception:
            jpeg = None
        if not jpeg:
            print("[Search] No camera frame available.")
            return None
        print(f"[Search] Obstacle ahead — checking whether it's the {task.target}...")
        try:
            verdict = classify_obstacle(self.vlm, jpeg, task.target)
        except Exception as e:
            print(f"[Search] Classification error: {e}")
            return None
        if verdict:
            print(f"[Search] VLM says: {verdict}")
        return verdict

    def is_target(self, verdict, target):
        if not verdict:
            return False
        conf = float(verdict.get("confidence", 0.0) or 0.0)
        return bool(verdict.get("match")) and conf >= self.cfg["search_min_confidence"]

    def _turn_away(self):
        self.loco.turn(random.choice([1, -1]) * random.uniform(100, 160))
        self.loco.wait(SONAR_SETTLE_S)

    def _preferred_turn(self, task):
        """Head for where the world model last saw the target (inside the leash only)."""
        if task.tried_hint or self.world.outside_leash():
            return None
        pos = self.world.landmark_position(task.target)
        if not pos:
            return None
        if self.world.distance_to(*pos) < 12.0 or math.hypot(*pos) > self.world.leash_cm:
            task.tried_hint = True
            return None
        return self.world.bearing_to(*pos)

    def run(self, task):
        """Runs until found / gave up / cancelled, or returns early (status 'active') to yield."""
        stop_cm = self.cfg["roam_stop_cm"]
        print(f"[Search] Looking for: {task.target}")
        while task.status == "active":
            if self.should_yield():
                return task.status
            if task.expired():
                task.status = "gave_up"
                print(f"[Search] Gave up on the {task.target}.")
                self.speak(random.choice(GIVE_UP_LINES).format(target=task.target))
                return task.status

            dist, _ = self.loco.sense()
            if 0.0 < dist < stop_cm:
                pos = self.world.point_ahead(dist)
                if task.already_checked(*pos):
                    self._turn_away()           # seen this one already — don't waste a VLM call
                    continue

                verdict = self.inspect(task)
                if verdict is None:
                    if self.should_yield():
                        return task.status
                    task.mark_checked(*pos, "unknown")
                    self._turn_away()
                    continue

                what = clean_label(verdict.get("what") or "") or "something"
                task.mark_checked(*pos, what)
                if what != "something":
                    self.world.observe_objects([what])

                if self.is_target(verdict, task.target):
                    task.status = "found"
                    task.found_label = what
                    self.world.observe_objects([task.target])
                    print(f"[Search] FOUND the {task.target} ({what}).")
                    self.speak(random.choice(FOUND_LINES).format(target=task.target))
                    return task.status

                self.speak(random.choice(NOT_IT_LINES).format(target=task.target, what=what))
                if self.should_yield():
                    return task.status
                self._turn_away()
                continue

            self.loco.explore_step(self._preferred_turn(task))
        return task.status
