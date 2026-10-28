"""Loads the pure-logic IKRU modules straight from their files.

Importing the `ikru` package pulls in the LLM, camera and robot stacks (and their
heavy dependencies), so the unit tests load only the modules they exercise.
"""
import importlib.util
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "software" / "ikru"


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(f"ikru_unit_{name}", SRC / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def parser():
    return _load("parser", "chat/parser.py")


@pytest.fixture(scope="session")
def protocol():
    return _load("protocol", "robot/protocol.py")


@pytest.fixture(scope="session")
def vad():
    return _load("vad", "mic/vad.py")


@pytest.fixture(scope="session")
def world_model():
    return _load("world_model", "autonomy/world_model.py")
