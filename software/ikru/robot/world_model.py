# Backward-compatible import path — the world model now lives in ikru.autonomy.
from ..autonomy.world_model import *  # noqa: F401,F403
from ..autonomy.world_model import WorldModel, labels_match, clean_label, describe_direction
