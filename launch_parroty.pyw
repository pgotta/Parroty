"""Windowless Parroty launcher used by the desktop shortcut.

Import the Flask server as ``app.server`` instead of executing it as
``__main__``. Flask uses the import name to locate ``app/templates`` and
``app/static``; executing the module through ``runpy`` made Flask search from
the project root and caused ``TemplateNotFound: index.html`` even when the file
was present.
"""
from __future__ import annotations

import os
import socket
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


def _maximize_parroty_window(timeout: float = 12.0) -> None:
    """Explicitly maximize the Chrome/Edge app window on Windows.

    Chromium can ignore ``--start-maximized`` for app-mode windows, especially
    when an existing browser process handles the launch request. This waits for
    the Parroty window title to appear and then asks Windows to maximize it.
    """
    if os.name != "nt" or os.environ.get("PARROTY_TEST_MODE") == "1":
        return

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        sw_maximize = 3

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matched = []

            @enum_proc_type
            def enum_proc(hwnd, _lparam):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value.lower()
                    if "parroty" in title:
                        matched.append(hwnd)
                except Exception:
                    pass
                return True

            user32.EnumWindows(enum_proc, 0)
            if matched:
                for hwnd in matched:
                    user32.ShowWindow(hwnd, sw_maximize)
                    try:
                        user32.BringWindowToTop(hwnd)
                        user32.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
                return
            time.sleep(0.2)
    except Exception:
        pass


def _open_maximized(open_window) -> None:
    open_window(URL)
    _maximize_parroty_window()


def _open_when_ready(open_window) -> None:
    if os.environ.get("PARROTY_NO_BROWSER") == "1":
        return
    if wait_until_healthy(30.0):
        _open_maximized(open_window)
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
            _open_maximized(server._open_chrome)
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
