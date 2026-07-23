from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected text was not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def update_readme() -> None:
    replace_once(
        ROOT / "README.md",
        "Parroty in a dedicated maximized Chrome/Edge app window, and silently creates or\n"
        "refreshes the desktop shortcut. Output goes to `parroty.log`; use `stop.bat` to\n"
        "shut down the hidden server. These `.bat` files are deliberately ignored by Git.",
        "Parroty in a dedicated maximized Chrome/Edge app window, and silently creates or\n"
        "refreshes the desktop shortcut. Closing that Parroty app window with **X** now\n"
        "automatically stops the hidden Flask backend, the same result as running\n"
        "`stop.bat`. Output goes to `parroty.log`; `stop.bat` remains available as a\n"
        "fallback if the window is already gone or the backend needs to be forced closed.\n"
        "These `.bat` files are deliberately ignored by Git.",
    )


def update_quick_start() -> None:
    path = ROOT / "Quick Start Readme.txt"
    replace_once(
        path,
        "- stop.bat          Stop the hidden backend.",
        "- stop.bat          Fallback force-stop for the hidden backend.",
    )
    replace_once(
        path,
        "dedicated maximized Chrome/Edge app window and keeps logs in parroty.log.",
        "dedicated maximized Chrome/Edge app window and keeps logs in parroty.log.\n"
        "Closing that Parroty window with X automatically stops the hidden backend.",
    )
    replace_once(
        path,
        "3. Use stop.bat when you need to stop the hidden backend.\n"
        "4. Use run_debug.bat only when you need a visible traceback or log.",
        "3. Close the Parroty app window with X to stop the hidden backend automatically.\n"
        "4. Use stop.bat only if the window is already gone or a forced stop is needed.\n"
        "5. Use run_debug.bat only when you need a visible traceback or log.",
    )


def update_build() -> None:
    path = ROOT / "BUILD.md"
    replace_once(
        path,
        "- Parroty opens in its own maximized app window.\n"
        "- The desktop shortcut uses `parroty.ico`.",
        "- Parroty opens in its own maximized app window.\n"
        "- Closing the app window with X stops the Flask listener and releases port 5000.\n"
        "- The desktop shortcut uses `parroty.ico`.",
    )
    replace_once(
        path,
        "- `stop.bat` shuts down the server on port 5000.",
        "- `stop.bat` still shuts down the server on port 5000 as a fallback.",
    )


def update_release_notes() -> None:
    replace_once(
        ROOT / "RELEASE_NOTES.md",
        "- Added a dedicated maximized Chrome/Edge app window using its own browser\n"
        "  profile, rather than reopening inside the user's normal browser session.\n",
        "- Added a dedicated maximized Chrome/Edge app window using its own browser\n"
        "  profile, rather than reopening inside the user's normal browser session.\n"
        "- Closing the dedicated Parroty app window now automatically stops the hidden\n"
        "  Flask backend, matching `stop.bat` behavior without affecting normal browser windows.\n",
    )


def main() -> None:
    update_readme()
    update_quick_start()
    update_build()
    update_release_notes()
    print("Updated window-close shutdown documentation")


if __name__ == "__main__":
    main()
