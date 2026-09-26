"""
Offline tests for IKRU's roaming autonomous brain + world model.
No robot, camera, or Ollama needed:  python -m pytest tests/test_autonomous_roaming.py -v
"""
import os
import sys
import json
import time
import random
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "software"))

import pytest

from ikru.robot import RobotController
from ikru.autonomy import AutonomousBrain, WorldModel, SearchTask
from ikru.autonomy.world_model import labels_match


# ------------------------------------------------------------------ #
# Fakes
# ------------------------------------------------------------------ #

class FakeRobot:
    connected = True

    def __init__(self):
        self.log = []
        self._lock = threading.Lock()

    def _rec(self, item):
        with self._lock:
            self.log.append(item)

    def send(self, cmd):
        self._rec(cmd)

    def stop(self, duration=0):
        self._rec("STOP")

    def set_speed(self, pct):
        self._rec(f"SPEED:{pct}")

    def speak_segments(self, segments, audio_service=None, interrupt_event=None, **kw):
        self._rec(("SPEAK", tuple(segments)))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self._rec(name)

    def commands(self):
        with self._lock:
            return [c for c in self.log if isinstance(c, str)]


class FakeProximity:
    def __init__(self, distance=-1.0):
        self.distance = distance
        self.paused = False

    def get_distance(self):
        return self.distance

    def get_sensor_context(self):
        return None

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


class FakeVision:
    class buffer:
        @staticmethod
        def get_jpeg_bytes():
            return b"jpeg"


class FakeVLM:
    """Returns scripted verdicts for classify_target, one per call."""
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def classify_target(self, jpeg, target):
        self.calls.append(target)
        return self.verdicts.pop(0) if self.verdicts else {"what": "book", "match": False, "confidence": 0.9}


def make_brain(robot=None, prox=None, vision=None, vlm=None, **cfg):
    config = {
        "excursion_s": [2.5, 2.5], "rest_s": [100, 100], "thought_gap_s": [100, 100],
        "forward_cm_per_s": 40.0, "turn_deg_per_s": 360.0, **cfg,
    }
    brain = AutonomousBrain(
        robot=robot or FakeRobot(), proximity_monitor=prox or FakeProximity(),
        vision=vision, vlm=vlm, config=config, world_model=WorldModel(leash_cm=config.get("leash_cm", 35.0)),
    )
    brain._query_llm = lambda trigger: ([{"action": "forward", "duration": 5}],
                                        "[happy]Do clouds ever get tired of floating [giggle]?")
    brain.running = True
    return brain


# ------------------------------------------------------------------ #
# World model
# ------------------------------------------------------------------ #

def test_dead_reckoning_and_homing():
    w = WorldModel(leash_cm=35)
    w.apply_forward(20)
    w.apply_turn(90)
    w.apply_forward(10)
    assert w.x == pytest.approx(20, abs=1e-6)
    assert w.y == pytest.approx(10, abs=1e-6)
    assert w.heading == pytest.approx(90)
    # facing +y at (20, 10): home lies at atan2(-10, -20) = -153.4 deg -> relative +116.6 (left, behind)
    assert w.bearing_to_home() == pytest.approx(116.565, abs=0.01)
    w.apply_forward(40)   # now far outside the leash
    assert w.outside_leash()
    turn = w.choose_turn(step_cm=10)
    assert turn == pytest.approx(w.bearing_to_home())


def test_bearing_to_home_points_back():
    w = WorldModel()
    w.apply_forward(30)                    # facing away from home
    assert abs(w.bearing_to_home()) == pytest.approx(180, abs=1e-6)
    w.apply_turn(90)                       # facing left; home is to the left of that again
    assert w.bearing_to_home() == pytest.approx(90, abs=1e-6)


def test_choose_turn_avoids_known_obstacle():
    w = WorldModel(leash_cm=60)
    for _ in range(4):
        w.observe_range(12)                # wall right ahead
    turns = {w.choose_turn(step_cm=10) for _ in range(20)}
    assert 0.0 not in turns


def test_surprise_new_obstacle_then_gone():
    w = WorldModel(leash_cm=60)
    w.apply_forward(30)
    w.apply_turn(180)
    w.apply_forward(30)
    w.apply_turn(180)                      # back home, facing the patch we just drove over
    assert w.observe_range(20) == "new_obstacle"
    w._last_surprise = 0
    w.observe_range(20)
    w._last_surprise = 0
    assert w.observe_range(-1) == "obstacle_gone"
    w._last_surprise = 0
    assert w.observe_range(-1) is None     # stale obstacle was forgotten, no repeat surprise


def test_unknown_space_is_not_surprising():
    w = WorldModel()
    assert w.observe_range(20) is None


def test_landmarks_new_again_missing_and_familiar(tmp_path):
    path = str(tmp_path / "world.json")
    w = WorldModel(persist_path=path)
    r = w.observe_objects(["a coffee mug", "Laptop"], "A desk with a mug and a laptop.")
    assert r["new"] == ["coffee mug", "laptop"]
    r = w.observe_objects(["white mug"])
    assert r["again"] == ["coffee mug"]
    for lm in w.landmarks:
        lm["last_seen"] -= 60
    r = w.observe_objects([])
    assert set(r["missing"]) == {"coffee mug", "laptop"}
    assert "World Model" in w.summary()

    w2 = WorldModel(persist_path=path)
    assert {lm["label"] for lm in w2.landmarks} == {"coffee mug", "laptop"}
    assert w2.observe_objects(["mug"])["familiar"] == ["coffee mug"]
    saved = json.load(open(path, encoding="utf-8"))
    assert all("pos" not in lm for lm in saved["landmarks"])


def test_labels_match():
    assert labels_match("coffee mug", "white mug")
    assert not labels_match("mug", "laptop")
    assert not labels_match("a", "the")


# ------------------------------------------------------------------ #
# Brain
# ------------------------------------------------------------------ #

def test_excursion_roams_speaks_and_restores():
    random.seed(7)                                        # deterministic look-around / turn choices
    robot = FakeRobot()
    brain = make_brain(robot, excursion_s=[5.0, 5.0])
    brain._urgent_hint = ("roam_musing", "test")        # compose a thought right away
    t0 = time.time()
    brain._excursion()
    assert time.time() - t0 < 25

    cmds = robot.commands()
    assert cmds[0] == "SPEED:55"
    assert "FORWARD" in cmds, "IKRU should actually drive around"
    assert cmds.count("FORWARD") >= 2, "more than a single roam burst"
    assert cmds[-1] == "look_front" and "SPEED:100" in cmds[-3:]
    speaks = [c for c in robot.log if isinstance(c, tuple) and c[0] == "SPEAK"]
    assert speaks, "a thought should be spoken while roaming"
    # tools from the LLM are ignored while roaming (wheels are driven by the planner)
    assert brain.world.session_excursions == 1
    assert brain.state == "resting"
    assert brain.energy < 1.0
    assert "Do clouds ever get tired" in brain._recent_thoughts[0]


def test_roaming_never_drives_into_close_obstacle():
    robot = FakeRobot()
    brain = make_brain(robot, prox=FakeProximity(distance=18.0), excursion_s=[1.5, 1.5])
    brain._excursion()
    assert "FORWARD" not in robot.commands()


def test_startle_turns_away_from_hand():
    robot = FakeRobot()
    brain = make_brain(robot, prox=FakeProximity(distance=6.0), excursion_s=[1.0, 1.0])
    brain._excursion()
    cmds = robot.commands()
    assert "gasp" in cmds and "set_emotion" in cmds
    assert "FORWARD" not in cmds


def test_attention_stops_roaming_quickly():
    robot = FakeRobot()
    brain = make_brain(robot, excursion_s=[30, 30])
    th = threading.Thread(target=brain._excursion)
    th.start()
    time.sleep(1.0)
    brain.attention()
    th.join(timeout=3.0)
    assert not th.is_alive(), "excursion must end promptly when someone speaks"
    cmds = robot.commands()
    assert "SPEED:100" in cmds
    assert cmds.index("SPEED:100") > len(cmds) - 4
    # no motion after yielding
    tail = cmds[cmds.index("SPEED:100"):]
    assert "FORWARD" not in tail


def test_pause_yields_and_does_not_resume_background_systems():
    robot = FakeRobot()
    prox = FakeProximity()
    brain = make_brain(robot, prox=prox, excursion_s=[30, 30])
    th = threading.Thread(target=brain._excursion)
    th.start()
    time.sleep(0.8)
    brain.pause()
    prox.paused = True                     # the chat loop pauses proximity during its turn
    th.join(timeout=3.0)
    assert not th.is_alive()
    assert prox.paused, "brain must not re-enable reflexes while the user has the stage"


def test_resting_thought_still_works():
    robot = FakeRobot()
    brain = make_brain(robot)
    brain._query_llm = lambda trigger: ([{"action": "left", "duration": 0.2}], "[happy]What a calm afternoon.")
    brain._act()
    speaks = [c for c in robot.log if isinstance(c, tuple) and c[0] == "SPEAK"]
    assert speaks
    assert "left" in robot.commands()        # rest-mode tools still run (capped)
    assert brain.world.heading > 0           # ...and the world model tracked the turn


def test_note_external_motion():
    brain = make_brain()
    brain.note_external_motion("forward", 1.0)          # full speed: 40 * 100/55
    assert brain.world.x == pytest.approx(40 * 100 / 55, rel=1e-3)
    brain.note_external_motion("forward", 0)            # untimed -> pose unknown -> new home
    assert brain.world.distance_from_home() == 0


def test_chat_engine_note_autonomous_utterance():
    from ikru.chat import ChatEngine
    chat = ChatEngine(model="none")
    chat.note_autonomous_utterance("[happy]What are you building today?")
    assert chat.messages[-1]["role"] == "assistant"
    assert "building" in chat.messages[-1]["content"]
    for _ in range(20):
        chat.note_autonomous_utterance("[happy]x")
    assert len(chat.messages) <= 12 and chat.messages[0]["role"] == "system"


def test_get_distance_skips_obstacle_alert():
    class FakeWS:
        def __init__(self):
            self.replies = ['{"event":"obstacle_alert","distance_cm":9.0}', '{"type":"distance","cm":42.0}']

        def send(self, _):
            pass

        def settimeout(self, _):
            pass

        def recv(self):
            return self.replies.pop(0)

    robot = RobotController(connect_now=False, auto_reconnect=False)
    robot.ws, robot.connected = FakeWS(), True
    try:
        assert robot.get_distance(timeout=0.5) == 42.0
    finally:
        robot.close()


# ------------------------------------------------------------------ #
# Object search
# ------------------------------------------------------------------ #

def spoken(robot):
    return [" ".join(t for _, t in c[1]) for c in robot.log if isinstance(c, tuple) and c[0] == "SPEAK"]


def test_search_checks_obstacles_until_target_found():
    robot = FakeRobot()
    vlm = FakeVLM([
        {"what": "book", "match": False, "confidence": 0.95},
        {"what": "blue mug", "match": True, "confidence": 0.9},
    ])
    brain = make_brain(robot, prox=FakeProximity(distance=20.0), vision=FakeVision(), vlm=vlm)
    assert brain.start_search("the mug")
    brain._run_search()

    assert vlm.calls == ["mug", "mug"], "each new obstacle is sent to the VLM"
    lines = spoken(robot)
    assert len(lines) == 2
    assert "book" in lines[0], "says what the wrong obstacle was, then keeps going"
    assert "mug" in lines[1]
    assert brain.last_search.status == "found" and not brain.is_searching()
    assert brain.world.landmark_position("mug") is not None, "found object becomes a landmark"
    cmds = robot.commands()
    assert "SPEED:100" in cmds[-3:]


def test_search_low_confidence_is_not_a_match():
    robot = FakeRobot()
    vlm = FakeVLM([{"what": "cup", "match": True, "confidence": 0.3}])
    brain = make_brain(robot, prox=FakeProximity(distance=20.0), vision=FakeVision(), vlm=vlm,
                       search_timeout_s=2.0)
    brain.start_search("mug")
    brain._run_search()
    assert brain.last_search.status == "gave_up"
    assert len(vlm.calls) >= 1


def test_search_continues_journey_when_path_clear_then_gives_up():
    robot = FakeRobot()
    vlm = FakeVLM([])
    brain = make_brain(robot, prox=FakeProximity(distance=-1.0), vision=FakeVision(), vlm=vlm,
                       search_timeout_s=2.0)
    brain.start_search("keys")
    brain._run_search()
    assert "FORWARD" in robot.commands(), "keeps roaming while searching"
    assert vlm.calls == [], "no obstacle -> no VLM calls"
    assert brain.last_search.status == "gave_up"
    assert "keys" in spoken(robot)[-1]


def test_search_never_rechecks_same_obstacle():
    task = SearchTask("mug", 10)
    task.mark_checked(20.0, 0.0, "book")
    assert task.already_checked(25.0, 5.0)
    assert not task.already_checked(0.0, 30.0)


def test_search_needs_camera():
    brain = make_brain()
    assert brain.start_search("mug") is False


def test_search_runs_from_loop_even_with_idle_behaviours_disabled():
    robot = FakeRobot()
    vlm = FakeVLM([{"what": "mug", "match": True, "confidence": 0.99}])
    brain = make_brain(robot, prox=FakeProximity(distance=20.0), vision=FakeVision(), vlm=vlm, enabled=False)
    brain.running = False
    brain.start_search("mug")
    brain.start()
    try:
        deadline = time.time() + 10
        while brain.last_search is None and time.time() < deadline:
            time.sleep(0.1)
        assert brain.last_search and brain.last_search.status == "found"
    finally:
        brain.stop()


def test_cancel_search_interrupts():
    robot = FakeRobot()
    brain = make_brain(robot, prox=FakeProximity(distance=-1.0), vision=FakeVision(), vlm=FakeVLM([]),
                       search_timeout_s=60)
    brain.start_search("mug")
    th = threading.Thread(target=brain._run_search)
    th.start()
    time.sleep(1.0)
    brain.cancel_search()
    brain.pause()                     # the chat loop pauses the brain during the user's turn
    th.join(timeout=3.0)
    assert not th.is_alive()
    assert brain.last_search.status == "cancelled" and not brain.is_searching()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
