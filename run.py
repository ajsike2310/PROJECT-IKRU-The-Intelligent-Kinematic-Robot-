"""
PROJECT IKRU — Terminal Runner
==============================
Launches the IKRU Robotic Assistant in pure terminal mode.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SOFTWARE_DIR = os.path.join(ROOT_DIR, "software")
if SOFTWARE_DIR not in sys.path:
    sys.path.insert(0, SOFTWARE_DIR)

from ikru.main import main

if __name__ == "__main__":
    main()
