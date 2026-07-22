"""Windowless Parroty launcher used by the desktop shortcut."""
from __future__ import annotations

import os
import runpy
import socket
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:5000"
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["PARROTY_HIDDEN"] = "1"


def port_is_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5000), timeout=0.35):
            return True
    except OSError:
        return False


def log_failure() -> None:
    try:
        with (ROOT / "parroty.log").open("a", encoding="utf-8", errors="replace") as f:
            f.write("\n[launcher error]\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


try:
    if port_is_open():
        from app.server import _open_chrome
        _open_chrome(URL)
    else:
        runpy.run_module("app.server", run_name="__main__")
except Exception:
    log_failure()
