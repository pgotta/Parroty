@echo off
setlocal
cd /d "%~dp0"
wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs" /quiet
start "" wscript.exe //nologo "%~dp0launch_parroty.vbs"
exit /b 0
