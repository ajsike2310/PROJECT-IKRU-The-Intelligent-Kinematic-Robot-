import time
import random
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import ollama

from ..chat.prompts import SYSTEM_PROMPT, AUTONOMOUS_ADDENDUM
from ..chat.parser import parse_llm_json, parse_segments
from .config import (
    DEFAULT_CONFIG, MIN_INTERVAL_S, MAX_INTERVAL_S, STARTUP_QUIET_S, VISION_SAMPLE_PROBABILITY,
    MAX_AUTONOMOUS_MOVE_S, FORWARD_SAFETY_DISTANCE_CM, SAFE_SEQUENCES, STARTLE_CM, SONAR_SETTLE_S,
    LOOK_AROUND_PROBABILITY, OBSERVE_WITH_CAMERA_PROBABILITY, THOUGHT_MAX_AGE_S, OBSERVATION_MAX_AGE_S,
    ATTENTION_HOLD_S, ECHO_GUARD_S, ENERGY_DRAIN_PER_S, ENERGY_RECHARGE_PER_S, ENERGY_TO_ROAM,
    ENERGY_TIRED, BORED_EXPLORED_FRACTION,
)
from .hints import (
    MODE_HINTS_WITH_VISION, MODE_HINTS_WITHOUT_VISION, ROAM_HINTS, SURPRISE_HINTS,
    TIRED_HINT, WIND_DOWN_HINTS,
)
from .world_model import WorldModel
from .locomotion import Locomotion
from .search import SearchTask, ObjectSearcher


class AutonomousBrain:
    """
    Background daemon that gives IKRU a life of its own when nobody is talking to it.

    Behaviours, in priority order:
      * SEARCH — on request ("find my mug") IKRU roams the desk; every obstacle
        the ultrasonic sensor finds is photographed and classified by the VLM.
        Not the target -> it says so, remembers the spot, turns away and carries on.
      * EXCURSIONS — IKRU roams the desk in short scoots, steered by a tiny
        WorldModel (dead-reckoned pose, ultrasonic occupancy grid, camera
        landmarks) that keeps it inside a leash around home and prefers
        unexplored spots. It looks around, sometimes checks the camera, notices
        surprises and speaks thoughts / random questions composed by the LLM on
        a background worker so the wheels keep moving while it thinks.
      * RESTING — IKRU recharges its energy and occasionally has a stationary
        spontaneous thought.

    Thoughts bypass the main ChatEngine window (so the conversation stays clean)
    but are noted into it, so if IKRU asks a question the user can answer it.
    The brain yields immediately when the user speaks (pause() / attention()).
    """

    def __init__(
        self,
        robot,
        memory=None,
        vision=None,
        vlm=None,
        idle_manager=None,
        proximity_monitor=None,
        audio_service=None,
        model="qwen2.5:3b",
        keep_alive="30m",
        min_interval=MIN_INTERVAL_S,
        max_interval=MAX_INTERVAL_S,
        vision_probability=VISION_SAMPLE_PROBABILITY,
        chat_engine=None,
        config=None,
        world_model=None,
        world_model_path=None,
    ):
        self.robot             = robot
        self.memory            = memory
        self.vision            = vision
        self.vlm               = vlm
        self.idle_manager      = idle_manager
        self.proximity_monitor = proximity_monitor
        self.audio_service     = audio_service
        self.chat_engine       = chat_engine
        self.model             = model
        self.keep_alive        = keep_alive
        self.min_interval      = min_interval
        self.max_interval      = max_interval
        self.vision_probability = vision_probability

        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.world = world_model or WorldModel(
            leash_cm=self.cfg["leash_cm"], persist_path=world_model_path,
        )
        self.loco = Locomotion(
            robot, self.world, self.cfg, proximity_monitor=proximity_monitor,
            should_yield=self._should_yield, on_sound=self._chirp_guard,
        )
        self.searcher = ObjectSearcher(
            self.loco, self.world, self.cfg, vision=vision, vlm=vlm,
            speak=self._say, should_yield=self._should_yield,
        )

        self.running = False
        self.paused  = False
        self._lock   = threading.Lock()
        self.thread  = None
        self._last_thought_time = 0.0

        # Set whenever the user needs the stage: cuts motion and speech short
        self._interrupt = threading.Event()
        self._hold_until = 0.0
        self._last_user_activity = time.time()
        self._vocal_until = 0.0
        self._vocalizing = False

        self.energy = 1.0
        self.state = "resting"
        self._recent_thoughts = deque(maxlen=6)
        self._last_vision_time = 0.0
        self._urgent_hint = None
        self._pending = None
        self._search = None
        self.last_search = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ikru-thought")

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            self.paused  = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        if not self.cfg["enabled"]:
            print("[Autonomous] Brain started — idle behaviours off (config), object search available.")
        else:
            roam = "roaming + " if self.cfg["roam_enabled"] else ""
            print(f"[Autonomous] Brain started — {roam}spontaneous thoughts enabled.")

    def stop(self):
        with self._lock:
            self.running = False
        self._interrupt.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.world.save()
        print("[Autonomous] Brain stopped.")

    def pause(self):
        """Suppress autonomous behaviour (call when user is speaking / IKRU is busy)."""
        with self._lock:
            self.paused = True
            self._last_user_activity = time.time()
        self._interrupt.set()

    def resume(self):
        """Re-enable autonomous behaviour after user interaction finishes."""
        with self._lock:
            self.paused = False
            self._last_user_activity = time.time()

    def attention(self, hold_s=ATTENTION_HOLD_S):
        """Someone started talking: stop rolling and listen for a few seconds."""
        with self._lock:
            self._hold_until = max(self._hold_until, time.time() + hold_s)
            self._last_user_activity = time.time()
        self._interrupt.set()

    def is_vocalizing(self):
        """True while IKRU is making its own sounds (so the mic can ignore them)."""
        return self._vocalizing or time.time() < self._vocal_until

    # ------------------------------------------------------------------ #
    # Object search API (called from the chat loop)
    # ------------------------------------------------------------------ #

    def start_search(self, target):
        """Queues a search for `target`; it runs as soon as the user's turn ends. False if impossible."""
        target = str(target or "").strip()
        if not target:
            return False
        if not self.searcher.can_search():
            print("[Search] Can't search without the camera + VLM.")
            return False
        task = SearchTask(target, self.cfg["search_timeout_s"])   # respects the same leash as roaming
        with self._lock:
            self._search = task
        print(f"[Search] Queued search for: {task.target}")
        return True

    def cancel_search(self):
        with self._lock:
            task, self._search = self._search, None
        if task:
            task.status = "cancelled"
            self.last_search = task
            self._interrupt.set()
            print(f"[Search] Cancelled search for: {task.target}")
        return task is not None

    def is_searching(self):
        with self._lock:
            return self._search is not None

    # ------------------------------------------------------------------ #

    def _is_running(self):
        with self._lock:
            return self.running

    def _should_yield(self):
        with self._lock:
            if not self.running or self.paused:
                return True
            held = time.time() < self._hold_until
        return held or not (self.robot and getattr(self.robot, "connected", False))

    def _wait(self, seconds):
        return self.loco.wait(seconds)

    # ------------------------------------------------------------------ #
    # Main Loop
    # ------------------------------------------------------------------ #

    def _loop(self):
        # Quiet grace period after startup so IKRU doesn't blurt during first setup.
        end = time.time() + STARTUP_QUIET_S
        while time.time() < end and not self.is_searching():
            if not self._is_running():
                return
            time.sleep(0.2)

        now = time.time()
        next_rest_thought = now + random.uniform(self.min_interval, self.max_interval)
        next_excursion = now + random.uniform(5.0, 15.0)
        last_tick = now

        while self._is_running():
            time.sleep(0.5)
            now = time.time()
            if self.state == "resting":
                self.energy = min(1.0, self.energy + (now - last_tick) * ENERGY_RECHARGE_PER_S)
            last_tick = now

            if self._should_yield():
                continue

            try:
                if self.is_searching():
                    self._run_search()
                    last_tick = time.time()
                    next_excursion = max(next_excursion, last_tick + random.uniform(*self.cfg["rest_s"]))
                    continue
                if not self.cfg["enabled"]:
                    continue

                quiet_for = now - self._last_user_activity
                if (self.cfg["roam_enabled"] and now >= next_excursion
                        and self.energy >= ENERGY_TO_ROAM
                        and quiet_for >= self.cfg["idle_before_roam_s"]):
                    self._excursion()
                    last_tick = time.time()
                    next_excursion = last_tick + random.uniform(*self.cfg["rest_s"])
                    next_rest_thought = max(next_rest_thought, last_tick + 30.0)
                elif now >= next_rest_thought:
                    self._act()
                    next_rest_thought = time.time() + random.uniform(self.min_interval, self.max_interval)
            except Exception as e:
                print(f"[Autonomous] Cycle error: {e}")
                self.loco.stop()

    # ------------------------------------------------------------------ #
    # Context Gathering
    # ------------------------------------------------------------------ #

    def _gather_vision_context(self):
        """Grab a JPEG frame and run VLM description with configured probability."""
        if not (self.vision and self.vlm):
            return None
        if random.random() >= self.vision_probability:
            return None
        try:
            jpeg = self.vision.buffer.get_jpeg_bytes()
            if not jpeg:
                return None
            desc = self.vlm.describe_scene(jpeg)
            if desc:
                print(f"[Autonomous] Vision snapshot: {desc}")
            return desc
        except Exception as e:
            print(f"[Autonomous] Vision context error: {e}")
            return None

    def _gather_proximity_context(self):
        if not self.proximity_monitor:
            return None
        try:
            return self.proximity_monitor.get_sensor_context()
        except Exception:
            return None

    def _gather_memory_context(self):
        """Recall recent thoughts / facts so autonomous mode has continuity."""
        if not self.memory:
            return None
        try:
            return self.memory.build_memory_context("recent thoughts and observations")
        except Exception:
            return None

    def _minutes_since_last(self):
        if self._last_thought_time == 0.0:
            return 0
        return max(0, int((time.time() - self._last_thought_time) / 60.0))

    # ------------------------------------------------------------------ #
    # Prompt Construction
    # ------------------------------------------------------------------ #

    def _pick_mode(self, has_vision):
        options = MODE_HINTS_WITH_VISION if has_vision else MODE_HINTS_WITHOUT_VISION
        return random.choice(options)

    def _pick_roam_hint(self):
        if self._urgent_hint:
            hint, self._urgent_hint = self._urgent_hint, None
            return hint
        if self.energy < ENERGY_TIRED + 0.15:
            return TIRED_HINT
        weights = [w for w, _, _ in ROAM_HINTS]
        _, key, text = random.choices(ROAM_HINTS, weights=weights, k=1)[0]
        return (key, text)

    def _build_trigger(self, vision_ctx, prox_ctx, memory_ctx, mode_hint, roaming=False):
        parts = []
        if memory_ctx:
            parts.append(memory_ctx)
        if vision_ctx:
            parts.append(f"[Camera Visual Observation: {vision_ctx.strip()}]")
        if prox_ctx:
            parts.append(prox_ctx.strip())
        try:
            parts.append(self.world.summary())
        except Exception:
            pass
        if self._recent_thoughts:
            parts.append(
                "[Your recent thoughts (do NOT repeat or paraphrase these):\n"
                + "\n".join(f"  - {t}" for t in self._recent_thoughts) + "]"
            )

        gap_min = self._minutes_since_last()
        gap_phrase = f"~{gap_min} minutes have passed" if gap_min > 0 else "some quiet time has passed"
        situation = (
            "You are roaming around the desk on your own right now — your wheels are driven "
            "automatically, so leave tools empty."
            if roaming else f"{gap_phrase} since your last thought."
        )

        parts.append(
            "[INTERNAL SIGNAL — AUTONOMOUS MODE]\n"
            f"No one is speaking to you right now. {situation}\n"
            f"Mode hint: {mode_hint[1]}\n"
            "Generate ONE brief spontaneous action in the standard JSON format."
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # LLM Call (ephemeral, bypasses main ChatEngine)
    # ------------------------------------------------------------------ #

    def _query_llm(self, trigger_text):
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT + "\n" + AUTONOMOUS_ADDENDUM},
                    {"role": "user",   "content": trigger_text},
                ],
                format="json",
                keep_alive=self.keep_alive,
            )
            raw = response["message"]["content"].strip()
            return parse_llm_json(raw)
        except Exception as e:
            print(f"[Autonomous] LLM query failed: {e}")
            return [], ""

    def _compose(self, mode_hint, vision_ctx=None, roaming=False, max_age=THOUGHT_MAX_AGE_S):
        """Builds context, asks the LLM, returns a thought dict (or None). Safe to run on the worker."""
        trigger = self._build_trigger(
            vision_ctx, self._gather_proximity_context(), self._gather_memory_context(),
            mode_hint, roaming=roaming,
        )
        tools, response_text = self._query_llm(trigger)
        if not response_text:
            print("[Autonomous] LLM returned nothing usable — skipping.")
            return None
        return self._make_thought(response_text, tools, max_age, mode_hint[0])

    @staticmethod
    def _make_thought(response_text, tools=None, max_age=THOUGHT_MAX_AGE_S, mode="scripted"):
        segments = parse_segments(response_text) or [("normal", response_text)]
        return {
            "tools": tools or [], "text": response_text, "segments": segments,
            "created": time.time(), "max_age": max_age, "mode": mode,
        }

    def _compose_observation(self, jpeg):
        """Worker job: camera -> objects -> world model diff -> a thought about it."""
        hint, scene = self._pick_roam_hint(), None
        result = None
        try:
            if hasattr(self.vlm, "list_objects"):
                result = self.vlm.list_objects(jpeg)
            else:
                desc = self.vlm.describe_scene(jpeg)
                result = {"scene": desc, "objects": []} if desc else None
        except Exception as e:
            print(f"[Autonomous] Vision observation error: {e}")

        if result:
            scene = result.get("scene")
            objects = result.get("objects") or []
            print(f"[Autonomous] Saw: {scene} | objects: {objects}")
            diff = self.world.observe_objects(objects, scene)
            if diff["new"]:
                hint = ("discovery", f"You just noticed something you have never seen before: {diff['new'][0]}. "
                                     "React with delight, or ask a curious question about it.")
            elif diff["missing"]:
                hint = ("missing", f"The {diff['missing'][0]} you saw around here earlier seems to be gone. "
                                   "Wonder aloud where it went.")
            elif diff["familiar"]:
                hint = ("familiar", f"You recognise the {diff['familiar'][0]} from before. "
                                    "Greet it like an old friend or share a thought about it.")
            else:
                hint = ("comment_on_sight", "Comment on something you see, or ask a curious question about it.")
        return self._compose(hint, vision_ctx=scene, roaming=True, max_age=OBSERVATION_MAX_AGE_S)

    # ------------------------------------------------------------------ #
    # Robot helpers
    # ------------------------------------------------------------------ #

    def _chirp_guard(self, seconds=ECHO_GUARD_S):
        self._vocal_until = max(self._vocal_until, time.time() + seconds)

    def _express(self, emotion):
        self.loco.express(emotion)

    def note_external_motion(self, action, duration, speed_pct=100):
        """
        Keeps the world model roughly in sync with moves IKRU makes on the user's
        request. Untimed moves (duration 0) make the pose unknown, so home resets.
        """
        action = str(action).lower()
        if action not in ("forward", "backward", "left", "right", "spin_left", "spin_right"):
            return
        if float(duration) <= 0:
            self.world.reset_home()
            print("[Autonomous] Untimed move — position unknown, treating this spot as home.")
            return
        scale = speed_pct / max(float(self.cfg["roam_speed_pct"]), 1.0)
        if action == "forward":
            self.world.apply_forward(duration * self.cfg["forward_cm_per_s"] * scale)
        elif action == "backward":
            self.world.apply_forward(-duration * self.cfg["forward_cm_per_s"] * scale)
        else:
            sign = 1 if action in ("left", "spin_left") else -1
            self.world.apply_turn(sign * duration * self.cfg["turn_deg_per_s"] * scale)

    # ------------------------------------------------------------------ #
    # Movement Safety (LLM-requested tools)
    # ------------------------------------------------------------------ #

    def _is_forward_safe(self):
        """Blocks forward motion if the proximity sensor reports something close."""
        if not self.proximity_monitor:
            return True
        try:
            dist = self.proximity_monitor.get_distance()
            return not (0 < dist < FORWARD_SAFETY_DISTANCE_CM)
        except Exception:
            return True

    def _execute_tool_safely(self, tool):
        action   = str(tool.get("action", "")).lower()
        try:
            duration = float(tool.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0.0

        if action == "play_sequence":
            seq_name = str(tool.get("sequence", tool.get("name", "curious_scan"))).lower()
            if seq_name not in SAFE_SEQUENCES:
                print(f"[Autonomous] Sequence '{seq_name}' not in safe list — skipping.")
                return
            print(f"[Autonomous] Executing safe sequence: {seq_name}")
            self._chirp_guard(4.0)
            try:
                self.robot.play_sequence(seq_name)
            except Exception as e:
                print(f"[Autonomous] Sequence error: {e}")
            return

        if action == "forward" and not self._is_forward_safe():
            print("[Autonomous] Forward blocked — obstacle too close.")
            return

        if action in ("forward", "backward", "left", "right"):
            capped = min(max(duration, 0.15), MAX_AUTONOMOUS_MOVE_S)
            method = getattr(self.robot, action, None)
            if method:
                print(f"[Autonomous] Movement: {action} ({capped:.2f}s)")
                try:
                    method(capped)
                    self.note_external_motion(action, capped)
                except Exception as e:
                    print(f"[Autonomous] Movement error: {e}")

        # 'stop' and unknown actions are ignored in autonomous mode — no need to
        # spontaneously halt something that wasn't already moving.

    # ------------------------------------------------------------------ #
    # Stage management & speech
    # ------------------------------------------------------------------ #

    def _take_stage(self):
        if self.idle_manager:
            self.idle_manager.notify_activity()
        if self.proximity_monitor:
            self.proximity_monitor.pause()

    def _release_stage(self):
        # If the user took over, the chat loop owns idle/proximity now and resumes them itself.
        with self._lock:
            if self.paused:
                return
        if self.idle_manager:
            self.idle_manager.notify_speech_done()
        if self.proximity_monitor:
            self.proximity_monitor.resume()

    def _deliver(self, thought, run_tools=True):
        """Speaks a composed thought. Returns False if the user cut in."""
        if not thought or self._should_yield():
            return False
        self.loco.stop()
        self._vocalizing = True
        try:
            self.robot.speak_segments(
                thought["segments"], audio_service=self.audio_service, interrupt_event=self._interrupt,
            )
        except Exception as e:
            print(f"[Autonomous] Speak error: {e}")
        finally:
            self._vocalizing = False
            self._chirp_guard()

        if self._interrupt.is_set():
            print("[Autonomous] User cut in — thought interrupted.")
            return False

        tools = thought["tools"] if run_tools else []
        for tool in tools:
            self._execute_tool_safely(tool)

        clean = " ".join(txt for _, txt in thought["segments"]).strip()
        print(f"[Autonomous Thought]: {clean}")
        self._recent_thoughts.append(clean)

        # Persist so future user turns can recall it
        if self.memory:
            try:
                self.memory.record_assistant_message(
                    f"[autonomous thought] {thought['text']}",
                    tools_used=tools if tools else None,
                )
            except Exception as e:
                print(f"[Autonomous] Memory record error: {e}")

        # Let the conversation know what IKRU just said (so answers to its questions make sense)
        if self.chat_engine and hasattr(self.chat_engine, "note_autonomous_utterance"):
            try:
                self.chat_engine.note_autonomous_utterance(thought["text"], tools)
            except Exception as e:
                print(f"[Autonomous] Chat note error: {e}")

        self._last_thought_time = time.time()
        return True

    def _say(self, response_text):
        """Speaks a scripted line (no LLM round-trip — keeps search snappy)."""
        return self._deliver(self._make_thought(response_text), run_tools=False)

    # ------------------------------------------------------------------ #
    # Resting: one stationary spontaneous thought
    # ------------------------------------------------------------------ #

    def _act(self):
        self._interrupt.clear()
        vision_ctx = self._gather_vision_context()
        mode = self._pick_mode(has_vision=bool(vision_ctx))
        print(f"[Autonomous] Cycle — mode: {mode[0]}")
        thought = self._compose(mode, vision_ctx=vision_ctx)
        if not thought:
            return

        # Abort if the user started interacting while we were thinking —
        # LLM calls can take several seconds; user takes priority.
        if self._should_yield():
            print("[Autonomous] User activity detected mid-thought — aborting cycle.")
            return

        self._take_stage()
        try:
            self._deliver(thought)
        finally:
            self._release_stage()

    # ------------------------------------------------------------------ #
    # Object search
    # ------------------------------------------------------------------ #

    def _run_search(self):
        with self._lock:
            task = self._search
        if task is None:
            return
        self._interrupt.clear()
        self.state = "searching"
        self._take_stage()
        try:
            self.loco.set_speed(self.cfg["roam_speed_pct"])
            self._express("focused")
            status = self.searcher.run(task)
            if status != "active":                 # finished; 'active' = paused, resumes later
                with self._lock:
                    if self._search is task:
                        self._search = None
                self.last_search = task
                if status == "found":
                    self._express("glee")
        finally:
            self.loco.stop()
            self.loco.set_speed(100)
            try:
                self.robot.look_front()
            except Exception:
                pass
            self.state = "resting"
            self.world.save()
            self._release_stage()

    # ------------------------------------------------------------------ #
    # Roaming: an excursion around the desk
    # ------------------------------------------------------------------ #

    def _submit(self, fn, *args):
        try:
            self._pending = self._executor.submit(fn, *args)
        except RuntimeError:
            self._pending = None   # executor shut down

    def _collect_pending(self):
        """Returns a finished, fresh thought (or None) and clears the slot when done."""
        fut = self._pending
        if fut is None or not fut.done():
            return None
        self._pending = None
        try:
            thought = fut.result()
        except Exception as e:
            print(f"[Autonomous] Thought worker error: {e}")
            return None
        if thought and time.time() - thought["created"] > thought["max_age"]:
            print("[Autonomous] Thought went stale — dropping it.")
            return None
        return thought

    def _roam_step(self):
        dist, surprise = self.loco.sense()
        if surprise:
            print(f"[Autonomous] World model surprise: {surprise}")
            self._express("surprised")
            self._urgent_hint = (surprise, SURPRISE_HINTS[surprise])

        # Something right in our face (hand?) — startle and turn away
        if 0.0 < dist < STARTLE_CM:
            print(f"[Autonomous] Startled by something at {dist:.0f} cm!")
            self.loco.stop()
            self._express("scared")
            self._chirp_guard()
            try:
                self.robot.gasp()
            except Exception:
                pass
            self.loco.turn(random.choice([120, -120]))
            self._wait(SONAR_SETTLE_S)
            return

        # Now and then: stop, look around, maybe use the camera
        if random.random() < LOOK_AROUND_PROBABILITY:
            self.loco.look_around()
            if (self._pending is None and self.vision and self.vlm
                    and time.time() - self._last_vision_time >= self.cfg["vision_min_gap_s"]
                    and random.random() < OBSERVE_WITH_CAMERA_PROBABILITY):
                jpeg = None
                try:
                    jpeg = self.vision.buffer.get_jpeg_bytes()
                except Exception:
                    pass
                if jpeg:
                    self._last_vision_time = time.time()
                    print("[Autonomous] Taking a closer look with the camera...")
                    self._submit(self._compose_observation, jpeg)
                    self._wait(random.uniform(1.0, 2.0))   # linger a moment, like it's studying
            return

        self.loco.explore_step()

    def _excursion(self):
        self._interrupt.clear()
        self.state = "roaming"
        self.world.begin_excursion()
        start = time.time()
        end = start + random.uniform(*self.cfg["excursion_s"])
        next_thought_at = start + random.uniform(6.0, 14.0)   # first musing soon after setting off
        reason = "time"
        print(f"[Autonomous] Setting off to explore (energy {self.energy:.2f}, "
              f"{self.world.distance_from_home():.0f} cm from home)")

        self._take_stage()
        last = start
        try:
            self.loco.set_speed(self.cfg["roam_speed_pct"])
            self._express(random.choice(["happy", "glee", "focused"]))

            while True:
                if self._should_yield():
                    reason = "user"
                    break
                if self.is_searching():
                    reason = "search"                 # a search request outranks idle roaming
                    break
                now = time.time()
                self.energy = max(0.0, self.energy - (now - last) * ENERGY_DRAIN_PER_S)
                last = now

                thought = self._collect_pending()
                if thought:
                    if not self._deliver(thought, run_tools=False):
                        reason = "user"
                        break
                    next_thought_at = time.time() + random.uniform(*self.cfg["thought_gap_s"])
                    continue
                if self._pending is None and next_thought_at == float("inf"):
                    # previous thought failed or went stale — try again later
                    next_thought_at = now + random.uniform(*self.cfg["thought_gap_s"])

                if now >= end:
                    break
                if self.energy < ENERGY_TIRED:
                    reason = "tired"
                    break
                if self.world.explored_fraction() >= BORED_EXPLORED_FRACTION and now - start > 30:
                    reason = "bored"
                    break

                if self._pending is None and (now >= next_thought_at or self._urgent_hint):
                    self._submit(self._compose, self._pick_roam_hint(), None, True)
                    next_thought_at = float("inf")

                self._roam_step()

            if reason not in ("user", "search"):
                self._wind_down(reason)
        finally:
            self.loco.stop()
            self.loco.set_speed(100)
            try:
                self.robot.look_front()
            except Exception:
                pass
            self._pending = None
            self.state = "resting"
            self.world.save()
            self._release_stage()
            print(f"[Autonomous] Excursion over ({reason}) — "
                  f"{self.world.distance_from_home():.0f} cm from home, energy {self.energy:.2f}, "
                  f"explored {self.world.explored_fraction():.0%} of the leash area.")

    def _wind_down(self, reason):
        """Head back home, deliver a last thought if one is ready, settle in."""
        closing = None
        if reason in WIND_DOWN_HINTS and self._pending is None:
            self._submit(self._compose, WIND_DOWN_HINTS[reason], None, True)
        self.loco.go_home()

        deadline = time.time() + 12.0
        while self._pending is not None and time.time() < deadline:
            if self._should_yield():
                return
            closing = self._collect_pending()
            if closing:
                break
            time.sleep(0.1)
        if closing:
            self._deliver(closing, run_tools=False)
        if reason == "tired" and not self._should_yield():
            self._express("sleepy")
