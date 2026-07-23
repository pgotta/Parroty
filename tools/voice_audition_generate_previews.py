from __future__ import annotations

import html
import json
import os
import sys
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REFS = HERE / "references"
OUTPUTS = HERE / "outputs"
LOG_PATH = HERE / "voice_review.log"
PASSAGE = (
    "At first light, the old house stood quietly above the river. "
    "Mara opened the weathered book and read the first line aloud. "
    "Beyond the window, rain moved through the trees, soft and steady, "
    "while the fire settled into a warm glow."
)


def build_review_page(candidates: list[dict]) -> Path:
    cards: list[str] = []
    for candidate in candidates:
        order = int(candidate["order"])
        generated_name = f"{order:02d}_{candidate['slug']}.wav"
        generated_path = OUTPUTS / generated_name
        reference_src = f"references/{candidate['filename']}"
        if generated_path.exists():
            generated_html = (
                f'<audio controls preload="metadata" '
                f'src="outputs/{generated_name}"></audio>'
            )
        else:
            generated_html = (
                '<div class="pending">This preview was not generated. '
                'Check voice_review.log.</div>'
            )

        cards.append(
            '<article class="card">'
            f'<div class="number">{order:02d}</div>'
            '<div class="content">'
            f'<h2>{html.escape(candidate["label"])}</h2>'
            f'<p class="meta">Anonymous VCTK {html.escape(candidate["speaker"])} · '
            f'{candidate["age"]} · {html.escape(candidate["accent"])} · '
            f'{html.escape(candidate["region"])}</p>'
            f'<p>{html.escape(candidate["description"])}</p>'
            '<div class="players">'
            '<label>Reference voice</label>'
            f'<audio controls preload="metadata" src="{reference_src}"></audio>'
            '<label>Parroty Chatterbox preview</label>'
            f'{generated_html}'
            '</div></div></article>'
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parroty Voice Auditions</title>
<style>
:root {{ color-scheme:dark; --bg:#15130f; --panel:#211d17; --line:#4b4032; --text:#f5eee3; --muted:#baa995; --accent:#d59a72; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Segoe UI,Arial,sans-serif; background:radial-gradient(circle at top,#2c251d,var(--bg) 45%); color:var(--text); }}
main {{ width:min(1040px,calc(100% - 32px)); margin:42px auto 80px; }}
h1 {{ font-family:Georgia,serif; font-size:clamp(34px,6vw,62px); margin:0 0 8px; }}
.lead,.meta,footer {{ color:var(--muted); }}
.passage {{ background:#17130f; border:1px solid var(--line); padding:18px 20px; border-radius:12px; color:#e6d7c7; line-height:1.55; margin:24px 0; }}
.grid {{ display:grid; gap:16px; }}
.card {{ display:grid; grid-template-columns:66px 1fr; gap:12px; background:rgba(33,29,23,.94); border:1px solid var(--line); border-radius:15px; padding:20px; }}
.number {{ font:700 26px Georgia,serif; color:var(--accent); }}
h2 {{ margin:0 0 5px; font:700 25px Georgia,serif; }}
p {{ line-height:1.5; }}
.meta {{ font-size:14px; }}
.players {{ display:grid; grid-template-columns:180px 1fr; gap:10px 14px; align-items:center; margin-top:16px; }}
.players label {{ color:var(--muted); font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; }}
audio {{ width:100%; }}
.pending {{ background:#17130f; border:1px dashed var(--line); border-radius:8px; padding:12px; color:var(--muted); }}
footer {{ margin-top:28px; font-size:13px; line-height:1.5; }}
@media(max-width:650px) {{ .card {{ grid-template-columns:1fr; }} .players {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body><main>
<header>
<h1>Parroty Voice Auditions</h1>
<p class="lead">Generated with your installed Parroty Chatterbox Standard model using identical text and settings. Nothing has been added to Parroty's permanent voice menu.</p>
</header>
<div class="passage"><strong>Shared test passage</strong><br>{html.escape(PASSAGE)}</div>
<section class="grid">{''.join(cards)}</section>
<footer>Source references: CSTR VCTK Corpus, CC BY 4.0. Anonymous speaker IDs are retained; do not attempt to identify the speakers.</footer>
</main></body></html>"""
    destination = HERE / "review.html"
    destination.write_text(page, encoding="utf-8")
    return destination


def main() -> None:
    candidates = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "app" / "converters" / "chatterbox_engine.py").exists():
        raise RuntimeError(
            "Extract the audition pack directly into the Parroty folder. "
            "The voice_review folder must sit beside app, venv, and run.bat."
        )

    from app.converters.chatterbox_engine import ChatterboxEngine

    print("Loading Parroty Chatterbox Standard once. The first load may download model files...")
    engine = ChatterboxEngine(device="auto", variant="standard")
    failures: list[tuple[str, str]] = []

    for position, candidate in enumerate(candidates, start=1):
        order = int(candidate["order"])
        reference = REFS / candidate["filename"]
        output = OUTPUTS / f"{order:02d}_{candidate['slug']}.wav"
        print(f"\n[{position}/{len(candidates)}] {candidate['label']} — {candidate['speaker']}")
        last_percent = -10

        def progress(done: float, _total: float) -> None:
            nonlocal last_percent
            percent = int(float(done) * 100)
            if percent >= last_percent + 10 or percent == 100:
                last_percent = percent
                print(f"  {percent:3d}%", flush=True)

        try:
            engine.synthesize(
                PASSAGE,
                str(output),
                speaker_wav=str(reference),
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
                progress_callback=progress,
            )
        except Exception as exc:
            failures.append((candidate["label"], str(exc)))
            print(f"  FAILED: {exc}")
            traceback.print_exc()

    review_page = build_review_page(candidates)
    print(f"\nVoice review page created: {review_page}")
    if failures:
        print("\nSome candidates failed:")
        for label, error in failures:
            print(f" - {label}: {error}")
    webbrowser.open(review_page.resolve().as_uri())


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value: str) -> None:
        for stream in self.streams:
            try:
                stream.write(value)
                stream.flush()
            except Exception:
                pass

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


if __name__ == "__main__":
    with LOG_PATH.open("a", encoding="utf-8", errors="replace") as log_file:
        sys.stdout = Tee(sys.__stdout__, log_file)
        sys.stderr = Tee(sys.__stderr__, log_file)
        try:
            main()
        except Exception:
            traceback.print_exc()
            raise
