"""
PROJECT IKRU — Companion Studio Launcher
========================================
Double-click or run:
  python run_ui.py

Starts the lightweight Companion Studio web interface on port 5000 and
automatically opens it in your default web browser.
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SOFTWARE_DIR = ROOT_DIR / "software"
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))

from ikru.ui.server import run_studio_server

PORT = 5000
URL = f"http://localhost:{PORT}/"


def open_browser_delayed():
    time.sleep(1.0)
    print(f"[*] Opening IKRU Companion Studio in default browser: {URL}")
    webbrowser.open(URL)


def main():
    threading.Thread(target=open_browser_delayed, daemon=True).start()
    run_studio_server(port=PORT)


if __name__ == "__main__":
    main()
