from __future__ import annotations

import html
import json
import shutil
import zipfile
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

DIST = Path("dist")
PACK = DIST / "Parroty-Voice-Audition-Pack"
REVIEW = PACK / "voice_review"
REFS = REVIEW / "references"
OUTPUTS = REVIEW / "outputs"

PASSAGE = (
    "At first light, the old house stood quietly above the river. "
    "Mara opened the weathered book and read the first line aloud. "
    "Beyond the window, rain moved through the trees, soft and steady, "
    "while the fire settled into a warm glow."
)

CANDIDATES = [
    {"order": 1, "slug": "warm_female", "label": "Warm female", "speaker": "p318", "clip": "p318_021_pad.wav", "age": 32, "accent": "American", "region": "Napa", "description": "A rounded American female candidate selected for warmth."},
    {"order": 2, "slug": "mature_female", "label": "Mature female", "speaker": "p294", "clip": "p294_006_pad.wav", "age": 33, "accent": "American", "region": "San Francisco", "description": "The oldest female speaker in this shortlist, selected for a more mature tone."},
    {"order": 3, "slug": "neutral_female", "label": "Neutral female", "speaker": "p300", "clip": "p300_021_pad.wav", "age": 23, "accent": "American", "region": "California", "description": "A general American female candidate intended to be clear and unobtrusive."},
    {"order": 4, "slug": "british_female", "label": "British female", "speaker": "p276", "clip": "p276_021_pad.wav", "age": 24, "accent": "English", "region": "Oxford", "description": "An Oxford English female candidate for a distinctly British narration option."},
    {"order": 5, "slug": "warm_male", "label": "Warm male", "speaker": "p311", "clip": "p311_021_pad.wav", "age": 21, "accent": "American", "region": "Iowa", "description": "A general American male candidate selected for a relaxed, warm delivery."},
    {"order": 6, "slug": "mature_deep_male", "label": "Mature/deep male", "speaker": "p227", "clip": "p227_011_pad.wav", "age": 38, "accent": "English", "region": "Cumbria", "description": "The oldest male speaker in this shortlist, selected for maturity and depth."},
    {"order": 7, "slug": "neutral_male", "label": "Neutral male", "speaker": "p345", "clip": "p345_021_pad.wav", "age": 22, "accent": "American", "region": "Florida", "description": "A general American male candidate intended to stay clear and neutral."},
    {"order": 8, "slug": "british_male", "label": "British male", "speaker": "p232", "clip": "p232_021_pad.wav", "age": 23, "accent": "English", "region": "Southern England", "description": "A Southern English male candidate for a broadly British audiobook voice."},
]


def find_source_paths() -> dict[str, str]:
    files = HfApi().list_repo_files("yfyeung/vctk", repo_type="dataset")
    by_name = {Path(item).name: item for item in files if item.lower().endswith(".wav")}
    result: dict[str, str] = {}
    for candidate in CANDIDATES:
        clip = candidate["clip"]
        source = by_name.get(clip)
        if source is None:
            expected_suffix = f"/{candidate['speaker']}/{clip}"
            matches = [item for item in files if item.replace("\\", "/").endswith(expected_suffix)]
            if matches:
                source = matches[0]
        if source is None:
            raise RuntimeError(f"Could not locate {clip} in yfyeung/vctk")
        result[candidate["speaker"]] = source
    return result


def initial_review_html(candidates: list[dict]) -> str:
    cards: list[str] = []
    for candidate in candidates:
        order = int(candidate["order"])
        reference = f"references/{candidate['filename']}"
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
            f'<audio controls preload="metadata" src="{reference}"></audio>'
            '<label>Parroty Chatterbox preview</label>'
            '<div class="pending">Run <strong>Generate Voice Reviews.bat</strong> to create the same audiobook passage with this voice.</div>'
            '</div></div></article>'
        )

    return f"""<!doctype html>
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
<header><h1>Parroty Voice Auditions</h1><p class="lead">Listen to the clean source references now, then generate the real Parroty Chatterbox versions with the included BAT file. The category names are provisional audition labels, not claims about the speakers.</p></header>
<div class="passage"><strong>Shared test passage</strong><br>{html.escape(PASSAGE)}</div>
<section class="grid">{''.join(cards)}</section>
<footer>Source: CSTR VCTK Corpus, licensed CC BY 4.0. Speaker identities remain anonymous; do not attempt to identify them.</footer>
</main></body></html>"""


def write_launchers() -> None:
    generate = r'''@echo off
setlocal
cd /d "%~dp0"
title Parroty Voice Auditions
if not exist "app\converters\chatterbox_engine.py" (
  echo [X] Extract this ZIP directly into your existing Parroty folder.
  echo     Generate Voice Reviews.bat must sit beside app, venv, and run.bat.
  pause
  exit /b 1
)
if not exist "venv\Scripts\python.exe" (
  echo [X] Parroty's venv was not found. Run install_all.bat first.
  pause
  exit /b 1
)
echo Generating eight identical audiobook previews through Parroty Chatterbox Standard.
echo The model loads once and uses your GPU. Nothing is added permanently.
echo.
"venv\Scripts\python.exe" "voice_review\generate_previews.py"
if errorlevel 1 (
  echo.
  echo [X] Generation did not finish. See voice_review\voice_review.log
  pause
  exit /b 1
)
echo.
echo Done. The local review page should now be open.
pause
'''
    open_review = r'''@echo off
cd /d "%~dp0"
if not exist "voice_review\review.html" (
  echo [X] voice_review\review.html is missing.
  pause
  exit /b 1
)
start "" "%CD%\voice_review\review.html"
'''
    (PACK / "Generate Voice Reviews.bat").write_text(generate, encoding="utf-8", newline="\r\n")
    (PACK / "Open Voice Review.bat").write_text(open_review, encoding="utf-8", newline="\r\n")


def main() -> None:
    if PACK.exists():
        shutil.rmtree(PACK)
    REFS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    sources = find_source_paths()
    packaged: list[dict] = []
    for candidate in CANDIDATES:
        filename = f"{candidate['order']:02d}_{candidate['slug']}_{candidate['speaker']}.wav"
        cached = hf_hub_download(
            repo_id="yfyeung/vctk",
            repo_type="dataset",
            filename=sources[candidate["speaker"]],
        )
        destination = REFS / filename
        shutil.copy2(cached, destination)
        if destination.stat().st_size < 100_000:
            raise RuntimeError(f"Downloaded reference looks too small: {destination}")
        item = dict(candidate)
        item["filename"] = filename
        item["source_repo_path"] = sources[candidate["speaker"]]
        packaged.append(item)
        print(candidate["label"], sources[candidate["speaker"]], destination.stat().st_size)

    generator_source = Path("tools/voice_audition_generate_previews.py")
    shutil.copy2(generator_source, REVIEW / "generate_previews.py")
    (REVIEW / "candidates.json").write_text(json.dumps(packaged, indent=2), encoding="utf-8")
    (REVIEW / "review.html").write_text(initial_review_html(packaged), encoding="utf-8")
    (OUTPUTS / ".gitkeep").write_text("", encoding="utf-8")
    write_launchers()

    readme_lines = [
        "PARROTY VOICE AUDITION PACK",
        "============================",
        "",
        "This is a review-only pack. It does not change Parroty's permanent voice menu.",
        "",
        "HOW TO USE",
        "1. Extract the ZIP directly into your existing Parroty folder.",
        "2. Double-click Generate Voice Reviews.bat.",
        "3. Chatterbox Standard loads once and renders the same passage with all eight voices.",
        "4. The local review page opens automatically.",
        "5. Tell ChatGPT which numbered voices you want to keep.",
        "",
        "The reference clips can be heard immediately by opening voice_review\\review.html.",
        "Generated clips are saved under voice_review\\outputs.",
        "Logs are saved to voice_review\\voice_review.log.",
        "",
        "CANDIDATES",
    ]
    for candidate in packaged:
        readme_lines.append(
            f"{candidate['order']:02d}. {candidate['label']} — anonymous VCTK "
            f"{candidate['speaker']}, age {candidate['age']}, "
            f"{candidate['accent']}, {candidate['region']}"
        )
    readme_lines.extend([
        "",
        "The descriptive labels are provisional audition categories, not verified personal traits.",
        "Do not attempt to identify the anonymous speakers.",
        "",
    ])
    (PACK / "README-FIRST.txt").write_text("\n".join(readme_lines), encoding="utf-8")

    attribution = """LICENSE AND ATTRIBUTION
=======================

Source corpus: CSTR VCTK Corpus: English Multi-speaker Corpus for CSTR Voice Cloning Toolkit.
Corpus authors: Christophe Veaux, Junichi Yamagishi, and Kirsten MacDonald.
License: Creative Commons Attribution 4.0 International (CC BY 4.0).
Source distribution used for these short clips: yfyeung/vctk on Hugging Face.

The clips under voice_review/references are anonymous VCTK speaker samples.
Do not attempt to identify the speakers. Preserve this attribution if selected clips are later bundled with Parroty.

The generated voice_review/outputs files are created locally using the user's installed Chatterbox model and are not included in this download.
"""
    (PACK / "LICENSE-ATTRIBUTION.txt").write_text(attribution, encoding="utf-8")

    archive = DIST / "Parroty-Voice-Audition-Pack.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in PACK.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(PACK))
    print("Created", archive, archive.stat().st_size)


if __name__ == "__main__":
    main()
