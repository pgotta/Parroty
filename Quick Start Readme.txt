========================================================================
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
No API key or separate voice download is required. Closing the dedicated
Parroty Chrome/Edge app window with X automatically stops the hidden backend.

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
3. Close the Parroty app window with X to stop the hidden backend automatically.
4. Use stop.bat only if the window is already gone or a forced stop is needed.
5. Use run_debug.bat only for troubleshooting.

Do not commit the generated BAT files. They are local/package conveniences.
