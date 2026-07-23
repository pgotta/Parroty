# Parroty — current release notes

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
- Closing the dedicated Parroty app window now monitors the exact native window
  handle and terminates the complete Parroty process tree, including active
  `app.narrate_worker` children that Windows would otherwise leave orphaned.
- Updated the local `stop.bat` template to detect both the port-5000 listener and
  Parroty launcher/server/narration workers, preventing false “not running” reports.
- Added the Parroty bird favicon and applies `parroty.ico` directly to the native
  Chrome/Edge app window so the title bar and Windows taskbar show the app icon.
- Added desktop-shortcut creation using the Parroty icon.
- Corrected hidden-launch template/static resolution.
- Kept narration workers GPU-enabled when the app window is hidden or inactive.
- Updated documentation and package-building instructions.
- Removed all BAT files from Git tracking and reinforced the `*.bat` ignore rule.

## Packaging note

The GitHub repository intentionally excludes `.bat` files. Windows release ZIPs
may include locally generated BAT wrappers. Their current templates are stored
in `Quick Start Readme.txt`.
