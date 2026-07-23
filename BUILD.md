# Parroty build and packaging guide

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
