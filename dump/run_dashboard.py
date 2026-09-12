"""
IKRU Dashboard Launcher
=======================
Starts the IKRU Professional Web Dashboard and Diagnostic Hub.
Open http://localhost:5000 in your browser.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SOFTWARE_DIR = ROOT_DIR / "software"
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))

from ikru.ui.server import run_server

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    run_server(port)
