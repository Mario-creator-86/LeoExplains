"""Leo Explains dashboard launcher (runs with pythonw, no console window).

Starts the dashboard server in the background if it is not already answering on port 8010,
then opens it in the default browser. Pass --nobrowser to only start the server (used at logon).
"""
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

URL = "http://127.0.0.1:8010/"
REPO = Path(__file__).resolve().parents[1]
# the interpreter this launcher runs with, console-less when a pythonw.exe sits next to it
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
if not PYTHONW.exists():
    PYTHONW = Path(sys.executable)


def running():
    try:
        with urllib.request.urlopen(URL, timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


if not running():
    subprocess.Popen([str(PYTHONW), "dashboard/server.py"], cwd=REPO,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(0.5)
        if running():
            break

if "--nobrowser" not in sys.argv:
    webbrowser.open(URL)
