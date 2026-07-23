from __future__ import annotations

import html
import json
import shutil
import textwrap
import wave
import zipfile
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

OUT = Path("dist/Parroty-Voice-Audition-Pack")
REFS = OUT / "voice_review" / "references"
OUTPUTS = OUT / "voice_review" / "outputs"

CANDIDATES = [
    {
        "order": 1,
        "slug": "warm_female",
        "label": "Warm female",
        "speaker": "p318",
        "age": 32,
        "gender": "female",
        "accent": "American",
        "region": "Napa",
        "description": "A lower, rounded American female candidate selected for warmth.",
    },
    {
        "order": 2,
        "slug": "mature_female",
        "label": "Mature female",
        "speaker": "p294",
        "age": 33,
        "gender": "female",
        "accent": "American",
        "region": "San Francisco",
        "description": "The oldest female speaker in this shortlist, selected for a more mature tone.",
    },
    {
        "order": 3,
        "slug": "neutral_female",
        "label": "Neutral female",
        "speaker": "p300",
        "age": 23,
        "gender": "female",
        "accent": "American",
        "region": "California",
        "description": "A general American female candidate intended to be clear and unobtrusive.",
    },
    {
        "order": 4,
        "slug": "british_female",
        "label": "British female",
        "speaker": "p276",
        "age": 24,
        "gender": "female",
        "accent": "English",
        "region": "Oxford",
        "description": "An Oxford English female candidate for a distinctly British narration option.",
    },
    {
        "order": 5,
        "slug": "warm_male",
        "label": "Warm male",
        "speaker": "p311",
        "age": 21,
        "gender": "male",
        "accent": "American",
        "region": "Iowa",
        "description": "A general American male candidate selected for a relaxed, warm delivery.",
    },
    {
        "order": 6,
        "slug": "mature_deep_male",
        "label": "Mature/deep male",
        "speaker": "p227",
        "age": 38,
        "gender": "male",
        "accent": "English",
        "region": "Cumbria",
        "description": "The oldest male speaker in VCTK's English group, selected for maturity and depth.",
    },
    {
        "order": 7,
        "slug": "neutral_male",
        "label": "Neutral male",
        "speaker": "p345",
        "age": 22,
        "gender": "male",
        "accent": "American",
        "region": "Florida",
        "description": "A general American male candidate intended to stay clear and neutral.",
    },
    {
        "order": 8,
        "slug": "british_male",
        "label": "British male",
        "speaker": "p232",
        "age": 23,
        "gender": "male",
        "accent": "English",
        "region": "Southern England",
        "description": "A Southern English male candidate for a broadly British audiobook voice.",
    },
]

PASSAGE = (
    "At first light, the old house stood quietly above the river. "
    "Mara opened the weathered book and read the first line aloud. "
    "Beyond the window, rain moved through the trees, soft and steady, "
    "while the fire settled into a warm glow."
)


def locate_vctk_files() -> dict[str, str]:
    api = HfApi()
    files = api.list_repo_files("yfyeung/vctk", repo_type="dataset")
    chosen: dict[str, str] = {}
    for candidate in CANDIDATES:
        sid = candidate["speaker"]
        matches = [
            f for f in files
            if f.lower().endswith(".wav")
            and f"/{sid}/" in f.replace("\\", "/")
            and ("10s" in f.lower() or "10_sec" in f.lower())
        ]
        if not matches:
            matches = [
                f for f in files
                if f.lower().endswith(".wav")
                and f"/{sid}/" in f.replace("\\", "/")
            ]
        if not matches:
            raise RuntimeError(f"No VCTK sample found for {sid}")
        chosen[sid] = sorted(matches, key=lambda p: ("10s" not in p.lower(), len(p), p))[0]
    return chosen


def wav_details(path: Path) -> dict[str, int | float]:
    with wave.open(str(path), "rb") as wf:
        return {
            "channels": wf.getnchannels(),
            "sample_rate": wf.getframerate(),
            "sample_width": wf.getsampwidth(),
            "frames": wf.getnframes(),
            "duration": round(wf.getnframes() / max(1, wf.getframerate()), 3),
        }


def source_review_html(candidates: list[dict]) -> str:
    cards = []
    for c in candidates:
        ref = f"references/{c['filename']}"
        cards.append(
            f"""
            <article class="card">
              <div class="number">{c['order']:02d}</div>
              <div class="content">
                <h2>{html.escape(c['label'])}</h2>
                <p class="meta">Anonymous VCTK {c['speaker']} · {c['age']} · {html.escape(c['accent'])} · {html.escape(c['region'])}</p>
                <p>{html.escape(c['description'])}</p>
                <div class="players">
                  <label>Reference voice</label>
                  <audio controls preload="metadata" src="{ref}"></audio>
                  <label>Parroty Chatterbox preview</label>
                  <div class="pending">Run <strong>Generate Voice Reviews.bat</strong> to create the same audiobook passage with this voice.</div>
                </div>
              </div>
            </article>
            """
        )
    return html_page("Parroty Voice Auditions", "".join(cards), generated=False)


def html_page(title: str, cards: str, generated: bool) -> str:
    status = (
        "The generated Chatterbox previews are ready. Compare the same passage across all eight voices."
        if generated
        else "You can listen to the clean source references now. Generate the real Parroty versions with the included BAT file."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: dark; --bg:#15130f; --panel:#211d17; --line:#4b4032; --text:#f5eee3; --muted:#baa995; --accent:#d59a72; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Segoe UI,Arial,sans-serif; background:radial-gradient(circle at top,#2c251d,var(--bg) 45%); color:var(--text); }}
main {{ width:min(1040px,calc(100% - 32px)); margin:42px auto 80px; }}
header {{ margin-bottom:28px; }}
h1 {{ font-family:Georgia,serif; font-size:clamp(34px,6vw,62px); margin:0 0 8px; }}
.lead {{ color:var(--muted); max-width:760px; line-height:1.55; }}
.passage {{ background:#17130f; border:1px solid var(--line); padding:18px 20px; border-radius:12px; color:#e6d7c7; line-height:1.55; margin:24px 0; }}
.grid {{ display:grid; gap:16px; }}
.card {{ display:grid; grid-template-columns:66px 1fr; gap:12px; background:rgba(33,29,23,.94); border:1px solid var(--line); border-radius:15px; padding:20px; box-shadow:0 14px 32px rgba(0,0,0,.22); }}
.number {{ font:700 26px Georgia,serif; color:var(--accent); }}
h2 {{ margin:0 0 5px; font:700 25px Georgia,serif; }}
p {{ margin:8px 0; line-height:1.5; }}
.meta {{ color:var(--muted); font-size:14px; }}
.players {{ display:grid; grid-template-columns:180px 1fr; gap:10px 14px; align-items:center; margin-top:16px; }}
.players label {{ color:var(--muted); font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; }}
audio {{ width:100%; }}
.pending {{ background:#17130f; border:1px dashed var(--line); border-radius:8px; padding:12px; color:var(--muted); }}
footer {{ color:var(--muted); margin-top:28px; font-size:13px; line-height:1.5; }}
@media(max-width:650px) {{ .card{{grid-template-columns:1fr}} .players{{grid-template-columns:1fr}} }}
</style>
</head>
<body><main>
<header><h1>Parroty Voice Auditions</h1><p class="lead">{html.escape(status)} The category names are audition labels, not claims about the anonymous speakers. Nothing here changes Parroty until you choose.</p></header>
<div class="passage"><strong>Shared test passage</strong><br>{html.escape(PASSAGE)}</div>
<section class="grid">{cards}</section>
<footer>Source: CSTR VCTK Corpus. Audio and metadata are provided under Creative Commons Attribution 4.0. Speaker identities are intentionally anonymous; do not attempt to identify them.</footer>
</main></body></html>"""


def generate_preview_script() -> str:
    # This script executes on the user's installed Parroty environment.
    return textwrap.dedent(f'''\
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
        LOG = HERE / "voice_review.log"
        PASSAGE = {PASSAGE!r}

        sys.path.insert(0, str(ROOT))
        os.chdir(ROOT)

        def write_review(candidates):
            cards = []
            for c in candidates:
                ref = f"references/{{c['filename']}}"
                generated_name = f"{{c['order']:02d}}_{{c['slug']}}.wav"
                generated_path = OUTPUTS / generated_name
                if generated_path.exists():
                    generated = f'<audio controls preload="metadata" src="outputs/{{generated_name}}"></audio>'
                else:
                    generated = '<div class="pending">Generation failed or has not run yet. Check voice_review.log.</div>'
                cards.append(f'''<article class="card"><div class="number">{{c['order']:02d}}</div><div class="content"><h2>{{html.escape(c['label'])}}</h2><p class="meta">Anonymous VCTK {{c['speaker']}} · {{c['age']}} · {{html.escape(c['accent'])}} · {{html.escape(c['region'])}}</p><p>{{html.escape(c['description'])}}</p><div class="players"><label>Reference voice</label><audio controls preload="metadata" src="{{ref}}"></audio><label>Parroty Chatterbox preview</label>{{generated}}</div></div></article>''')
            body = "".join(cards)
            page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Parroty Voice Auditions</title><style>:root{{color-scheme:dark;--bg:#15130f;--panel:#211d17;--line:#4b4032;--text:#f5eee3;--muted:#baa995;--accent:#d59a72}}*{{box-sizing:border-box}}body{{margin:0;font-family:Segoe UI,Arial,sans-serif;background:radial-gradient(circle at top,#2c251d,var(--bg) 45%);color:var(--text)}}main{{width:min(1040px,calc(100% - 32px));margin:42px auto 80px}}h1{{font-family:Georgia,serif;font-size:clamp(34px,6vw,62px);margin:0 0 8px}}.lead,.meta,footer{{color:var(--muted)}}.passage{{background:#17130f;border:1px solid var(--line);padding:18px 20px;border-radius:12px;color:#e6d7c7;line-height:1.55;margin:24px 0}}.grid{{display:grid;gap:16px}}.card{{display:grid;grid-template-columns:66px 1fr;gap:12px;background:rgba(33,29,23,.94);border:1px solid var(--line);border-radius:15px;padding:20px}}.number{{font:700 26px Georgia,serif;color:var(--accent)}}h2{{margin:0 0 5px;font:700 25px Georgia,serif}}p{{line-height:1.5}}.meta{{font-size:14px}}.players{{display:grid;grid-template-columns:180px 1fr;gap:10px 14px;align-items:center;margin-top:16px}}.players label{{color:var(--muted);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}}audio{{width:100%}}.pending{{background:#17130f;border:1px dashed var(--line);border-radius:8px;padding:12px;color:var(--muted)}}footer{{margin-top:28px;font-size:13px;line-height:1.5}}@media(max-width:650px){{.card{{grid-template-columns:1fr}}.players{{grid-template-columns:1fr}}}}</style></head><body><main><header><h1>Parroty Voice Auditions</h1><p class="lead">Generated with your installed Parroty Chatterbox Standard model using identical settings and identical text. Nothing has been added to Parroty's permanent voice menu.</p></header><div class="passage"><strong>Shared test passage</strong><br>{{html.escape(PASSAGE)}}</div><section class="grid">{{body}}</section><footer>Source references: CSTR VCTK Corpus, CC BY 4.0. Anonymous speaker IDs are retained; do not attempt to identify the speakers.</footer></main></body></html>'''
            (HERE / "review.html").write_text(page, encoding="utf-8")

        def main():
            candidates = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
            OUTPUTS.mkdir(parents=True, exist_ok=True)
            if not (ROOT / "app" / "converters" / "chatterbox_engine.py").exists():
                raise RuntimeError("This audition pack must be extracted directly into the Parroty folder.")

            from app.converters.chatterbox_engine import ChatterboxEngine

            print("Loading Parroty Chatterbox Standard once. The first load may download model files...")
            engine = ChatterboxEngine(device="auto", variant="standard")
            total = len(candidates)
            failures = []
            for position, candidate in enumerate(candidates, 1):
                reference = REFS / candidate["filename"]
                output = OUTPUTS / f"{{candidate['order']:02d}}_{{candidate['slug']}}.wav"
                print(f"\n[{{position}}/{{total}}] {{candidate['label']}} — {{candidate['speaker']}}")
                last_percent = -1
                def progress(done, _total):
                    nonlocal last_percent
                    percent = int(float(done) * 100)
                    if percent >= last_percent + 10 or percent == 100:
                        last_percent = percent
                        print(f"  {{percent:3d}%}}", flush=True)
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
                    print(f"  FAILED: {{exc}}")
                    traceback.print_exc()

            write_review(candidates)
            print("\nVoice review page created:", HERE / "review.html")
            if failures:
                print("\nSome voices failed:")
                for label, error in failures:
                    print(" -", label, error)
            webbrowser.open((HERE / "review.html").resolve().as_uri())

        if __name__ == "__main__":
            try:
                with LOG.open("a", encoding="utf-8", errors="replace") as log:
                    class Tee:
                        def __init__(self, *streams): self.streams = streams
                        def write(self, value):
                            for stream in self.streams:
                                try: stream.write(value); stream.flush()
                                except Exception: pass
                        def flush(self):
                            for stream in self.streams:
                                try: stream.flush()
                                except Exception: pass
                    sys.stdout = Tee(sys.__stdout__, log)
                    sys.stderr = Tee(sys.__stderr__, log)
                    main()
            except Exception:
                traceback.print_exc()
                raise
    ''')


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    REFS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    repo_files = locate_vctk_files()
    final_candidates = []
    for c in CANDIDATES:
        filename = f"{c['order']:02d}_{c['slug']}_{c['speaker']}.wav"
        cached = hf_hub_download(
            repo_id="yfyeung/vctk",
            repo_type="dataset",
            filename=repo_files[c["speaker"]],
        )
        destination = REFS / filename
        shutil.copy2(cached, destination)
        item = dict(c)
        item["filename"] = filename
        item["source_repo_path"] = repo_files[c["speaker"]]
        item["audio"] = wav_details(destination)
        final_candidates.append(item)
        print(c["label"], c["speaker"], repo_files[c["speaker"]], item["audio"])

    (OUT / "voice_review" / "candidates.json").write_text(
        json.dumps(final_candidates, indent=2), encoding="utf-8"
    )
    (OUT / "voice_review" / "generate_previews.py").write_text(
        generate_preview_script(), encoding="utf-8"
    )
    (OUT / "voice_review" / "review.html").write_text(
        source_review_html(final_candidates), encoding="utf-8"
    )
    (OUTPUTS / ".gitkeep").write_text("", encoding="utf-8")

    generate_bat = r'''@echo off
setlocal
cd /d "%~dp0"
title Parroty Voice Auditions

if not exist "app\converters\chatterbox_engine.py" (
  echo [X] Extract this audition pack directly into your Parroty folder.
  echo     It should sit beside app, venv, run.bat, and install_all.bat.
  pause
  exit /b 1
)
if not exist "venv\Scripts\python.exe" (
  echo [X] Parroty's venv was not found. Run install_all.bat first.
  pause
  exit /b 1
)

echo Generating eight identical Chatterbox audiobook previews.
echo The model loads once, then each candidate is rendered on your GPU.
echo This may take several minutes. Nothing is added to Parroty permanently.
echo.
"venv\Scripts\python.exe" "voice_review\generate_previews.py"
if errorlevel 1 (
  echo.
  echo [X] Generation did not finish. See voice_review\voice_review.log
  pause
  exit /b 1
)
echo.
echo Done. The review page should now be open.
pause
'''
    open_bat = r'''@echo off
cd /d "%~dp0"
if not exist "voice_review\review.html" (
  echo [X] voice_review\review.html is missing.
  pause
  exit /b 1
)
start "" "%CD%\voice_review\review.html"
'''
    (OUT / "Generate Voice Reviews.bat").write_text(generate_bat, encoding="utf-8", newline="\r\n")
    (OUT / "Open Voice Review.bat").write_text(open_bat, encoding="utf-8", newline="\r\n")

    readme = f"""PARROTY VOICE AUDITION PACK
============================

This is a review-only pack. It does not modify Parroty's permanent voice menu.

HOW TO USE
1. Extract every file in this ZIP directly into your existing Parroty folder.
2. Double-click "Generate Voice Reviews.bat".
3. Parroty loads Chatterbox Standard once and renders the SAME passage with all eight candidates.
4. The local review page opens automatically. Listen and note which labels you want to keep.
5. You can reopen it later with "Open Voice Review.bat".

The clean reference clips are already playable in voice_review\review.html before generation.
Generated clips are saved under voice_review\outputs.
Logs are saved to voice_review\voice_review.log.

SHARED PASSAGE
{PASSAGE}

CANDIDATES
"""
    for c in final_candidates:
        readme += (
            f"{c['order']:02d}. {c['label']} — anonymous VCTK {c['speaker']}, "
            f"age {c['age']}, {c['accent']}, {c['region']}\n"
        )
    readme += "\nThe descriptive labels are provisional audition categories, not verified personal traits.\n"
    (OUT / "README-FIRST.txt").write_text(readme, encoding="utf-8")

    attribution = """LICENSE AND ATTRIBUTION
=======================

Source corpus: CSTR VCTK Corpus: English Multi-speaker Corpus for CSTR Voice Cloning Toolkit.
Corpus authors: Christophe Veaux, Junichi Yamagishi, and Kirsten MacDonald.
License: Creative Commons Attribution 4.0 International (CC BY 4.0).
Source: University of Edinburgh DataShare / CSTR VCTK Corpus.

The clips in voice_review/references are short anonymous speaker samples selected from the VCTK corpus.
Do not attempt to identify the speakers. Preserve this attribution if the selected clips are later bundled with Parroty.

The generated voice_review/outputs files are created locally by the user's installed Chatterbox model and are not included in this download.
"""
    (OUT / "LICENSE-ATTRIBUTION.txt").write_text(attribution, encoding="utf-8")

    archive = Path("dist/Parroty-Voice-Audition-Pack.zip")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in OUT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(OUT))
    print("Created", archive, archive.stat().st_size)


if __name__ == "__main__":
    main()
