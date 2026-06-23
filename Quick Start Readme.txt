========================================================================
  PARROTY - QUICK START (optional double-click launchers)
========================================================================

Parroty runs from the command line (see the main README for full setup).
If you would rather start it by double-clicking instead of typing commands,
you can create a few small "batch files" (.bat) yourself. This guide shows
you how, and gives you the exact contents to paste.

These launchers are OPTIONAL and purely for convenience - Parroty works
fine without them.


------------------------------------------------------------------------
  BEFORE YOU START
------------------------------------------------------------------------

You need these one-time, machine-wide installs first:
  - Python 3.12     https://www.python.org/downloads/  (tick "Add to PATH")
  - ffmpeg          (see the README "Install ffmpeg" section)
  - The Parroty project folder, unzipped somewhere on your PC.

Create the .bat files INSIDE the Parroty folder - the same folder that
contains the "app" folder and requirements.txt.


------------------------------------------------------------------------
  HOW TO CREATE A .BAT FILE
------------------------------------------------------------------------

  1. Open Notepad.
  2. Copy one of the blocks below and paste it into Notepad.
  3. Click File > Save As...
  4. In the "Save as type" dropdown, choose "All Files (*.*)".
       (This step matters - otherwise Windows saves it as a .txt and it
        will not run.)
  5. Name it exactly as shown (for example:  setup.bat ) and save it
     inside the Parroty folder.
  6. Repeat for each file you want to create.


------------------------------------------------------------------------
  THE TWO YOU ACTUALLY NEED
------------------------------------------------------------------------

  setup.bat  - run ONCE to install everything.
  run.bat    - run EVERY time you want to start Parroty.

Once they are created:
  - Double-click setup.bat and wait for it to finish (it downloads a lot
    the first time, including the GPU build of PyTorch).
  - Then double-click run.bat. Chrome opens automatically at
    http://127.0.0.1:5000.
  - Keep the run.bat window open while narrating. You can minimize it, but
    for full GPU speed keep it in the foreground.
  - To stop, close the window or press Ctrl+C.


========================================================================
  FILE:  setup.bat        (run once - installs everything)
========================================================================

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


========================================================================
  FILE:  run.bat          (run every time - starts Parroty)
========================================================================

@echo off
REM ============================================================
REM  Parroty - start the app (VISIBLE console, foreground)
REM  Double-click to launch. Chrome opens automatically at
REM  http://127.0.0.1:5000. Keep this window open while using
REM  Parroty. All output is also saved to parroty.log so you can
REM  see what happened if it ever stops unexpectedly.
REM ============================================================

cd /d "%~dp0"

REM Name the console window "Parroty".
title Parroty

if not exist "venv\Scripts\python.exe" (
    echo.
    echo No virtual environment found. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

REM Disable console QuickEdit Mode so clicking in the window doesn't pause it.
powershell -NoProfile -Command "$sig='[DllImport(\"kernel32.dll\")]public static extern IntPtr GetStdHandle(int h);[DllImport(\"kernel32.dll\")]public static extern bool GetConsoleMode(IntPtr h,out uint m);[DllImport(\"kernel32.dll\")]public static extern bool SetConsoleMode(IntPtr h,uint m);'; $t=Add-Type -MemberDefinition $sig -Name K -Namespace W -PassThru; $h=$t::GetStdHandle(-10); $m=0; [void]$t::GetConsoleMode($h,[ref]$m); [void]$t::SetConsoleMode($h, ($m -bor 0x0080) -band (-bnot 0x0040))" 2>nul

REM Set this process to HIGH priority so background throttling doesn't starve
REM GPU work (the app also does this itself, but set it here too).
wmic process where "name='cmd.exe' and ProcessId=%~1" CALL setpriority 128 >nul 2>nul

echo Starting Parroty...  (Chrome will open shortly)
echo.
echo   Keep this window open while narrating. You can minimize it,
echo   but for full GPU speed keep it in the foreground.
echo   Watch progress in the browser.
echo   A copy of all messages is saved to parroty.log
echo.

REM Run in the SAME console (foreground = full GPU priority). Tee output to
REM parroty.log AND the screen via PowerShell Tee-Object, so if the server
REM crashes the reason is captured in the log even though the window may close.
REM ($host.UI sets the window title to "Parroty" since PowerShell can reset it.)
title Parroty
powershell -NoProfile -Command "$host.UI.RawUI.WindowTitle='Parroty'; & '%CD%\venv\Scripts\python.exe' -m app.server 2>&1 | Tee-Object -FilePath '%CD%\parroty.log'"

REM If we reach here, the server stopped (crash or Ctrl+C). Keep the window
REM open so any error message stays visible, and point at the log.
echo.
echo ============================================================
echo  Parroty has stopped.
echo  If this was unexpected, the full output is saved in:
echo     %CD%\parroty.log
echo  Scroll up to see the error, or open parroty.log.
echo ============================================================
echo.
pause


------------------------------------------------------------------------
  OPTIONAL EXTRAS
------------------------------------------------------------------------

  stop.bat       - stops a running Parroty server.
  check_gpu.bat  - shows whether your GPU is being used.
  fix_gpu.bat    - reinstalls the GPU build of PyTorch if it fell back
                   to CPU (run this if check_gpu shows "GPU available: False"
                   but you have an NVIDIA card).


========================================================================
  FILE:  stop.bat
========================================================================

@echo off
REM ============================================================
REM  Stop the Parroty background server.
REM ============================================================
echo Stopping Parroty...

REM Find the process listening on port 5000 and kill it.
set FOUND=
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)

if defined FOUND (
    echo Parroty has been stopped.
) else (
    echo Parroty does not appear to be running.
)
echo.
timeout /t 4 >nul


========================================================================
  FILE:  check_gpu.bat
========================================================================

@echo off
REM ============================================================
REM  Parroty - GPU check
REM  Double-click to see whether PyTorch can use your GPU.
REM ============================================================
if not exist "venv\Scripts\python.exe" (
    echo No virtual environment found. Run setup.bat first.
    pause
    exit /b 1
)
echo Checking PyTorch / GPU status...
echo.
"venv\Scripts\python.exe" -c "import torch; ok=torch.cuda.is_available(); print('PyTorch version :', torch.__version__); print('Built with CUDA :', torch.version.cuda); print('GPU available   :', ok); print('GPU name        :', torch.cuda.get_device_name(0) if ok else '(none - will use CPU)')"
echo.
echo If 'GPU available' is False but you have an NVIDIA card, reinstall the
echo CUDA build (see fix_gpu.bat below, or the README GPU section).
echo.
pause


========================================================================
  FILE:  fix_gpu.bat
========================================================================

@echo off
REM ============================================================
REM  Restore GPU (CUDA) PyTorch if setup installed the CPU build.
REM  Run this if check_gpu.bat shows "GPU available: False" but
REM  you have an NVIDIA card.
REM ============================================================
echo.
echo Reinstalling PyTorch with CUDA 12.8 GPU support...
echo (Large download ~2.5 GB)
echo.

set "VPY=venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo No venv found. Run setup.bat first.
    pause
    exit /b 1
)

"%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128
if %errorlevel% neq 0 (
    echo CUDA 12.8 failed, trying CUDA 12.4...
    "%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu124
)

echo.
echo Verifying...
"%VPY%" -c "import torch; ok=torch.cuda.is_available(); print('PyTorch', torch.__version__); print('GPU available:', ok); print('GPU:', torch.cuda.get_device_name(0) if ok else '(CPU only)')"
echo.
pause


========================================================================
  That's everything. Once setup.bat and run.bat exist in your Parroty
  folder, starting the app is just a double-click.
========================================================================
