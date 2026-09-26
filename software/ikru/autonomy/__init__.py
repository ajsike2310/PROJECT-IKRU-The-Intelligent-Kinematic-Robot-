"""
IKRU autonomy: everything IKRU does on its own initiative.

  brain.py        AutonomousBrain — orchestrates resting thoughts, free roaming and object search
  world_model.py  WorldModel — dead-reckoned pose, ultrasonic occupancy grid, camera landmarks
  locomotion.py   Locomotion — safe motion primitives (scoot, turn, look around, go home)
  search.py       ObjectSearcher — roam + classify every obstacle with the VLM until found
  hints.py        LLM mode hints for spontaneous thoughts
  config.py       tuning defaults (overridable via config.json -> "autonomous")
"""
from .brain import AutonomousBrain
from .world_model import WorldModel
from .locomotion import Locomotion
from .search import ObjectSearcher, SearchTask
from .config import DEFAULT_CONFIG

__all__ = ["AutonomousBrain", "WorldModel", "Locomotion", "ObjectSearcher", "SearchTask", "DEFAULT_CONFIG"]
