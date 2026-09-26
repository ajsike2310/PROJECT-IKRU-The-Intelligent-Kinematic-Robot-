"""
Tests for Laya-powered tool calling.

Offline (fake Laya):   python -m pytest tests/test_laya_router.py -v
Live (real model, downloads ~1.5 GB once):
    IKRU_LAYA_LIVE=1 python -m pytest tests/test_laya_router.py -v -s -k live
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "software"))

import pytest

from ikru.chat.tool_router import (
    LayaToolRouter, merge_tool_calls, extract_duration, extract_search_target,
)


class FakeLaya:
    """Answers Laya questions from a script: {"intent": (label, p), "direction": (choice, p), ...}."""
    def __init__(self, script):
        self.script = script
        self.states = []

    def predict(self, state, questions):
        self.states.append(state)
        answers = {}
        for name, q in questions.items():
            if q["type"] == "choice":
                choice, p = self.script.get(name, (list(q["criteria"])[0], 0.2))
                probs = {k: (p if k == choice else (1 - p) / (len(q["criteria"]) - 1)) for k in q["criteria"]}
                answers[name] = {"choice": choice, "probabilities": probs, "confidence": p - 0.2}
            else:
                answers[name] = {"noul": self.script.get(name, 0.05), "confidence": 0.9}
        return {"answers": answers}


def router(script, **kw):
    return LayaToolRouter(agent=FakeLaya(script), **kw)


# ------------------------------------------------------------------ #
# Argument extraction
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("text,want", [
    ("move forward for 3 seconds", 3.0), ("turn left 1.5 sec", 1.5), ("go back for five seconds", 5.0),
    ("spin for half a second", 0.5), ("forward 500 ms", 0.5), ("move forward", None), ("wait 99 seconds", 30.0),
])
def test_extract_duration(text, want):
    assert extract_duration(text) == want


@pytest.mark.parametrize("text,want", [
    ("can you find my coffee mug", "coffee mug"), ("find my keys please", "keys"),
    ("where are my glasses?", "glasses"), ("look for the red pen on the desk", "red pen"),
    ("search for a phone", "phone"), ("hello there", None),
])
def test_extract_search_target(text, want):
    assert extract_search_target(text) == want


# ------------------------------------------------------------------ #
# Decisions
# ------------------------------------------------------------------ #

def test_move_with_stated_duration():
    d = router({"intent": ("drive", 0.9), "direction": ("forward", 0.9)}).decide("move forward for 3 seconds")
    assert d.intent == "move" and d.tools == [{"action": "forward", "duration": 3.0}]
    assert "forward for 3 seconds" in d.context_line()


def test_stop_is_immediate():
    d = router({"intent": ("halt", 0.99)}).decide("stop!")
    assert d.immediate and d.tools == [{"action": "stop", "duration": 0}]


def test_cancel_search_is_immediate():
    d = router({"intent": ("give_up", 0.9)}).decide("never mind, stop looking")
    assert d.immediate and d.tools == [{"action": "cancel_search"}]


def test_search_extracts_target():
    d = router({"intent": ("find", 0.95)}).decide("can you find my coffee mug")
    assert d.tools == [{"action": "search_object", "target": "coffee mug"}] and not d.needs_target


def test_perform_maps_sequences_and_plain_actions():
    d = router({"intent": ("dance", 0.95), "performance": ("celebrate", 0.9)}).decide("woo we won!")
    assert d.tools == [{"action": "play_sequence", "sequence": "celebrate"}]
    d = router({"intent": ("dance", 0.95), "performance": ("dance", 0.9)}).decide("dance!")
    assert d.tools == [{"action": "dance", "duration": 0}]


def test_low_confidence_defers_to_llm():
    assert router({"intent": ("find", 0.47)}).decide("what's the capital of France?") is None


def test_unsure_follow_up_defers_to_llm():
    assert router({"intent": ("drive", 0.9), "direction": ("left", 0.4)}).decide("go that way") is None


def test_multi_step_defers_to_llm():
    r = router({"intent": ("drive", 0.9), "direction": ("forward", 0.9), "multi_step": 0.8})
    assert r.decide("go forward 5 seconds and then back 2 seconds") is None


def test_just_talking_never_strips_llm_tools_by_default():
    r = router({"intent": ("chat", 0.9)})
    assert r.decide("come here buddy") is None          # measured failure mode: confident "chat"
    llm = [{"action": "forward", "duration": 1}]
    assert merge_tool_calls(None, llm) == llm


def test_veto_mode_strips_hallucinated_tools():
    d = router({"intent": ("chat", 0.95)}, veto=True).decide("tell me a joke")
    assert d is not None and merge_tool_calls(d, [{"action": "dance"}]) == []


def test_state_is_only_the_users_words():
    # Measured on the real model: adding Ikru's last line skews every answer toward it
    fake = FakeLaya({"intent": ("halt", 0.99)})
    LayaToolRouter(agent=fake).decide("  stop!  ")
    assert fake.states == [{"user_said": "stop!"}]


def test_follow_up_questions_only_when_needed():
    fake = FakeLaya({"intent": ("halt", 0.99)})
    LayaToolRouter(agent=fake).decide("stop")
    assert len(fake.states) == 1                      # stop/find/chat: one call
    fake = FakeLaya({"intent": ("drive", 0.9), "direction": ("left", 0.9)})
    LayaToolRouter(agent=fake).decide("turn left")
    assert len(fake.states) == 2                      # drive: intent + direction


def test_not_ready_returns_none():
    assert LayaToolRouter().decide("stop") is None       # model not loaded -> LLM path


# ------------------------------------------------------------------ #
# Merging with the LLM's suggestion
# ------------------------------------------------------------------ #

def test_merge_fills_duration_from_llm_when_user_gave_none():
    d = router({"intent": ("drive", 0.9), "direction": ("forward", 0.9)}).decide("move forward")
    assert d.tools == [{"action": "forward", "duration": 1.0}]          # safe default
    assert merge_tool_calls(d, [{"action": "forward", "duration": 2}]) == [{"action": "forward", "duration": 2.0}]


def test_merge_fills_search_target_from_llm():
    d = router({"intent": ("find", 0.9)}).decide("can you help me out, it's gone missing")
    assert d.needs_target
    merged = merge_tool_calls(d, [{"action": "search_object", "target": "wallet"}])
    assert merged == [{"action": "search_object", "target": "wallet"}]
    assert merge_tool_calls(d, []) == []                                   # no target anywhere -> skip


def test_merge_laya_overrides_conflicting_llm_tool():
    d = router({"intent": ("drive", 0.9), "direction": ("left", 0.9)}).decide("turn left")
    assert merge_tool_calls(d, [{"action": "right", "duration": 1}]) == [{"action": "left", "duration": 0.5}]


def test_merge_skips_already_executed_actions():
    d = router({"intent": ("halt", 0.99)}).decide("stop")
    assert merge_tool_calls(d, [{"action": "stop"}], skip_actions={"stop"}) == []


# ------------------------------------------------------------------ #
# Live model
# ------------------------------------------------------------------ #

LIVE_CASES = [
    ("move forward for 3 seconds", "move"), ("what's the capital of France?", "none"), ("stop!", "stop"),
    ("can you find my coffee mug", "search"), ("never mind, stop looking for it", "cancel_search"),
    ("do a little happy dance", "perform"), ("turn left", "move"), ("i'm feeling sad today", "none"),
    ("come here buddy", "move"), ("where are my keys?", "search"), ("tell me a joke", "none"),
    ("halt", "stop"), ("sing me a song", "perform"), ("back up a little", "move"),
    ("freeze!", "stop"), ("please look for my phone", "search"), ("how are you doing?", "none"),
]


@pytest.mark.skipif(os.environ.get("IKRU_LAYA_LIVE") != "1", reason="set IKRU_LAYA_LIVE=1 to run against the real model")
def test_live_laya_never_takes_a_wrong_action():
    r = LayaToolRouter(device=os.environ.get("IKRU_LAYA_DEVICE", "cpu"))
    assert r.warm_up(), "laya failed to load"
    acted = correct = 0
    wrong = []
    t_total = 0.0
    for text, want in LIVE_CASES:
        t0 = time.time()
        d = r.decide(text)
        t_total += time.time() - t0
        if d is None:
            print(f"  defer   {text!r}")
            continue
        acted += 1
        ok = d.intent == want
        correct += ok
        print(f"  {'OK ' if ok else 'BAD'}     {text!r} -> {d}")
        if not ok:
            wrong.append((text, want, d.intent))
    print(f"\n  Laya acted on {acted}/{len(LIVE_CASES)}, correct {correct}/{acted}; "
          f"avg {t_total / len(LIVE_CASES) * 1000:.0f} ms")
    assert not wrong, f"Laya confidently took the wrong action: {wrong}"
    assert acted >= len(LIVE_CASES) // 3, "Laya should handle a useful share of commands itself"
