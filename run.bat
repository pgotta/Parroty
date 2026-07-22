@echo off
setlocal
cd /d "%~dp0"

REM Refresh the desktop shortcut silently. The VBS uses Windows' real Desktop
REM location, including OneDrive-redirection, and is safe to run every time.
wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs" /quiet

REM The real launcher uses pythonw.exe, so no PowerShell/cmd window remains.
start "" wscript.exe //nologo "%~dp0launch_parroty.vbs"
exit /b 0
