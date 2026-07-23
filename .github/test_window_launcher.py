from __future__ import annotations

import os
import runpy
import socket
import subprocess
import sys
import types
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["PARROTY_TEST_MODE"] = "1"


def install_stub(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


install_stub(
    "app.epub_parser",
    parse_epub=lambda *args, **kwargs: None,
    Chapter=type("Chapter", (), {}),
)
install_stub(
    "app.document_parser",
    parse_document=lambda *args, **kwargs: None,
    SUPPORTED_EXTENSIONS={".txt", ".epub"},
)
install_stub(
    "app.tts",
    get_engine=lambda *args, **kwargs: None,
    ENGINE_CATALOG={},
)
install_stub(
    "app.assembler",
    combine_chapters=lambda *args, **kwargs: None,
    build_youtube_timestamps=lambda *args, **kwargs: None,
    build_video=lambda *args, **kwargs: None,
    ensure_ffmpeg=lambda: True,
    build_drive_chapter_page=lambda *args, **kwargs: None,
)
install_stub("app.subtitles", write_srt=lambda *args, **kwargs: None)


class DummySocket:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


captured: dict[str, object] = {}


def fake_create_connection(*args, **kwargs):
    return DummySocket()


def fake_urlopen(*args, **kwargs):
    return DummyResponse()


def fake_popen(command, **kwargs):
    captured["command"] = command
    captured["kwargs"] = kwargs
    return types.SimpleNamespace(pid=12345)


original_create_connection = socket.create_connection
original_urlopen = urllib.request.urlopen
original_popen = subprocess.Popen
socket.create_connection = fake_create_connection
urllib.request.urlopen = fake_urlopen
subprocess.Popen = fake_popen
try:
    runpy.run_path(str(ROOT / "launch_parroty.pyw"), run_name="__main__")
finally:
    socket.create_connection = original_create_connection
    urllib.request.urlopen = original_urlopen
    subprocess.Popen = original_popen

command = captured.get("command")
assert isinstance(command, list), "The launcher did not start the PowerShell app-window helper"
assert any(str(item).lower().endswith(("powershell.exe", "pwsh.exe")) for item in command)
assert "-File" in command
script_index = command.index("-File") + 1
assert Path(command[script_index]).name == "parroty_window.ps1"
assert "-Url" in command and "http://127.0.0.1:5000" in command
assert "-Root" in command and str(ROOT) in command

kwargs = captured.get("kwargs")
assert isinstance(kwargs, dict)
assert kwargs.get("cwd") == str(ROOT)
assert kwargs.get("stdin") is subprocess.DEVNULL
assert kwargs.get("stdout") is subprocess.DEVNULL
assert kwargs.get("stderr") is subprocess.DEVNULL

print("Window launcher test passed: dedicated PowerShell helper selected with hidden I/O")
