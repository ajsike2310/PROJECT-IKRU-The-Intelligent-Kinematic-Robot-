# ------------------------------------------------------------------ #
# Focus hints. These never contain a thought: they only say WHICH real
# part of the live context IKRU should talk about. The words themselves
# come from the LLM, grounded in what the camera sees, the time of day,
# the human and IKRU's own state.
# ------------------------------------------------------------------ #

FOCUS_HINTS = {
    "sight": "Say something about one specific thing your camera shows right now - something you can actually see in the Camera Visual Observation.",
    "atmosphere": "Say something about the atmosphere right now - the time of day, how quiet or lively it is, the mood of the room - using only the Atmosphere facts.",
    "human": "Say something about your human - how long it has been since they spoke to you, what they said or were doing, or something you remember about them. Use only the facts given.",
    "self": "Say something about how you feel right now - your energy, where you are on the desk, what you just did. Use only the facts given.",
}

# Reactions to real events (sensor / world-model driven), not themes
SURPRISE_HINTS = {
    "new_obstacle":  "Something is suddenly in your way where the desk used to be open. React with surprise and curiosity — what could it be?",
    "obstacle_gone": "The thing that blocked your path earlier has vanished. React with puzzled curiosity.",
}

TIRED_HINT = ("getting_tired", "You're getting a bit tired from exploring. Say something about wanting a rest soon.")
WIND_DOWN_HINTS = {
    "tired": ("tired", "You explored until you're tired. Say you're heading back to your spot to rest."),
    "bored": ("bored", "You've explored almost everywhere nearby. Say something about knowing this desk by heart now."),
}
