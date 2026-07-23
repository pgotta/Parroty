from __future__ import annotations

import os
import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["PARROTY_NO_BROWSER"] = "1"
os.environ["PARROTY_TEST_MODE"] = "1"

import flask
import app


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
install_stub(
    "app.subtitles",
    write_srt=lambda *args, **kwargs: None,
)

run_called = False
original_run = flask.Flask.run


def verified_run(self: flask.Flask, *args, **kwargs):
    global run_called
    run_called = True

    assert self.import_name == "app.server", self.import_name
    assert Path(self.root_path).resolve() == (ROOT / "app").resolve(), self.root_path

    with self.test_client() as client:
        readiness = client.get("/engines")
        assert readiness.status_code == 200, readiness.get_data(as_text=True)

        home = client.get("/")
        assert home.status_code == 200, home.get_data(as_text=True)
        assert b"Parroty" in home.data

        css = client.get("/static/style.css")
        assert css.status_code == 200

    print("Hidden launcher test passed: readiness=200, homepage=200, static=200")


flask.Flask.run = verified_run
try:
    runpy.run_path(str(ROOT / "launch_parroty.pyw"), run_name="__main__")
finally:
    flask.Flask.run = original_run

assert run_called, "The hidden launcher never reached Flask.run"
