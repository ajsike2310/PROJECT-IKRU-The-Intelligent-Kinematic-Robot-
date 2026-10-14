import os
import re
import json
import math
import time
import random
import threading
from collections import deque


# ------------------------------------------------------------------ #
# A deliberately small "world model" for IKRU.
#
# It is not SLAM. It is the minimum internal picture a curious desk robot
# needs to feel like it knows where it is:
#   - a dead-reckoned pose (x, y, heading) from the motor commands it sent
#   - a coarse occupancy grid built from the forward ultrasonic sensor
#   - landmarks: objects the camera named, with a rough position and
#     how familiar they are (familiarity persists across sessions)
#   - predict -> observe -> surprise: before sensing, the model predicts
#     what it should see; a mismatch becomes a "surprise" event that the
#     autonomous brain turns into curiosity and speech.
#
# Coordinates: cm, origin = "home" (where IKRU was when the session started),
# +x = initial facing direction, heading in degrees, counter-clockwise positive
# (a LEFT spin increases heading).
# ------------------------------------------------------------------ #

CELL_CM = 10.0
TRUSTED_RANGE_CM = 80.0       # ultrasonic readings beyond this are treated as "open"
OCC_HIT = 0.7
OCC_FREE = -0.35
OCC_LIMIT = 2.0
OCC_BLOCKED = 0.5             # occupancy above this = blocked cell
SURPRISE_COOLDOWN_S = 15.0
OBJECT_GUESS_CM = 30.0        # objects the camera names are assumed ~this far ahead
EXPECT_VIEW_DEG = 35.0        # landmark counts as "should be visible" within this half-angle
EXPECT_VIEW_CM = 70.0

_LABEL_STOPWORDS = {
    "a", "an", "the", "some", "of", "on", "in", "with", "and", "small", "large", "big",
    "little", "tiny", "white", "black", "red", "blue", "green", "yellow", "grey", "gray",
    "brown", "silver", "dark", "light", "pink", "purple", "orange", "object", "thing",
}


def ago_phrase(seconds):
    """85 -> 'about a minute ago', 7200 -> 'about 2 hours ago'."""
    s = max(0.0, float(seconds))
    if s < 45:
        return "just now"
    if s < 90:
        return "about a minute ago"
    if s < 3600:
        return f"about {int(round(s / 60))} minutes ago"
    if s < 86400:
        h = int(round(s / 3600))
        return f"about {h} hour{'s' if h != 1 else ''} ago"
    d = int(round(s / 86400))
    return f"about {d} day{'s' if d != 1 else ''} ago"


def _norm_angle(deg):
    """Wraps an angle to (-180, 180]."""
    deg = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if deg == -180.0 else deg


def _label_words(label):
    words = re.findall(r"[a-z]+", str(label).lower())
    return {w for w in words if w not in _LABEL_STOPWORDS and len(w) > 2}


def labels_match(a, b):
    """Loose match so 'coffee mug' and 'white mug' count as the same thing."""
    wa, wb = _label_words(a), _label_words(b)
    return bool(wa and wb and (wa & wb))


def clean_label(label):
    label = re.sub(r"\s+", " ", str(label).strip().lower())
    label = re.sub(r"^(a|an|the|some)\s+", "", label)
    return label[:40]


def describe_direction(rel_deg):
    """Human phrasing for a heading relative to IKRU's nose."""
    a = _norm_angle(rel_deg)
    if abs(a) <= 25:
        return "straight ahead"
    if abs(a) >= 150:
        return "behind you"
    side = "left" if a > 0 else "right"
    return f"to your {side}" if abs(a) < 110 else f"behind you to the {side}"


class WorldModel:
    def __init__(
        self,
        leash_cm=35.0,
        cell_cm=CELL_CM,
        persist_path=None,
    ):
        self.leash_cm = float(leash_cm)
        self.cell_cm = float(cell_cm)
        self.persist_path = persist_path
        self._lock = threading.RLock()

        # Pose (per session)
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0

        # Per-session spatial memory
        self.cells = {}                    # (i, j) -> {"occ": float, "visits": int}
        self.events = deque(maxlen=12)     # (timestamp, kind, text)
        self._last_surprise = 0.0
        self.distance_travelled_cm = 0.0
        self.session_excursions = 0

        # Landmarks — familiarity persists, positions are per session
        self.landmarks = []                # list of dicts
        self.lifetime_excursions = 0
        # Rolling log of what the camera saw, newest last; persists across sessions
        self.sightings = deque(maxlen=12)  # {"t", "scene", "objects"}

        self._visit(self.x, self.y)
        self.load()

    # ------------------------------------------------------------------ #
    # Grid helpers
    # ------------------------------------------------------------------ #

    def _key(self, x, y):
        return (int(round(x / self.cell_cm)), int(round(y / self.cell_cm)))

    def _cell(self, key):
        c = self.cells.get(key)
        if c is None:
            c = {"occ": 0.0, "visits": 0}
            self.cells[key] = c
        return c

    def _visit(self, x, y):
        c = self._cell(self._key(x, y))
        c["visits"] += 1
        c["occ"] = max(-OCC_LIMIT, c["occ"] + OCC_FREE)

    def _is_blocked(self, key):
        c = self.cells.get(key)
        return bool(c and c["occ"] > OCC_BLOCKED)

    def _ray_points(self, heading, length_cm, step_cm=None):
        step = step_cm or self.cell_cm / 2.0
        rad = math.radians(heading)
        n = max(1, int(length_cm / step))
        for k in range(1, n + 1):
            d = k * step
            yield d, self.x + d * math.cos(rad), self.y + d * math.sin(rad)

    # ------------------------------------------------------------------ #
    # Motion (dead reckoning)
    # ------------------------------------------------------------------ #

    def apply_forward(self, distance_cm):
        """Advances the pose; negative distance = reversing."""
        with self._lock:
            rad = math.radians(self.heading)
            steps = max(1, int(abs(distance_cm) / (self.cell_cm / 2.0)))
            dx = distance_cm * math.cos(rad) / steps
            dy = distance_cm * math.sin(rad) / steps
            for _ in range(steps):
                self.x += dx
                self.y += dy
                self._visit(self.x, self.y)
            self.distance_travelled_cm += abs(distance_cm)

    def apply_turn(self, deg):
        with self._lock:
            self.heading = _norm_angle(self.heading + deg)

    def reset_home(self):
        """Declares the current spot as the new safe home (e.g. after IKRU was picked up)."""
        with self._lock:
            self.x = self.y = self.heading = 0.0
            self.cells.clear()
            for lm in self.landmarks:
                lm["pos"] = None
            self._visit(0.0, 0.0)
            self._add_event("reset", "You were placed in a new spot, so this is home now.")

    # ------------------------------------------------------------------ #
    # Prediction & observation (ultrasonic)
    # ------------------------------------------------------------------ #

    def predict_range(self, max_cm=TRUSTED_RANGE_CM):
        """Distance to the first cell the model believes is blocked, or None if unknown/open."""
        with self._lock:
            for d, px, py in self._ray_points(self.heading, max_cm):
                if self._is_blocked(self._key(px, py)):
                    return d
            return None

    def observe_range(self, distance_cm):
        """
        Integrates one forward ultrasonic reading. Returns a surprise kind
        ('new_obstacle' / 'obstacle_gone') when the reading contradicts what the
        model predicted, else None.
        """
        with self._lock:
            predicted = self.predict_range()
            hit = 0.0 < distance_cm < TRUSTED_RANGE_CM
            free_len = distance_cm - self.cell_cm / 2.0 if hit else TRUSTED_RANGE_CM * 0.75

            hit_key, seen_open_before = None, False
            if hit:
                rad = math.radians(self.heading)
                hit_key = self._key(self.x + distance_cm * math.cos(rad),
                                    self.y + distance_cm * math.sin(rad))
                prior = self.cells.get(hit_key)
                # Only surprising if we had evidence of open desk there (visited / seen free)
                seen_open_before = bool(prior and (prior["visits"] > 0 or prior["occ"] < 0.0))

            for d, px, py in self._ray_points(self.heading, max(0.0, free_len)):
                key = self._key(px, py)
                if key == hit_key:
                    continue
                c = self._cell(key)
                c["occ"] = max(-OCC_LIMIT, c["occ"] + OCC_FREE)

            if hit:
                # A fresh echo outweighs older "free" evidence — the newest reading wins
                c = self._cell(hit_key)
                c["occ"] = min(OCC_LIMIT, max(c["occ"], 0.0) + OCC_HIT)

            surprise = None
            if hit and distance_cm < 45.0 and (predicted is None or predicted > distance_cm + 15.0):
                if seen_open_before:
                    surprise = "new_obstacle"
            elif predicted is not None and predicted < 45.0 and (not hit or distance_cm > predicted + 20.0):
                surprise = "obstacle_gone"
                # Forget the stale obstacle at once so it can't re-trigger this surprise
                for d, px, py in self._ray_points(self.heading, predicted + self.cell_cm):
                    c = self._cell(self._key(px, py))
                    c["occ"] = min(c["occ"], 0.0)

            now = time.time()
            if surprise and now - self._last_surprise > SURPRISE_COOLDOWN_S:
                self._last_surprise = now
                text = ("Something is blocking your path straight ahead, where the desk used to be open."
                        if surprise == "new_obstacle"
                        else "The thing that used to block your path straight ahead is gone now.")
                self._add_event(surprise, text)
                return surprise
            return None

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #

    def distance_from_home(self):
        with self._lock:
            return math.hypot(self.x, self.y)

    def bearing_to_home(self):
        """Relative turn (deg) that would point IKRU back at home."""
        with self._lock:
            if math.hypot(self.x, self.y) < 1e-6:
                return 0.0
            return _norm_angle(math.degrees(math.atan2(-self.y, -self.x)) - self.heading)

    def point_ahead(self, distance_cm):
        """World position `distance_cm` straight in front of IKRU."""
        with self._lock:
            rad = math.radians(self.heading)
            return (self.x + distance_cm * math.cos(rad), self.y + distance_cm * math.sin(rad))

    def bearing_to(self, x, y):
        """Relative turn (deg) that would point IKRU at (x, y)."""
        with self._lock:
            return _norm_angle(math.degrees(math.atan2(y - self.y, x - self.x)) - self.heading)

    def distance_to(self, x, y):
        with self._lock:
            return math.hypot(x - self.x, y - self.y)

    def landmark_position(self, label):
        """Where IKRU last saw something matching `label` this session, or None."""
        with self._lock:
            lm = self._find_landmark(label)
            return tuple(lm["pos"]) if lm and lm.get("pos") else None

    def outside_leash(self, margin_cm=0.0):
        return self.distance_from_home() > self.leash_cm + margin_cm

    def choose_turn(self, step_cm, rng=random):
        """
        Picks a relative turn (deg) for the next short drive. Prefers unexplored,
        unblocked patches that stay inside the leash radius around home.
        """
        with self._lock:
            if self.outside_leash():
                return self.bearing_to_home()

            best_turn, best_score = 0.0, -1e9
            for rel in (0, 30, -30, 60, -60, 90, -90, 135, -135, 180):
                h = self.heading + rel
                rad = math.radians(h)
                ex = self.x + step_cm * 2 * math.cos(rad)
                ey = self.y + step_cm * 2 * math.sin(rad)

                score = 0.0
                end_r = math.hypot(ex, ey)
                if end_r > self.leash_cm:
                    score -= 4.0 + (end_r - self.leash_cm) * 0.3

                for d, px, py in self._ray_points(h, step_cm * 2.5):
                    key = self._key(px, py)
                    if self._is_blocked(key):
                        score -= 6.0 if d < step_cm * 1.5 else 2.0
                        break
                    if math.hypot(px, py) <= self.leash_cm:
                        c = self.cells.get(key)
                        score += 1.0 if (c is None or c["visits"] == 0) else -0.15 * min(c["visits"], 4)

                score -= abs(rel) / 180.0 * 0.8        # mild preference for gentle turns
                score += rng.uniform(0.0, 0.9)         # a little whimsy
                if score > best_score:
                    best_turn, best_score = float(rel), score
            return best_turn

    def explored_fraction(self):
        """Share of the leash disc IKRU has physically visited this session."""
        with self._lock:
            r_cells = int(self.leash_cm / self.cell_cm)
            total = visited = 0
            for i in range(-r_cells, r_cells + 1):
                for j in range(-r_cells, r_cells + 1):
                    if math.hypot(i, j) * self.cell_cm <= self.leash_cm:
                        total += 1
                        c = self.cells.get((i, j))
                        if c and c["visits"] > 0:
                            visited += 1
            return visited / total if total else 1.0

    # ------------------------------------------------------------------ #
    # Landmarks (camera)
    # ------------------------------------------------------------------ #

    def _find_landmark(self, label):
        for lm in self.landmarks:
            if labels_match(lm["label"], label):
                return lm
        return None

    def observe_objects(self, labels, scene=None):
        """
        Integrates object names the VLM reported for the current view.
        Returns {"new": [...], "familiar": [...], "again": [...], "missing": [...]}:
          new      - never seen before, ever
          familiar - known from a previous session, first sighting this session
          again    - already seen this session
          missing  - expected in view (seen here earlier this session) but absent
        """
        now = time.time()
        rad = math.radians(self.heading)
        result = {"new": [], "familiar": [], "again": [], "missing": []}
        with self._lock:
            guess = (self.x + OBJECT_GUESS_CM * math.cos(rad), self.y + OBJECT_GUESS_CM * math.sin(rad))
            seen = []
            for raw in labels or []:
                label = clean_label(raw)
                if not label or any(labels_match(label, s) for s in seen):
                    continue
                seen.append(label)
                lm = self._find_landmark(label)
                if lm is None:
                    self.landmarks.append({
                        "label": label, "times_seen": 1, "sessions": 1,
                        "first_seen": now, "last_seen": now, "pos": guess, "session_seen": True,
                    })
                    result["new"].append(label)
                    continue
                if not lm.get("session_seen"):
                    lm["sessions"] = lm.get("sessions", 0) + 1
                    lm["session_seen"] = True
                    result["familiar"].append(lm["label"])
                else:
                    result["again"].append(lm["label"])
                lm["times_seen"] = lm.get("times_seen", 0) + 1
                lm["last_seen"] = now
                lm["pos"] = guess

            for lm in self.landmarks:
                if not lm.get("session_seen") or not lm.get("pos") or now - lm["last_seen"] < 20.0:
                    continue
                if any(labels_match(lm["label"], s) for s in seen):
                    continue
                dx, dy = lm["pos"][0] - self.x, lm["pos"][1] - self.y
                rel = _norm_angle(math.degrees(math.atan2(dy, dx)) - self.heading)
                if abs(rel) <= EXPECT_VIEW_DEG and math.hypot(dx, dy) <= EXPECT_VIEW_CM:
                    result["missing"].append(lm["label"])

            # Remember WHERE (what it was next to) and in what scene, in words — coordinates
            # are meaningless next session but "next to the laptop" is not.
            for label in seen:
                lm = self._find_landmark(label)
                if lm is not None:
                    lm["near"] = [o for o in seen if o != label][:3]
                    if scene:
                        lm["scene"] = str(scene).strip()[:120]
            if seen or scene:
                self.sightings.append({"t": now, "scene": str(scene or "").strip()[:160], "objects": seen[:8]})

            if result["new"]:
                self._add_event("discovery", f"You discovered something new: {', '.join(result['new'])}.")
            if result["missing"]:
                self._add_event("missing", f"You expected to see {', '.join(result['missing'])} here, but it's gone.")
            if scene:
                self._add_event("sight", f"You saw: {str(scene).strip()[:140]}")
        self.save()
        return result

    # ------------------------------------------------------------------ #
    # Recall: "where did I last see X?" and "what did I see lately?"
    # ------------------------------------------------------------------ #

    def recall(self, label):
        """Last known sighting of an object (persisted across sessions), or None if never seen."""
        with self._lock:
            lm = self._find_landmark(clean_label(label))
            if lm is None or not lm.get("last_seen"):
                return None
            return {"label": lm["label"], "ago_s": max(0.0, time.time() - lm["last_seen"]),
                    "near": list(lm.get("near") or []), "scene": lm.get("scene", ""),
                    "times_seen": lm.get("times_seen", 1)}

    def recall_line(self, label):
        """One plain sentence about the last sighting of `label`, or None."""
        r = self.recall(label)
        if r is None:
            return None
        line = f"you last saw the {r['label']} {ago_phrase(r['ago_s'])}"
        if r["near"]:
            line += f", near the {' and the '.join(r['near'][:2])}"
        if r["scene"]:
            line += f" (the view then: {r['scene']})"
        return line

    def recent_sightings(self, max_age_s=3600.0, n=3):
        """Compact lines about the latest camera views, newest last."""
        now = time.time()
        with self._lock:
            items = [s for s in self.sightings if now - s["t"] <= max_age_s][-n:]
        lines = []
        for s in items:
            what = s["scene"] or ("saw " + ", ".join(s["objects"]))
            objs = f" [objects: {', '.join(s['objects'])}]" if s["objects"] and s["scene"] else ""
            lines.append(f"{ago_phrase(now - s['t'])}: {what}{objs}")
        return lines

    # ------------------------------------------------------------------ #
    # Events & summary
    # ------------------------------------------------------------------ #

    def _add_event(self, kind, text):
        self.events.append((time.time(), kind, text))

    def recent_events(self, max_age_s=180.0, kinds=None):
        now = time.time()
        with self._lock:
            return [(k, t) for ts, k, t in self.events
                    if now - ts <= max_age_s and (kinds is None or k in kinds)]

    def begin_excursion(self):
        with self._lock:
            self.session_excursions += 1
            self.lifetime_excursions += 1

    def summary(self):
        """Compact natural-language snapshot for the LLM prompt."""
        with self._lock:
            d = math.hypot(self.x, self.y)
            if d < 8:
                where = "You are at your home spot on the desk."
            else:
                where = (f"You are about {int(round(d / 5.0) * 5)} cm from your home spot, "
                         f"which is {describe_direction(self.bearing_to_home())}.")
            explored = self.explored_fraction()
            if explored < 0.2:
                explore = "Most of the desk around you is still unexplored."
            elif explored < 0.6:
                explore = "You have explored part of the desk around you."
            else:
                explore = "You have explored most of the desk around you — it's getting familiar."

            ahead = self.predict_range()
            ahead_txt = f" Something is roughly {int(ahead)} cm ahead of you." if ahead else ""

            known = sorted(self.landmarks, key=lambda lm: -lm.get("times_seen", 0))[:5]
            if known:
                parts = []
                for lm in known:
                    tag = "very familiar" if lm.get("times_seen", 0) >= 5 else (
                        "seen before" if lm.get("sessions", 1) > 1 else "new today")
                    parts.append(f"{lm['label']} ({tag})")
                things = " Things you know on this desk: " + ", ".join(parts) + "."
            else:
                things = " You haven't identified any objects yet."

            recent = [t for k, t in self.recent_events(120.0) if k != "sight"][-2:]
            recent_txt = (" Just now: " + " ".join(recent)) if recent else ""

            return f"[World Model: {where} {explore}{ahead_txt}{things}{recent_txt}]"

    # ------------------------------------------------------------------ #
    # Persistence (familiarity only — positions are meaningless next session)
    # ------------------------------------------------------------------ #

    def load(self):
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self.landmarks = [
                    {**lm, "pos": None, "session_seen": False}
                    for lm in data.get("landmarks", []) if lm.get("label")
                ]
                self.lifetime_excursions = int(data.get("lifetime_excursions", 0))
                self.sightings.clear()
                for s in data.get("sightings", [])[-12:]:
                    if isinstance(s, dict) and s.get("t"):
                        self.sightings.append({"t": float(s["t"]), "scene": str(s.get("scene", "")),
                                               "objects": list(s.get("objects", []))})
        except Exception as e:
            print(f"[WorldModel] Could not load {os.path.basename(self.persist_path)}: {e}")

    def save(self):
        if not self.persist_path:
            return
        try:
            with self._lock:
                data = {
                    "landmarks": [
                        {k: lm[k] for k in ("label", "times_seen", "sessions", "first_seen", "last_seen",
                                            "near", "scene") if k in lm}
                        for lm in sorted(self.landmarks, key=lambda lm: -lm.get("last_seen", 0))[:60]
                    ],
                    "sightings": list(self.sightings),
                    "lifetime_excursions": self.lifetime_excursions,
                }
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            tmp = self.persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.persist_path)
        except Exception as e:
            print(f"[WorldModel] Could not save: {e}")
