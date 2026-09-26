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
    ("random_question",    "Ask a random curious question out loud — about science, nature, humans, or the universe."),
    ("robot_life",         "Muse briefly about your life as a little robot living on this desk."),
]

# (weight, key, hint) — picked while rolling around the desk
ROAM_HINTS = [
    (3, "roam_musing",     "You are rolling around exploring the desk on your own. Share a short, lively musing about your little adventure."),
    (3, "random_question", "Ask a random curious question out loud — playful, philosophical, or scientific (about the world, humans, nature, space, or robots)."),
    (2, "robot_life",      "Muse about your life as a tiny robot exploring a big desk."),
    (2, "world_wonder",    "Wonder aloud about the part of the desk you are exploring, using what your World Model says."),
    (1, "wonder_user",     "Wonder aloud about your human — what they might be doing, or something you remember about them."),
    (1, "ask_user",        "Ask your human one short friendly question (what they're up to, their favourite something, how their day is going)."),
]

SURPRISE_HINTS = {
    "new_obstacle":  "Something is suddenly in your way where the desk used to be open. React with surprise and curiosity — what could it be?",
    "obstacle_gone": "The thing that blocked your path earlier has vanished. React with puzzled curiosity.",
}

TIRED_HINT = ("getting_tired", "You're getting a bit tired from exploring. Say something about wanting a rest soon.")
WIND_DOWN_HINTS = {
    "tired": ("tired", "You explored until you're tired. Say you're heading back to your spot to rest."),
    "bored": ("bored", "You've explored almost everywhere nearby. Say something about knowing this desk by heart now."),
}
