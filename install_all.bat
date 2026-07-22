@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Parroty - Install All

echo ==========================================================
echo   PARROTY - INSTALL ALL
echo ==========================================================
echo.
echo This installs or repairs:
echo   - Python 3.12 (when missing)
echo   - ffmpeg
echo   - Parroty virtual environment and core packages
echo   - Chatterbox local voice engine
echo   - CUDA 12.8 PyTorch for NVIDIA GPUs / RTX 50-series
echo   - Parroty desktop shortcut
echo.
echo The first install downloads several gigabytes.
echo Existing working components are reused whenever possible.
echo.
pause

set "FAILED="
set "WARNINGS="
set "HAVE_WINGET="

where winget >nul 2>&1 && set "HAVE_WINGET=1"
if not defined HAVE_WINGET (
    echo.
    echo [!] Windows Package Manager ^(winget^) was not found.
    echo     The installer can still continue if Python 3.10-3.12 and ffmpeg
    echo     are already installed. Otherwise install "App Installer" from
    echo     Microsoft Store, then run install_all.bat again.
)

REM ============================================================
REM 1) Supported Python
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [1/7] Python
echo ----------------------------------------------------------

set "PY="
for %%V in (3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)

if not defined PY (
    python -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1 && set "PY=python"
)

if not defined PY (
    if defined HAVE_WINGET (
        echo Supported Python not found. Installing Python 3.12...
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        call :refresh_path
        py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
        if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
    )
)

if not defined PY (
    echo [X] A supported Python could not be found or installed.
    echo     Parroty requires Python 3.10-3.12; Python 3.14 is too new
    echo     for parts of the audio and local-TTS stack.
    echo     Install Python 3.12, then run this installer again:
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('%PY% --version 2^>^&1') do echo Using %%V

REM ============================================================
REM 2) ffmpeg
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [2/7] ffmpeg
echo ----------------------------------------------------------

where ffmpeg >nul 2>&1
if errorlevel 1 (
    if defined HAVE_WINGET (
        echo ffmpeg not found. Installing it...
        winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        call :refresh_path
    )
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [!] ffmpeg is still not visible.
    echo     Narration can run, but combining chapters and MP4 export will fail.
    echo     Close this window after setup, reopen it, and try "ffmpeg -version".
    set "WARNINGS=!WARNINGS! ffmpeg"
) else (
    for /f "delims=" %%V in ('ffmpeg -version 2^>nul ^| findstr /b "ffmpeg version"') do echo %%V
)

REM ============================================================
REM 3) Virtual environment
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [3/7] Virtual environment
echo ----------------------------------------------------------

set "VPY=venv\Scripts\python.exe"
if exist "%VPY%" (
    "%VPY%" -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Existing venv uses an unsupported or broken Python. Rebuilding it...
        rmdir /s /q "venv"
    ) else (
        echo Existing venv is compatible - reusing it.
    )
)

if not exist "%VPY%" (
    echo Creating venv...
    %PY% -m venv venv
    if errorlevel 1 (
        echo [X] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

REM ============================================================
REM 4) Core packages
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [4/7] Parroty core packages
 echo ----------------------------------------------------------

"%VPY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [X] pip could not be prepared.
    pause
    exit /b 1
)

"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] Parroty core requirements failed to install.
    echo     Review the error above, then rerun install_all.bat.
    pause
    exit /b 1
)

REM ============================================================
REM 5) Chatterbox
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [5/7] Chatterbox local voice engine
echo ----------------------------------------------------------

"%VPY%" -c "import chatterbox" >nul 2>&1
if errorlevel 1 (
    echo Installing Chatterbox...
    "%VPY%" -m pip install chatterbox-tts
    if errorlevel 1 (
        echo [!] Chatterbox failed to install. Cloud voices can still work,
        echo     but local voice cloning will be unavailable.
        set "FAILED=!FAILED! chatterbox"
    )
) else (
    echo Chatterbox is already installed - repairing dependencies if needed...
    "%VPY%" -m pip install chatterbox-tts
    if errorlevel 1 set "FAILED=!FAILED! chatterbox"
)

REM ============================================================
REM 6) CUDA PyTorch - always asserted after Chatterbox
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [6/7] CUDA 12.8 PyTorch
echo ----------------------------------------------------------

"%VPY%" -c "import torch,sys; ok=torch.cuda.is_available() and str(torch.version.cuda or '').startswith('12.8'); raise SystemExit(0 if ok else 1)" >nul 2>&1
if errorlevel 1 (
    echo Installing the CUDA 12.8 build of PyTorch...
    echo This is the largest download and may take a while.
    "%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128
    if errorlevel 1 (
        echo [X] CUDA PyTorch failed to install.
        echo     Parroty may still run with cloud voices, but local narration
        echo     will not have the intended GPU acceleration.
        set "FAILED=!FAILED! cuda-torch"
    )
) else (
    echo CUDA 12.8 PyTorch is already active - skipping the large reinstall.
)

REM ============================================================
REM 7) Verify and create shortcut
REM ============================================================
echo.
echo ----------------------------------------------------------
echo   [7/7] Verification and desktop shortcut
echo ----------------------------------------------------------

"%VPY%" -c "import flask, ebooklib, bs4, pydub, pdfplumber, docx, PIL, psutil; print('Core packages : OK')" 2>nul
if errorlevel 1 set "FAILED=!FAILED! core-verification"

"%VPY%" -c "import chatterbox; print('Chatterbox    : OK')" 2>nul
if errorlevel 1 echo Chatterbox    : unavailable

"%VPY%" -c "import torch; ok=torch.cuda.is_available(); print('PyTorch       :', torch.__version__); print('Built CUDA    :', torch.version.cuda); print('CUDA available:', ok); print('GPU           :', torch.cuda.get_device_name(0) if ok else 'CPU only')" 2>nul
if errorlevel 1 set "FAILED=!FAILED! torch-verification"

where ffmpeg >nul 2>&1 && echo ffmpeg       : OK || echo ffmpeg       : not currently on PATH

if exist "create_desktop_shortcut.vbs" (
    wscript.exe //nologo "%~dp0create_desktop_shortcut.vbs" /quiet
    echo Desktop shortcut: created/refreshed
) else (
    echo [!] Desktop shortcut helper is missing.
    set "WARNINGS=!WARNINGS! shortcut"
)

echo.
echo ==========================================================
if defined FAILED (
    echo   INSTALL FINISHED WITH PROBLEMS
    echo ==========================================================
    echo Failed components:!FAILED!
    echo.
    echo Re-run install_all.bat once. It is safe and repairs only
    echo missing or broken components.
) else (
    echo   INSTALL COMPLETE
    echo ==========================================================
    echo Parroty is ready.
)

if defined WARNINGS (
    echo.
    echo Warnings:!WARNINGS!
)

echo.
echo Use run.bat or the Parroty desktop shortcut to start.
echo The app opens in its own window with no PowerShell window.
echo.
echo For the strongest laptop background-GPU protection, run
echo fix_gpu.bat once as administrator after this installer.
echo.

if defined FAILED goto :finish

choice /C YN /N /M "Start Parroty now? [Y/N] "
if errorlevel 2 goto :finish
if errorlevel 1 (
    call run.bat
    exit /b 0
)

:finish
echo.
pause
exit /b 0

:refresh_path
set "SYSPATH="
set "USRPATH="
for /f "tokens=2,*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSPATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%B"
set "PATH=%SYSPATH%;%USRPATH%;%PATH%"
exit /b 0
