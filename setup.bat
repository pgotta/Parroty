@echo off
REM ============================================================
REM  Parroty - one-time setup
REM  Double-click this file (or run it in PowerShell/cmd) ONCE.
REM  It creates the virtual environment and installs everything,
REM  including Chatterbox (local voice cloning) + PyTorch with
REM  CUDA GPU support by default.
REM ============================================================

echo.
echo ===== Parroty setup =====
echo.

REM --- 0. Allow local scripts to run (so manual venv activation works) ---
powershell -NoProfile -Command "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force" >nul 2>nul

REM --- 1. Find Python 3.12 (fall back to whatever 'py'/'python' exists) ---
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYLAUNCH=py -3.12"
) else (
    set "PYLAUNCH=python"
)

echo Using: %PYLAUNCH%
echo.

REM --- 2. Create the venv if it doesn't already exist ---
if exist "venv\Scripts\python.exe" (
    echo Virtual environment already exists - reusing it.
) else (
    echo Creating virtual environment...
    %PYLAUNCH% -m venv venv
    if %errorlevel% neq 0 (
        echo.
        echo ERROR: could not create the venv. Is Python 3.12 installed?
        echo Download it from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

set "VPY=venv\Scripts\python.exe"

echo.
echo Upgrading pip...
"%VPY%" -m pip install --upgrade pip

echo.
echo Installing core requirements...
"%VPY%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: core requirements failed to install.
    pause
    exit /b 1
)

echo.
echo Installing Chatterbox (local voice cloning)...
REM Install chatterbox FIRST so its torch dependency is in place, then we
REM overwrite torch with the CUDA GPU build below. (If we installed torch
REM first, chatterbox's dependency resolver could replace it with CPU torch.)
"%VPY%" -m pip install chatterbox-tts

echo.
echo ============================================================
echo  Installing PyTorch with CUDA 12.8 GPU support (default)
echo  Large download (~2.5 GB). This enables fast GPU narration
echo  on NVIDIA cards. We install it LAST and force-reinstall so
echo  nothing can replace it with the slow CPU-only build.
echo ============================================================
"%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128
if %errorlevel% neq 0 (
    echo.
    echo CUDA 12.8 build failed. Trying the CUDA 12.4 build...
    "%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu124
    if %errorlevel% neq 0 (
        echo.
        echo GPU builds unavailable - falling back to CPU-only PyTorch.
        echo  ^(Narration will work but be slow. If you have an NVIDIA GPU,
        echo   see the README GPU section to install the CUDA build manually.^)
        "%VPY%" -m pip install torch torchaudio
    )
)

echo.
echo Verifying GPU availability...
"%VPY%" -c "import torch; ok=torch.cuda.is_available(); print('  PyTorch', torch.__version__); print('  GPU available:', ok); print('  GPU:', torch.cuda.get_device_name(0) if ok else '(CPU only)')"

echo.
echo ============================================================
echo  Setup complete!
echo  If 'GPU available' is True above, you're set for fast narration.
echo  To start Parroty, double-click run.bat
echo ============================================================
echo.
pause
