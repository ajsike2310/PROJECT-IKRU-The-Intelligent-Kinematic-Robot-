import re
import threading
import time


# ------------------------------------------------------------------ #
# Laya-powered tool calling.
#
# Laya (https://huggingface.co/convaiinnovations/laya) is a Jev-compatible
# "System 1" decision model: it does not generate text, it answers typed
# questions (choice / score / noul) about a state with calibrated
# probabilities in a single fast forward pass.
#
# IKRU uses it as the *decider* for physical actions:
#   - Laya picks the action (hierarchically: a small intent question, then a
#     small follow-up — Laya degrades on large option lists).
#   - Arguments come from the user's own words (durations, search target),
#     falling back to what the chat LLM suggested.
#   - The chat LLM still writes the spoken reply, told which action was chosen.
#   - Low confidence / multi-step requests / Laya unavailable -> the LLM's own
#     tool calls are used, exactly as before.
#
# Question design was measured against the real model (see tests/test_laya_router.py):
# short labels in one choice question beat long descriptions (which skewed
# everything toward "search") and per-intent yes/no questions (same accuracy,
# ~3x slower). Out of the box it gets ~70% of IKRU commands right; its misses
# are either low-confidence (-> LLM fallback) or a confident "just talking",
# which is why Laya's "no action" never overrides a tool the LLM chose.
# ------------------------------------------------------------------ #

# Laya label -> (IKRU intent, short description)
INTENT_LABELS = {
    "chat":    ("none",          "no command, just talking"),
    "drive":   ("move",          "drive or turn"),
    "halt":    ("stop",          "stop"),
    "dance":   ("perform",       "dance or sing"),
    "find":    ("search",        "find an object"),
    "give_up": ("cancel_search", "stop searching"),
}
INTENTS = {intent for intent, _ in INTENT_LABELS.values()}

DIRECTIONS = {
    "forward":  "forward or closer",
    "backward": "backward or away",
    "left":     "turn left",
    "right":    "turn right",
}

PERFORMANCES = {
    "dance":             "dance",
    "sing":              "sing",
    "celebrate":         "celebrate",
    "victory_twirl":     "victory spin",
    "happy_dance":       "happy wiggle",
    "confused_wiggle":   "act confused",
    "scared_retreat":    "act scared",
    "curious_scan":      "look around",
    "disapproval_shake": "shake head no",
}

SEQUENCES = {"celebrate", "victory_twirl", "happy_dance", "confused_wiggle",
             "scared_retreat", "curious_scan", "disapproval_shake"}

# Physical actions that should happen *now*, before the LLM has finished thinking
IMMEDIATE_INTENTS = {"stop", "cancel_search"}

DEFAULT_DURATIONS = {"forward": 1.0, "backward": 1.0, "left": 0.5, "right": 0.5}

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half a": 0.5, "a couple of": 2, "couple of": 2,
}
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?|half a|a couple of|couple of|an?|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(?:-\s*)?(s|sec|secs|second|seconds|ms|millisecond|milliseconds)\b",
    re.IGNORECASE,
)
_SEARCH_RE = re.compile(
    r"\b(?:find|look(?:ing)? for|search(?:ing)? for|locate|where(?:'s| is| are)|hunt for|spot)\s+"
    r"(?:(?:my|the|a|an|our|your|his|her|their|some)\s+)*([a-z][a-z0-9 \-]{1,40}?)"
    r"(?:\s+(?:please|for me|on the desk|on the table|around here|nearby|now|again))*\s*[?.!]*$",
    re.IGNORECASE,
)


def extract_duration(text):
    """'move forward for 3 seconds' -> 3.0 ; 'half a second' -> 0.5 ; None if not stated."""
    m = _DURATION_RE.search(text or "")
    if not m:
        return None
    raw, unit = m.group(1).lower(), m.group(2).lower()
    value = _NUMBER_WORDS.get(raw)
    if value is None:
        try:
            value = float(raw)
        except ValueError:
            return None
    if unit.startswith("m"):
        value /= 1000.0
    return max(0.0, min(float(value), 30.0))


def extract_search_target(text):
    """'can you find my coffee mug please' -> 'coffee mug' ; None if not stated."""
    m = _SEARCH_RE.search((text or "").strip())
    if not m:
        return None
    target = re.sub(r"\s+", " ", m.group(1)).strip(" -")
    return target or None


class ToolDecision:
    def __init__(self, intent, confidence, tools, action_text=None, needs_target=False,
                 needs_duration_from_llm=False, immediate=False, latency_ms=0.0, raw=None):
        self.intent = intent
        self.confidence = confidence
        self.tools = tools
        self.action_text = action_text          # natural description for the LLM ("move forward for 3 seconds")
        self.needs_target = needs_target        # search target must come from the LLM
        self.needs_duration_from_llm = needs_duration_from_llm
        self.immediate = immediate
        self.latency_ms = latency_ms
        self.raw = raw

    def context_line(self):
        """Tells the chat LLM what the body is about to do, so the words match the action."""
        if self.intent == "none":
            return None
        if not self.action_text:
            return None
        return (f"[Action System: your body is performing this action: {self.action_text}. "
                "Mention it naturally in your reply; the tools field is handled for you.]")

    def __repr__(self):
        return f"ToolDecision({self.intent}, conf={self.confidence:.2f}, tools={self.tools}, {self.latency_ms:.0f}ms)"


class LayaToolRouter:
    """Decides IKRU's tool calls with the Laya decision model (falls back to the LLM when unsure)."""

    def __init__(self, model_id="convaiinnovations/laya", device="cpu", min_confidence=0.8,
                 multi_step_threshold=0.5, veto=False, agent=None):
        self.model_id = model_id
        self.device = device
        self.min_confidence = float(min_confidence)
        # veto=True lets a confident "just talking" strip the LLM's tools (anti-hallucination).
        # Off by default: measured misses were confident "just talking" on real commands.
        self.veto = bool(veto)
        self.multi_step_threshold = float(multi_step_threshold)
        self._agent = agent
        self._error = None
        self._ready = threading.Event()
        if agent is not None:
            self._ready.set()

    # ------------------------------------------------------------------ #

    def warm_up(self):
        """Loads the model (downloads it the first time). Safe to run in a background thread."""
        if self._ready.is_set():
            return True
        try:
            import laya
            t0 = time.time()
            self._agent = laya.load(self.model_id, device=self.device)
            # One throwaway prediction so the first real turn doesn't pay for lazy init
            self._agent.predict("hello", self._questions("intent"))
            print(f"[Laya] {self.model_id} ready on {self.device} ({time.time() - t0:.1f}s).")
            self._ready.set()
            return True
        except ImportError:
            self._error = "laya is not installed (pip install laya)"
        except Exception as e:
            self._error = str(e)
        print(f"[Laya] Unavailable — using LLM tool calls instead ({self._error}).")
        return False

    @property
    def available(self):
        return self._ready.is_set()

    # ------------------------------------------------------------------ #

    # Staged questions: stage 1 is asked every turn, follow-ups only when needed.
    # Each extra question costs real time on CPU, and most turns are chat/stop/find.
    @staticmethod
    def _questions(*names):
        all_q = {
            "intent": {"type": "choice",
                       "instructions": "Which command is the user giving the robot?",
                       "criteria": {label: desc for label, (_, desc) in INTENT_LABELS.items()}},
            "direction": {"type": "choice", "instructions": "Which way should the robot move?",
                          "criteria": DIRECTIONS},
            "performance": {"type": "choice", "instructions": "Which performance does the user want?",
                            "criteria": PERFORMANCES},
            "multi_step": {"type": "noul",
                           "instructions": "Does the user ask for two or more different movements in a row?",
                           "criteria": {"false": "one action or none", "true": "several actions in sequence"}},
        }
        return {n: all_q[n] for n in (names or all_q)}

    FOLLOW_UPS = {"move": ("direction", "multi_step"), "perform": ("performance", "multi_step")}

    @staticmethod
    def _prob(ans):
        """Probability Laya gave its chosen option."""
        return float((ans.get("probabilities") or {}).get(ans.get("choice"), ans.get("confidence", 0.0)) or 0.0)

    @staticmethod
    def _answers(result):
        return result.get("answers", {}) if isinstance(result, dict) else getattr(result, "answers", {})

    def decide(self, user_text):
        """Returns a ToolDecision, or None to let the LLM's own tool calls stand."""
        if not self.available or not (user_text or "").strip():
            return None

        # Only the user's words. Measured on the real model: the dict form is ~30% slower
        # than plain text but noticeably more confident (acted on 9/17 vs 6/17 test
        # commands, all correct either way) — main.py runs Laya in parallel with the LLM,
        # so accuracy wins. Adding what Ikru last said ("Want me to dance?") skewed every
        # answer toward that offer, so replies like "yes, do it!" are left to the LLM.
        state = {"user_said": user_text.strip()}

        t0 = time.time()
        try:
            answers = self._answers(self._agent.predict(state, self._questions("intent")))
        except Exception as e:
            print(f"[Laya] Prediction failed ({e}) — using LLM tool calls.")
            return None

        intent_ans = answers.get("intent", {})
        label = intent_ans.get("choice")
        intent = INTENT_LABELS.get(label, (None, None))[0]
        # Probability of the chosen option (Laya's "confidence" field is a separate, stricter margin score)
        conf = float((intent_ans.get("probabilities") or {}).get(label, intent_ans.get("confidence", 0.0)) or 0.0)
        if intent not in INTENTS or conf < self.min_confidence:
            print(f"[Laya] Unsure ({intent}, {conf:.2f}) — deferring to the LLM's tool calls.")
            return None

        if intent in self.FOLLOW_UPS:
            try:
                answers.update(self._answers(self._agent.predict(state, self._questions(*self.FOLLOW_UPS[intent]))))
            except Exception as e:
                print(f"[Laya] Follow-up failed ({e}) — using LLM tool calls.")
                return None
        latency = (time.time() - t0) * 1000.0

        multi = float(answers.get("multi_step", {}).get("noul", 0.0) or 0.0)
        if intent in ("move", "perform") and multi >= self.multi_step_threshold:
            print(f"[Laya] Multi-step request (p={multi:.2f}) — deferring to the LLM's tool plan.")
            return None

        d = dict(intent=intent, confidence=conf, latency_ms=latency, raw=answers)

        if intent == "none":
            return ToolDecision(tools=[], **d) if self.veto else None

        if intent == "stop":
            return ToolDecision(tools=[{"action": "stop", "duration": 0}], action_text="stop moving",
                                immediate=True, **d)

        if intent == "cancel_search":
            return ToolDecision(tools=[{"action": "cancel_search"}], action_text="stop searching",
                                immediate=True, **d)

        if intent == "move":
            dir_ans = answers.get("direction", {})
            direction = dir_ans.get("choice")
            if direction not in DIRECTIONS or self._prob(dir_ans) < self.min_confidence:
                print(f"[Laya] Unsure of direction ({direction}, {self._prob(dir_ans):.2f}) - deferring to the LLM.")
                return None
            duration = extract_duration(user_text)
            text = f"move {direction}" + (f" for {duration:g} seconds" if duration else "")
            return ToolDecision(
                tools=[{"action": direction, "duration": duration if duration is not None
                        else DEFAULT_DURATIONS[direction]}],
                action_text=text, needs_duration_from_llm=duration is None, **d)

        if intent == "perform":
            perf_ans = answers.get("performance", {})
            perf = perf_ans.get("choice")
            if perf not in PERFORMANCES or self._prob(perf_ans) < self.min_confidence:
                print(f"[Laya] Unsure of performance ({perf}, {self._prob(perf_ans):.2f}) - deferring to the LLM.")
                return None
            if perf in SEQUENCES:
                tool = {"action": "play_sequence", "sequence": perf}
            else:
                tool = {"action": perf, "duration": 0}
            return ToolDecision(tools=[tool], action_text=f"{perf.replace('_', ' ')}", **d)

        if intent == "search":
            target = extract_search_target(user_text)
            return ToolDecision(
                tools=[{"action": "search_object", "target": target}],
                action_text=f"start searching for the {target}" if target else "start searching for the object",
                needs_target=target is None, **d)

        return None


def merge_tool_calls(decision, llm_tools, skip_actions=()):
    """
    Final tool list for a turn: Laya's decision when it has one, with missing
    arguments filled from the LLM's suggestion; otherwise the LLM's tools.
    """
    llm_tools = list(llm_tools or [])
    if decision is None:
        tools = llm_tools
    else:
        tools = []
        for tool in decision.tools:
            tool = dict(tool)
            action = tool.get("action")
            twin = next((t for t in llm_tools if str(t.get("action", "")).lower() == action), None)
            if action == "search_object" and not tool.get("target"):
                llm_search = next((t for t in llm_tools if str(t.get("action", "")).lower()
                                   in ("search_object", "find_object", "search")), None)
                tool["target"] = (llm_search or {}).get("target") or (llm_search or {}).get("object")
                if not tool["target"]:
                    print("[Laya] Search requested but no object name found — skipping.")
                    continue
            if decision.needs_duration_from_llm and twin is not None:
                try:
                    llm_dur = float(twin.get("duration", 0))
                    if llm_dur > 0:
                        tool["duration"] = llm_dur
                except (TypeError, ValueError):
                    pass
            tools.append(tool)
    return [t for t in tools if str(t.get("action", "")).lower() not in skip_actions]
