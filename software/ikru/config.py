"""
PROJECT IKRU — Centralized System Configuration
===============================================
Central configuration module defining network defaults, hardware IPs,
LLM settings, audio service parameters, and streaming latency targets.
"""

import os
from pathlib import Path

# ── Project & Directory Paths ─────────────────────────────────
PACKAGE_DIR = Path(__file__).resolve().parent
SOFTWARE_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = SOFTWARE_DIR.parent

STATIC_DIR = PACKAGE_DIR / "ui" / "static"
VOICES_DIR = PACKAGE_DIR / "audio" / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)

# ── Server & Network Configuration ───────────────────────────
SERVER_HOST = os.getenv("IKRU_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("IKRU_PORT", "5000"))

# Network Probing & Hardware Candidates
DEFAULT_ROBOT_IP = os.getenv("IKRU_ROBOT_IP", "192.168.1.42")
ROBOT_WS_PORT = int(os.getenv("IKRU_ROBOT_PORT", "81"))
CANDIDATE_ROBOT_IPS = [
    DEFAULT_ROBOT_IP,
    "192.168.1.34",
    "192.168.4.2",
    "192.168.4.3",
    "192.168.4.4",
    "192.168.1.37",
    "192.168.1.40",
]

DEFAULT_CAM_IP = os.getenv("IKRU_CAM_IP", "192.168.4.1")
CAM_VIDEO_PORT = int(os.getenv("IKRU_CAM_VIDEO_PORT", "2222"))
CAM_DISCOVERY_PORT = int(os.getenv("IKRU_CAM_DISCOVERY_PORT", "2223"))

# ── LLM / Ollama Configuration ──────────────────────────────
OLLAMA_MODEL = os.getenv("IKRU_LLM_MODEL", "qwen2.5:1.5b")
OLLAMA_FALLBACK_MODEL = "qwen2.5:3b"
OLLAMA_HOST = os.getenv("IKRU_OLLAMA_HOST", "http://127.0.0.1:11434")

# ── Audio & TTS Configuration ───────────────────────────────
DEFAULT_TTS_ENGINE = os.getenv("IKRU_TTS_ENGINE", "edge")  # 'edge' or 'chatterbox'
AUDIO_HTTP_PORT = int(os.getenv("IKRU_AUDIO_PORT", "8000"))
AUDIO_SAMPLE_RATE = 44100

# ── Streaming Latency & Performance Targets ──────────────────
STREAM_SENTENCES = True
PUNCTUATION_DELIMITERS = {".", "!", "?", ";", "\n"}
PROBE_TIMEOUT_S = 0.4
PING_INTERVAL_S = 5
PING_TIMEOUT_S = 3
