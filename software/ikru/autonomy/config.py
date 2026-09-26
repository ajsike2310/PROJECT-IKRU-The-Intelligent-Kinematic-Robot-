# ------------------------------------------------------------------ #
# Autonomy tuning — everything in DEFAULT_CONFIG can be overridden from
# config.json -> "autonomous". The module-level constants are internal pacing.
# ------------------------------------------------------------------ #

DEFAULT_CONFIG = {
    "enabled": True,              # idle behaviours (roaming + spontaneous thoughts); search works regardless
    "roam_enabled": True,
    # Calibrate these with tests/robot/test_roam_calibration.py — dead reckoning
    # (and therefore the leash that keeps IKRU near home) depends on them.
    "roam_speed_pct": 55,         # motor speed while roaming (needs firmware SPEED: support)
    "forward_cm_per_s": 25.0,     # measured forward speed at roam_speed_pct
    "turn_deg_per_s": 180.0,      # measured spin rate at roam_speed_pct
    "leash_cm": 35.0,             # IKRU never plans to roam further than this from home
    "roam_stop_cm": 25.0,         # stop + pick another direction when something is this close
    "idle_before_roam_s": 30.0,   # quiet time after the last user interaction before wandering
    "excursion_s": [60.0, 150.0],
    "rest_s": [45.0, 120.0],
    "thought_gap_s": [20.0, 45.0],  # between spoken thoughts while roaming
    "vision_min_gap_s": 75.0,       # the VLM evicts the chat LLM from VRAM, so keep it rare
    # Object search
    "search_timeout_s": 180.0,      # give up after this long
    "search_min_confidence": 0.6,   # VLM confidence needed to call an obstacle "the one"
}

# Random gap between spontaneous *stationary* thoughts while resting (seconds).
# Kept fairly long so IKRU doesn't feel manic — real personality is quiet moments too.
MIN_INTERVAL_S = 60.0
MAX_INTERVAL_S = 180.0

# Delay before the very first autonomous behaviour after startup.
STARTUP_QUIET_S = 25.0

# Probability of grabbing a fresh vision frame + running the VLM for a resting thought.
VISION_SAMPLE_PROBABILITY = 0.45

# Movement safety caps for LLM-requested tools in autonomous mode.
# Forward motion is completely blocked if something is closer than this (cm).
MAX_AUTONOMOUS_MOVE_S = 0.6
FORWARD_SAFETY_DISTANCE_CM = 20.0

# Sequences safe to trigger autonomously (no aggressive motion).
SAFE_SEQUENCES = {"curious_scan", "confused_wiggle", "happy_dance", "celebrate", "disapproval_shake"}

STARTLE_CM = 10.0
BURST_S = (0.25, 0.5)           # short scoots with pauses — slower on average, sensor checked often
MAX_TURN_S = 1.2
SONAR_SETTLE_S = 0.45           # firmware median filter (5 x 60 ms) + proximity poll interval
CAMERA_SETTLE_S = 0.5           # let a fresh, non-blurred frame arrive after stopping
LOOK_AROUND_PROBABILITY = 0.25
OBSERVE_WITH_CAMERA_PROBABILITY = 0.6
THOUGHT_MAX_AGE_S = 25.0        # a thought that arrives later than this is stale — drop it
OBSERVATION_MAX_AGE_S = 45.0
ATTENTION_HOLD_S = 8.0          # how long IKRU stays still after hearing a voice
ECHO_GUARD_S = 1.2              # IKRU's own chirps shouldn't count as someone speaking

# Drives (0..1). Energy drains while roaming and recharges while resting.
ENERGY_DRAIN_PER_S = 1.0 / 200.0
ENERGY_RECHARGE_PER_S = 1.0 / 150.0
ENERGY_TO_ROAM = 0.5
ENERGY_TIRED = 0.2
BORED_EXPLORED_FRACTION = 0.9
