from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
QUICK = ROOT / "Quick Start Readme.txt"
GITIGNORE = ROOT / ".gitignore"


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find README block: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------
s = README.read_text(encoding="utf-8")
s = s.replace("- [Known issues](#known-issues)\n", "")
s = s.replace(
    "- [Keeping the GPU at full speed](#keeping-the-gpu-at-full-speed)\n",
    "- [GPU setup and performance](#gpu-setup-and-performance)\n",
)
s = s.replace(
    "- [Project layout](#project-layout)\n",
    "- [Project layout](#project-layout)\n"
    "- [Building a Windows distribution](#building-a-windows-distribution)\n",
)

if "## Known issues\n" in s:
    start = s.index("## Known issues\n")
    end = s.index("## Screenshots\n", start)
    s = s[:start] + s[end:]

s = replace_required(
    s,
    "- **Three voice engines:** OpenAI and ElevenLabs (cloud, paid) and **Chatterbox**\n"
    "  (free, local, GPU-accelerated) which can clone a voice from a ~10-second sample.\n",
    "- **Three voice engines:** OpenAI and ElevenLabs (cloud, paid) and **Chatterbox**\n"
    "  (free, local, GPU-accelerated), with eight bundled audiobook voices plus custom\n"
    "  voice cloning from a ~10-second sample.\n",
    "highlight voice text",
)

s = s.replace(
    "| **Chatterbox** | free (local) | yes | clones from ~10s sample, GPU recommended |",
    "| **Chatterbox** | free (local) | yes | 8 bundled audiobook voices, custom cloning from ~10s sample, GPU recommended |",
)

voice_anchor = "WARNING: Only clone voices you own or have explicit permission to use.\n\n---\n"
voice_section = """WARNING: Only clone voices you own or have explicit permission to use.

### Bundled local voices

Chatterbox includes eight reviewed offline reference voices:

- Warm female
- Mature female
- Neutral female
- British female
- Warm male
- Mature/deep male
- Neutral male
- British male

These replace the older generic Female/Male references. They are anonymous VCTK
corpus clips licensed under CC BY 4.0; attribution is kept in
`app/assets/voices/ATTRIBUTION.md`. Uploading a custom reference sample still
overrides the selected built-in voice for that project.

---
"""
s = replace_required(s, voice_anchor, voice_section, "bundled voice section")

s = s.replace(
    "| OS | Windows 10/11 for the `.bat` launchers; macOS/Linux work from the command line |",
    "| OS | Windows 10/11 tested; macOS/Linux can run from the command line |",
)

old_batch_note = """> **Prefer to double-click instead of typing commands?** See
> **`Quick Start Readme.txt`** in this folder. It walks you through creating a
> few optional Windows launcher files — including an `install_all.bat` that
> installs *everything* (Python, ffmpeg, the environment, all packages, and GPU
> PyTorch) in one double-click, and a `run.bat` to start Parroty. They're
> optional; the commands above do the same job.
"""
new_batch_note = """> **Prefer to double-click instead of typing commands?** See
> **`Quick Start Readme.txt`**. It contains the current Windows BAT templates.
> Batch files are intentionally excluded from Git and generated locally (or
> injected into a downloadable Windows ZIP) so machine-specific wrappers never
> become repository source files. The commands above remain the portable setup
> path.
"""
s = replace_required(s, old_batch_note, new_batch_note, "batch launcher note")

old_running = """**Normal Windows launch:** double-click **`run.bat`**. It starts the backend
windowlessly through `pythonw.exe`, opens Parroty in a dedicated Chrome/Edge app
window, and silently creates or refreshes a desktop shortcut. Output goes to
`parroty.log`; stop the hidden server with `stop.bat`. `run_hidden.bat` remains as
a backwards-compatible alias and behaves the same way.
"""
new_running = """**Optional Windows launchers:** create the local `.bat` files from
`Quick Start Readme.txt`, or use a packaged Windows ZIP that already includes
them. `run.bat` starts the backend windowlessly through `pythonw.exe`, opens
Parroty in a dedicated maximized Chrome/Edge app window, and silently creates or
refreshes the desktop shortcut. Output goes to `parroty.log`; use `stop.bat` to
shut down the hidden server. These `.bat` files are deliberately ignored by Git.
"""
s = replace_required(s, old_running, new_running, "running and stopping")

if "## Keeping the GPU at full speed\n" in s:
    start = s.index("## Keeping the GPU at full speed\n")
    end = s.index("## Memory use on 16 GB machines\n", start)
    gpu_section = """## GPU setup and performance

For local Chatterbox narration, select **CUDA / NVIDIA GPU** in Parroty and
confirm that the bottom-left system monitor shows the NVIDIA GPU and rising VRAM
while speech is being generated. GPU utilization naturally rises and falls: the
model generates speech on the GPU, then Parroty performs CPU and disk work such
as chunk assembly, MP3 writing, progress updates, resume-ledger writes, and
memory cleanup. Average utilization can therefore be lower during a full book
than during a short back-to-back voice audition.

For best laptop performance:

- Plug in AC power.
- Use **Windows Settings → System → Power → Best performance**.
- In NVIDIA Control Panel, set `python.exe` and `pythonw.exe` to **Prefer maximum
  performance** when available.
- Keep enough free RAM and page-file headroom for the Standard model.

The hidden launcher and narration workers already request high execution priority
and opt out of Windows process power throttling. No visible PowerShell window is
required during narration.

"""
    s = s[:start] + gpu_section + s[end:]

s = s.replace(
    "- **System:** psutil (memory monitoring), ctypes (Windows API), batch-file launchers",
    "- **System:** psutil (memory monitoring), ctypes (Windows API), local Windows launcher helpers",
)

build_section = """## Building a Windows distribution

Repository source and downloadable Windows packages are intentionally different:

- Git tracks the application, Python/VBS/PowerShell launcher helpers, icon, voice
  assets, documentation, and tests.
- Git does **not** track `.bat` files. `.gitignore` blocks `*.bat` everywhere.
- A Windows ZIP may include locally generated `.bat` convenience launchers at the
  archive root. The current templates live in `Quick Start Readme.txt`.
- Package the project files at the ZIP root; do not add an extra nested `Parroty`
  directory.

See [`BUILD.md`](BUILD.md) for the complete packaging checklist and validation
commands.

---

"""
if "## Building a Windows distribution\n" not in s:
    s = replace_required(s, "## Troubleshooting\n", build_section + "## Troubleshooting\n", "build section")

for stale in ("loses focus", "keep the Parroty console", "fix_gpu.bat", "## Known issues"):
    if stale.lower() in s.lower():
        raise RuntimeError(f"Stale GPU-focus text remains in README: {stale}")

README.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# Quick Start: BAT files are kept as text templates, never tracked as files.
# ---------------------------------------------------------------------------
quick = r'''========================================================================
  PARROTY - WINDOWS QUICK START
========================================================================

The Parroty source repository intentionally does NOT track .bat files.
The repository .gitignore blocks *.bat everywhere. Downloadable Windows ZIPs
may include these wrappers for convenience, but they are never source files.

Create any BAT file below inside the Parroty folder, beside requirements.txt,
launch_parroty.pyw, and the app folder:

1. Open Notepad.
2. Copy the complete block for the file.
3. File > Save As.
4. Set "Save as type" to "All Files (*.*)".
5. Save with the exact .bat filename shown.

The eight bundled Chatterbox voices already live under app\assets\voices.
No API key or separate voice download is required.

========================================================================
  FILE: install_all.bat
========================================================================

@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Parroty - Install All

set "HAVE_WINGET="
where winget >nul 2>&1 && set "HAVE_WINGET=1"

set "PY="
for %%V in (3.12 3.11 3.10) do (
    if not defined PY py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
)
if not defined PY python -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1 && set "PY=python"

if not defined PY if defined HAVE_WINGET (
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
)
if not defined PY (
    echo Python 3.10-3.12 is required. Install Python 3.12 and rerun this file.
    pause
    exit /b 1
)

where ffmpeg >nul 2>&1
if errorlevel 1 if defined HAVE_WINGET winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements

if not exist "venv\Scripts\python.exe" %PY% -m venv venv
if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
)

set "VPY=venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip setuptools wheel
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Core requirements failed to install.
    pause
    exit /b 1
)

"%VPY%" -m pip install --upgrade --force-reinstall --no-cache-dir torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
    echo CUDA PyTorch failed to install. Cloud voices may still work.
)

"%VPY%" "tools\install_chatterbox_compat.py"
if errorlevel 1 echo Chatterbox installation failed. Cloud voices may still work.

"%VPY%" -c "import torch; print('PyTorch:',torch.__version__); print('CUDA:',torch.version.cuda); print('GPU available:',torch.cuda.is_available()); print('GPU:',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"

if exist "create_desktop_shortcut.vbs" wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs" /quiet

echo.
echo Installation complete. Start Parroty with run.bat or the desktop shortcut.
pause

========================================================================
  FILE: run.bat
========================================================================

@echo off
setlocal
cd /d "%~dp0"
wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs" /quiet
start "" wscript.exe //nologo "%~dp0launch_parroty.vbs"
exit /b 0

========================================================================
  FILE: stop.bat
========================================================================

@echo off
setlocal enabledelayedexpansion
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5000" ^| findstr LISTENING') do (
  taskkill /F /PID %%P >nul 2>&1
  set "FOUND=1"
)
if "!FOUND!"=="0" (echo Parroty was not running.) else (echo Parroty stopped.)
timeout /t 2 >nul
exit /b 0

========================================================================
  FILE: run_debug.bat
========================================================================

@echo off
setlocal
cd /d "%~dp0"
title Parroty - Debug Launcher
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python.exe"
set "PARROTY_HIDDEN="
set "PARROTY_NO_BROWSER="
"%PY%" -m app.server
echo.
echo Parroty stopped. Review the error above or parroty.log.
pause

========================================================================
  FILE: Create Desktop Shortcut.bat
========================================================================

@echo off
cd /d "%~dp0"
wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs"
exit /b 0

========================================================================
  FINISHED
========================================================================

1. Run install_all.bat once.
2. Start Parroty with run.bat or the desktop shortcut.
3. Use stop.bat to stop the hidden backend.
4. Use run_debug.bat only for troubleshooting.

Do not commit the generated BAT files. They are local/package conveniences.
'''
QUICK.write_text(quick, encoding="utf-8", newline="\r\n")


# ---------------------------------------------------------------------------
# Build and current release notes
# ---------------------------------------------------------------------------
(ROOT / "BUILD.md").write_text(
    '''# Parroty build and packaging guide

This document describes how to prepare a clean Windows distribution from the
GitHub source tree. It does not assign or change a version number.

## Repository policy

- Never commit Windows batch files. `.gitignore` must contain `*.bat`.
- Keep launcher logic in the tracked helpers:
  - `launch_parroty.pyw`
  - `launch_parroty.vbs`
  - `parroty_window.ps1`
  - `create_desktop_shortcut.vbs`
- Batch files are local convenience wrappers or release-package additions only.
  Their current templates are maintained in `Quick Start Readme.txt`.
- Do not commit `venv`, `.venv`, model caches, uploaded books, generated output,
  logs, Python bytecode, or editor files.

## Files required in a Windows package

The ZIP root should contain the project files directly. Do not wrap them inside
an extra nested `Parroty` directory.

Required source/runtime files include `app/`, `tools/`, `requirements.txt`, the
tracked launcher helpers, `parroty.ico`, documentation, and `LICENSE`.

The voice package must include all eight `builtin_*.wav` files and
`app/assets/voices/ATTRIBUTION.md`.

A downloadable Windows ZIP may additionally include locally generated wrappers:
`install_all.bat`, `run.bat`, `stop.bat`, `run_debug.bat`, and
`Create Desktop Shortcut.bat`. Those files belong in the ZIP only, not in Git.

## Clean-package checklist

1. Start from the current `main` branch and confirm `git status` is clean.
2. Confirm no tracked BAT files:

   ```bash
   git ls-files "*.bat"
   ```

   The command must print nothing.

3. Confirm `.gitignore` contains `*.bat`.
4. Remove `.git`, virtual environments, caches, logs, browser profiles, uploaded
   books, and generated output from the staging folder.
5. Preserve `output/.gitkeep` and `uploads/.gitkeep`.
6. Add locally generated BAT wrappers from `Quick Start Readme.txt` only to the
   staging folder.
7. Ensure project files sit at the archive root, then create the ZIP.

## Validation

```powershell
py -3.12 -m py_compile launch_parroty.pyw app/server.py app/tts.py app/narrate_worker.py
py -3.12 -c "from app.tts import ENGINE_CATALOG; v=ENGINE_CATALOG['chatterbox']['builtin_voices']; assert len(v)==8; print(list(v))"
```

After installation, verify the monitor identifies CUDA/NVIDIA, the app opens in
a dedicated maximized window without a visible console, the desktop shortcut
uses `parroty.ico`, all eight voices appear, previews work, and `stop.bat` shuts
down port 5000.

Before publishing, review `README.md`, `Quick Start Readme.txt`, `BUILD.md`,
`RELEASE_NOTES.md`, and the voice attribution. No version bump or GitHub Release
is required unless one is explicitly planned.
''',
    encoding="utf-8",
)

(ROOT / "RELEASE_NOTES.md").write_text(
    '''# Parroty — current release notes

No version number is assigned to this update.

## Included changes

- Replaced the two generic Chatterbox Female/Male references with eight reviewed,
  free, local audiobook voices: Warm female, Mature female, Neutral female,
  British female, Warm male, Mature/deep male, Neutral male, and British male.
- Preserved custom reference-sample voice cloning.
- Added CC BY 4.0 attribution for the anonymous VCTK reference clips.
- Added the bottom-left CPU/GPU/VRAM system monitor.
- Added hidden background launching with persistent `parroty.log` diagnostics.
- Added a dedicated maximized Chrome/Edge app window using its own browser profile.
- Added desktop-shortcut creation using the Parroty icon.
- Corrected hidden-launch template/static resolution.
- Kept narration workers GPU-enabled when the app window is hidden or inactive.
- Updated documentation and package-building instructions.
- Removed all BAT files from Git tracking and reinforced the `*.bat` ignore rule.

## Packaging note

The GitHub repository intentionally excludes `.bat` files. Windows release ZIPs
may include locally generated BAT wrappers. Their current templates are stored
in `Quick Start Readme.txt`.
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Gitignore and tracked BAT cleanup
# ---------------------------------------------------------------------------
g = GITIGNORE.read_text(encoding="utf-8")
old = """# ---- Windows launcher scripts ----
# Kept out of the public repo so it looks tidy and less alarming to visitors.
# They still live in your own copy of the folder, so you can double-click to run.
*.bat
"""
new = """# ---- Windows batch wrappers ----
# BAT files are generated locally or added only to Windows release ZIPs.
# Never commit them to the source repository.
*.bat
**/*.bat
"""
if old in g:
    g = g.replace(old, new, 1)
elif "*.bat" not in g:
    g += "\n# Windows batch wrappers are release/local files only\n*.bat\n**/*.bat\n"
GITIGNORE.write_text(g, encoding="utf-8")

tracked = subprocess.check_output(
    ["git", "ls-files", "*.bat"], cwd=ROOT, text=True
).splitlines()
for rel in tracked:
    path = ROOT / rel
    if path.exists():
        path.unlink()
    print(f"Removed tracked BAT: {rel}")

print(f"Documentation updated; removed {len(tracked)} tracked BAT file(s).")
