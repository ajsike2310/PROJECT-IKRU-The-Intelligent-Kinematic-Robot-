import json
import time
import random
import threading

import ollama

from ..chat.prompts import SYSTEM_PROMPT, AUTONOMOUS_ADDENDUM
from ..chat.parser import parse_llm_json, parse_segments


# ------------------------------------------------------------------ #
# Autonomous behaviour tuning
# ------------------------------------------------------------------ #

# Random gap between spontaneous thoughts (seconds).
# Kept fairly long so IKRU doesn't feel manic — real personality is quiet moments too.
MIN_INTERVAL_S = 60.0
MAX_INTERVAL_S = 180.0

# Delay before the very first autonomous thought after startup.
STARTUP_QUIET_S = 25.0

# Probability of grabbing a fresh vision frame + running the VLM this cycle.
# Vision calls are expensive, so we don't do it every time.
VISION_SAMPLE_PROBABILITY = 0.45

# Movement safety caps for autonomous mode.
# Forward motion is completely blocked if something is closer than this (cm).
MAX_AUTONOMOUS_MOVE_S = 0.6
FORWARD_SAFETY_DISTANCE_CM = 20.0

# Sequences safe to trigger autonomously (no aggressive motion).
SAFE_SEQUENCES = {"curious_scan", "confused_wiggle", "happy_dance", "celebrate", "disapproval_shake"}


# ------------------------------------------------------------------ #
# Mode hints — the LLM picks the actual thought, we just nudge the flavour
# ------------------------------------------------------------------ #

MODE_HINTS_WITH_VISION = [
    ("comment_on_sight",   "Comment naturally on something you see right now."),
    ("wonder_aloud",       "Ask a short curious question out loud about what you see."),
    ("small_observation",  "Make a small warm observation about the moment or your surroundings."),
    ("tiny_roam",          "Do a very small movement to look around, with a matching thought."),
]

MODE_HINTS_WITHOUT_VISION = [
    ("wonder_aloud",       "Ask a short curious rhetorical question out loud."),
    ("small_observation",  "Make a small observation about the quiet moment or the passage of time."),
    ("fleeting_feeling",   "Express a fleeting feeling — a sigh, a giggle, or a soft thought."),
    ("tiny_roam",          "Do a very small movement to explore your immediate surroundings."),
]


class AutonomousBrain:
    """
    Background daemon that generates spontaneous, LLM-driven behaviour when
    IKRU is idle. Every cycle it:
      1. Waits a random idle interval.
      2. Gathers live context: vision snapshot (sometimes), proximity, memory recall.
      3. Sends a one-shot autonomous prompt to the LLM (bypasses the main
         ChatEngine sliding window so real conversation stays uncluttered).
      4. Speaks the generated thought and executes a safety-capped movement.
      5. Records the thought to persistent memory (SQLite + Qdrant) so it can
         be semantically recalled later.

    The brain pauses cleanly during user turns and during proximity reflexes.
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
    ):
        self.robot             = robot
        self.memory            = memory
        self.vision            = vision
        self.vlm               = vlm
        self.idle_manager      = idle_manager
        self.proximity_monitor = proximity_monitor
        self.audio_service     = audio_service
        self.model             = model
        self.keep_alive        = keep_alive
        self.min_interval      = min_interval
        self.max_interval      = max_interval
        self.vision_probability = vision_probability

        self.running = False
        self.paused  = False
        self._lock   = threading.Lock()
        self.thread  = None
        self._last_thought_time = 0.0

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
        print("[Autonomous] Brain started — spontaneous thoughts enabled.")

    def stop(self):
        with self._lock:
            self.running = False
        print("[Autonomous] Brain stopped.")

    def pause(self):
        """Suppress autonomous thoughts (call when user is speaking / IKRU is busy)."""
        with self._lock:
            self.paused = True

    def resume(self):
        """Re-enable autonomous thoughts after user interaction finishes."""
        with self._lock:
            self.paused = False

    # ------------------------------------------------------------------ #
    # Main Loop
    # ------------------------------------------------------------------ #

    def _loop(self):
        # Quiet grace period after startup so IKRU doesn't blurt during first setup.
        time.sleep(STARTUP_QUIET_S)

        while True:
            wait_s = random.uniform(self.min_interval, self.max_interval)
            time.sleep(wait_s)

            with self._lock:
                if not self.running:
                    break
                paused = self.paused

            if paused:
                continue
            if not (self.robot and getattr(self.robot, "connected", False)):
                continue

            try:
                self._act()
            except Exception as e:
                print(f"[Autonomous] Cycle error: {e}")

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

    def _build_trigger(self, vision_ctx, prox_ctx, memory_ctx, mode_hint):
        parts = []
        if memory_ctx:
            parts.append(memory_ctx)
        if vision_ctx:
            parts.append(f"[Camera Visual Observation: {vision_ctx.strip()}]")
        if prox_ctx:
            parts.append(prox_ctx.strip())

        gap_min = self._minutes_since_last()
        gap_phrase = f"~{gap_min} minutes have passed" if gap_min > 0 else "some quiet time has passed"

        parts.append(
            "[INTERNAL SIGNAL — AUTONOMOUS MODE]\n"
            f"No one is speaking to you right now. {gap_phrase} since your last thought.\n"
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

    # ------------------------------------------------------------------ #
    # Movement Safety
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
        duration = float(tool.get("duration", 0))

        if action == "play_sequence":
            seq_name = str(tool.get("sequence", tool.get("name", "curious_scan"))).lower()
            if seq_name not in SAFE_SEQUENCES:
                print(f"[Autonomous] Sequence '{seq_name}' not in safe list — skipping.")
                return
            print(f"[Autonomous] Executing safe sequence: {seq_name}")
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
                except Exception as e:
                    print(f"[Autonomous] Movement error: {e}")

        # 'stop' and unknown actions are ignored in autonomous mode — no need to
        # spontaneously halt something that wasn't already moving.

    # ------------------------------------------------------------------ #
    # Full Autonomous Cycle
    # ------------------------------------------------------------------ #

    def _act(self):
        # 1. Context
        vision_ctx  = self._gather_vision_context()
        prox_ctx    = self._gather_proximity_context()
        memory_ctx  = self._gather_memory_context()

        # 2. Mode + trigger
        mode = self._pick_mode(has_vision=bool(vision_ctx))
        print(f"[Autonomous] Cycle — mode: {mode[0]}")
        trigger = self._build_trigger(vision_ctx, prox_ctx, memory_ctx, mode)

        # 3. LLM
        tools, response_text = self._query_llm(trigger)
        if not response_text:
            print("[Autonomous] LLM returned nothing usable — skipping.")
            return

        # Abort if the user started interacting while we were thinking —
        # LLM calls can take several seconds; user takes priority.
        with self._lock:
            if self.paused:
                print("[Autonomous] User activity detected mid-thought — aborting cycle.")
                return

        segments = parse_segments(response_text)
        if not segments:
            segments = [("normal", response_text)]

        # 4. Take the stage — pause other background systems
        if self.idle_manager:
            self.idle_manager.notify_activity()
        if self.proximity_monitor:
            self.proximity_monitor.pause()

        try:
            # 5. Speak
            try:
                self.robot.speak_segments(segments, audio_service=self.audio_service)
            except Exception as e:
                print(f"[Autonomous] Speak error: {e}")

            # 6. Execute safe tools
            for tool in tools:
                self._execute_tool_safely(tool)

            # 7. Log to console for visibility
            clean = " ".join(txt for _, txt in segments).strip()
            print(f"[Autonomous Thought]: {clean}")

            # 8. Persist to memory so future user turns can recall it
            if self.memory:
                try:
                    self.memory.record_assistant_message(
                        f"[autonomous thought] {response_text}",
                        tools_used=tools if tools else None,
                    )
                except Exception as e:
                    print(f"[Autonomous] Memory record error: {e}")

            self._last_thought_time = time.time()

        finally:
            # 9. Hand control back to background systems
            if self.idle_manager:
                self.idle_manager.notify_speech_done()
            if self.proximity_monitor:
                self.proximity_monitor.resume()
