"""Windowless Parroty launcher used by the desktop shortcut.

The Flask server is imported as ``app.server`` so templates/static assets stay
rooted under ``app/``. On Windows the browser window is launched by
``parroty_window.ps1`` using the same dedicated-profile/maximize approach as
Stemmy, so an existing Chrome session cannot restore Parroty to an old windowed
size.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:5000"
HEALTH_URL = URL + "/engines"
LOG_PATH = ROOT / "parroty.log"
WINDOW_SCRIPT = ROOT / "parroty_window.ps1"

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["PARROTY_HIDDEN"] = "1"


def _redirect_output_to_log() -> None:
    """Give pythonw/Flask a real output stream and keep a useful error log."""
    if os.environ.get("PARROTY_TEST_MODE") == "1":
        return
    try:
        log_file = LOG_PATH.open("a", buffering=1, encoding="utf-8", errors="replace")
        sys.stdout = log_file
        sys.stderr = log_file
    except Exception:
        pass


def port_is_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5000), timeout=0.35):
            return True
    except OSError:
        return False


def server_is_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def wait_until_healthy(timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_healthy():
            return True
        time.sleep(0.2)
    return False


def log_failure() -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8", errors="replace") as file:
            file.write("\n[launcher error]\n")
            traceback.print_exc(file=file)
    except Exception:
        pass


def _find_powershell() -> str | None:
    if os.name != "nt":
        return None
    candidates = [
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "PowerShell"
        / "7"
        / "pwsh.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def _launch_app_window(fallback_open_window) -> None:
    """Open Parroty in a dedicated, explicitly maximized app window."""
    if os.environ.get("PARROTY_NO_BROWSER") == "1":
        return

    powershell = _find_powershell()
    if powershell and WINDOW_SCRIPT.is_file():
        command = [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOW_SCRIPT),
            "-Url",
            URL,
            "-Root",
            str(ROOT),
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            return
        except Exception:
            # Retain the existing browser fallback if PowerShell is unavailable
            # or blocked by a local policy.
            pass

    fallback_open_window(URL)


def _open_when_ready(fallback_open_window) -> None:
    if wait_until_healthy(30.0):
        _launch_app_window(fallback_open_window)
    else:
        try:
            with LOG_PATH.open("a", encoding="utf-8", errors="replace") as file:
                file.write("\n[launcher error]\nParroty did not become healthy within 30 seconds.\n")
        except Exception:
            pass


_redirect_output_to_log()

try:
    # Importing by its real package name is critical: Flask then resolves the
    # templates and static folders from ``app/`` instead of the launcher folder.
    from app import server

    if port_is_open():
        if wait_until_healthy(3.0):
            _launch_app_window(server._open_chrome)
        else:
            raise RuntimeError(
                "Port 5000 is occupied, but Parroty readiness check failed. "
                "Run stop.bat and try again."
            )
    else:
        server._disable_windows_quickedit()
        server._keep_full_speed()
        threading.Thread(
            target=_open_when_ready,
            args=(server._open_chrome,),
            daemon=True,
        ).start()
        server.app.run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
except Exception:
    log_failure()
    if os.environ.get("PARROTY_TEST_MODE") == "1":
        raise
