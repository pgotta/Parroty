@echo off
cd /d "%~dp0"
wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs"
exit /b 0
