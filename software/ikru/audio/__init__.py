"""
===============================================================================
PROJECT IKRU — AUDIO & SONIC EMOTIONS PACKAGE
===============================================================================
Exposes SonicEmotionEngine for R2-D2 droid vocalizations, sentiment prosody,
and SonicClient for communication with ESP32-CAM (Head / Speaker).
===============================================================================
"""

from .engine import SonicEmotionEngine, DroidStep, SonicClient

__all__ = [
    "SonicEmotionEngine",
    "DroidStep",
    "SonicClient",
]
