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

All you need is the Parroty project folder, unzipped somewhere on your PC.

Parroty also needs Python 3.12 and ffmpeg installed on the machine. You can
either install those yourself:
  - Python 3.12     https://www.python.org/downloads/  (tick "Add to PATH")
  - ffmpeg          (see the README "Install ffmpeg" section)

...or just create install_all.bat below, which installs BOTH for you (via
winget) along with everything else. If you want the simplest possible path,
make install_all.bat and run.bat and skip the rest of this guide.

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
  THE ONES YOU ACTUALLY NEED
------------------------------------------------------------------------

EASIEST - two files, nothing else:

  install_all.bat - run ONCE. Installs Python, ffmpeg, the virtual
                    environment, every Python package, Chatterbox and GPU
                    PyTorch. Then offers to start Parroty for you.
  run.bat         - run EVERY time you want to start Parroty.

If you'd rather install Python and ffmpeg yourself, use setup.bat instead
of install_all.bat - it does the same thing minus those two prerequisites.
(You don't need both: install_all.bat is a superset of setup.bat.)

  setup.bat       - alternative to install_all.bat, assumes Python +
                    ffmpeg are already installed.
  run_hidden.bat  - optional: start Parroty with NO window at all. Use
                    instead of run.bat, AFTER installing.

Once they are created:
  - Double-click install_all.bat and wait for it to finish (it downloads a
    lot the first time, including the ~2.5 GB GPU build of PyTorch).
  - Then double-click run.bat. Chrome opens automatically at
    http://127.0.0.1:5000.
  - You can minimize the run.bat window; Parroty opts out of Windows
    background throttling so the GPU stays fast even when it isn't focused.
    Prefer no window at all? Use run_hidden.bat instead - Chrome still opens
    and all output is saved to parroty.log.
  - To stop, close the window or press Ctrl+C (or run stop.bat).


========================================================================
  FILE:  install_all.bat   (run once - installs EVERYTHING)
========================================================================

This is the recommended one. It installs Python and ffmpeg for you
(via winget), then the venv, all packages, Chatterbox and GPU PyTorch.
Safe to re-run - it skips whatever is already installed.

@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM  Parroty - INSTALL EVERYTHING (one file does it all)
REM
REM  Double-click this ONCE on a fresh Windows machine. It:
REM    1. Installs Python 3.12    (via winget, if missing)
REM    2. Installs ffmpeg         (via winget, if missing)
REM    3. Creates the virtual environment
REM    4. Installs all Python packages
REM    5. Installs Chatterbox + PyTorch with CUDA GPU support
REM    6. Verifies the install and offers to start Parroty
REM
REM  Safe to re-run: it skips anything already installed.
REM  This is a superset of setup.bat - you don't need both.
REM ============================================================

cd /d "%~dp0"
title Parroty - Install Everything

echo.
echo  ============================================================
echo   PARROTY - INSTALL EVERYTHING
echo  ============================================================
echo   This installs Python, ffmpeg, and all Parroty packages.
echo   Total download can be ~3-4 GB (mostly the GPU PyTorch).
echo   You only need to run this once.
echo  ============================================================
echo.

REM ---------- 0. Allow local scripts (for manual venv activation later) ----
powershell -NoProfile -Command "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force" >nul 2>nul

REM ---------- 0b. Is winget available? (Win10 1809+ / Win11 have it) -------
set "HAVE_WINGET="
where winget >nul 2>nul && set "HAVE_WINGET=1"
if not defined HAVE_WINGET (
    echo  [!] winget not found - cannot auto-install Python/ffmpeg.
    echo      Windows 11 and recent Windows 10 include it via "App Installer".
    echo      This script will still set up everything else, but you must
    echo      install any missing prerequisites manually:
    echo        Python 3.12 : https://www.python.org/downloads/
    echo        ffmpeg      : https://www.gyan.dev/ffmpeg/builds/
    echo.
)

REM =========================================================================
echo  [1/6] Checking Python...
REM =========================================================================
set "PYLAUNCH="
py -3.12 --version >nul 2>nul && set "PYLAUNCH=py -3.12"
if not defined PYLAUNCH (
    py -3 --version >nul 2>nul && set "PYLAUNCH=py -3"
)
if not defined PYLAUNCH (
    python --version >nul 2>nul && set "PYLAUNCH=python"
)

if not defined PYLAUNCH (
    if defined HAVE_WINGET (
        echo      Python not found - installing Python 3.12 via winget...
        winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
        REM winget updates PATH for NEW processes; refresh ours so we can use it now.
        call :refresh_path
        py -3.12 --version >nul 2>nul && set "PYLAUNCH=py -3.12"
        if not defined PYLAUNCH (
            python --version >nul 2>nul && set "PYLAUNCH=python"
        )
        if not defined PYLAUNCH (
            echo.
            echo  [X] Python was installed but this window can't see it yet.
            echo      CLOSE this window and run install_all.bat again - it will
            echo      pick up from here. ^(Windows needs a fresh window for the
            echo      updated PATH.^)
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo  [X] Python 3.12 is required. Install it, then re-run this file:
        echo      https://www.python.org/downloads/
        echo      IMPORTANT: tick "Add python.exe to PATH" in the installer.
        echo.
        pause
        exit /b 1
    )
)
for /f "delims=" %%v in ('%PYLAUNCH% --version 2^>^&1') do echo      Found: %%v
echo.

REM =========================================================================
echo  [2/6] Checking ffmpeg...
REM =========================================================================
where ffmpeg >nul 2>nul
if %errorlevel%==0 (
    echo      Found: ffmpeg already installed.
) else (
    if defined HAVE_WINGET (
        echo      ffmpeg not found - installing via winget...
        winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        call :refresh_path
        where ffmpeg >nul 2>nul
        if !errorlevel!==0 (
            echo      Installed: ffmpeg.
        ) else (
            echo.
            echo      [!] ffmpeg installed but not visible in this window yet.
            echo          Parroty needs it to combine audio and build MP4s.
            echo          After this finishes, CLOSE this window and open a new
            echo          one - ffmpeg will be on PATH then.
        )
    ) else (
        echo      [!] ffmpeg missing and winget unavailable. Install it from
        echo          https://www.gyan.dev/ffmpeg/builds/ and add it to PATH.
        echo          ^(Narration works without it, but combining audio and
        echo           building the MP4 will fail.^)
    )
)
echo.

REM =========================================================================
echo  [3/6] Creating the virtual environment...
REM =========================================================================
if exist "venv\Scripts\python.exe" (
    echo      Virtual environment already exists - reusing it.
) else (
    %PYLAUNCH% -m venv venv
    if !errorlevel! neq 0 (
        echo.
        echo  [X] Could not create the virtual environment.
        echo.
        pause
        exit /b 1
    )
    echo      Created: venv
)
set "VPY=venv\Scripts\python.exe"
echo.

REM =========================================================================
echo  [4/6] Installing Parroty's Python packages...
REM =========================================================================
"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo.
    echo  [X] Core requirements failed to install. Scroll up for the reason.
    echo.
    pause
    exit /b 1
)
echo      Core packages installed.
echo.

REM =========================================================================
echo  [5/6] Installing the local voice engine + GPU PyTorch...
REM       (Chatterbox FIRST so its torch dependency lands, then we force the
REM        CUDA build over the top - otherwise pip can leave you on CPU torch.)
REM =========================================================================
echo      Installing Chatterbox ^(local voice cloning^)...
"%VPY%" -m pip install chatterbox-tts

echo.
echo      Installing PyTorch with CUDA 12.8 GPU support...
echo      ^(Large download ~2.5 GB - this is the slow part.^)
"%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128
if !errorlevel! neq 0 (
    echo.
    echo      CUDA 12.8 build failed - trying CUDA 12.4...
    "%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu124
    if !errorlevel! neq 0 (
        echo.
        echo      GPU builds unavailable - falling back to CPU-only PyTorch.
        echo      ^(Narration will work but be much slower.^)
        "%VPY%" -m pip install torch torchaudio
    )
)
echo.

REM =========================================================================
echo  [6/6] Verifying the install...
REM =========================================================================
echo.
"%VPY%" -c "import flask, ebooklib, bs4, pydub; print('  Core packages : OK')" 2>nul || echo   Core packages : FAILED
"%VPY%" -c "import chatterbox; print('  Chatterbox    : OK')" 2>nul || echo   Chatterbox    : not installed (cloud voices still work)
"%VPY%" -c "import torch; ok=torch.cuda.is_available(); print('  PyTorch       :', torch.__version__); print('  GPU available :', ok); print('  GPU           :', torch.cuda.get_device_name(0) if ok else '(CPU only - narration will be slow)')" 2>nul || echo   PyTorch       : FAILED
where ffmpeg >nul 2>nul && echo   ffmpeg        : OK || echo   ffmpeg        : NOT on PATH (open a new window, or install it)
echo.

echo  ============================================================
echo   INSTALL COMPLETE
echo  ============================================================
echo   If "GPU available" says True, you're set for fast narration.
echo   If it says False but you have an NVIDIA card, run fix_gpu.bat.
echo.
echo   From now on, just double-click run.bat to start Parroty.
echo  ============================================================
echo.

choice /C YN /N /M "  Start Parroty now? [Y/N] "
if errorlevel 2 goto :finish
if errorlevel 1 (
    echo.
    echo   Starting Parroty...
    call run.bat
    exit /b 0
)

:finish
echo.
echo   Done. Double-click run.bat whenever you want to start Parroty.
echo.
pause
exit /b 0

REM =========================================================================
:refresh_path
REM Re-read PATH from the registry so tools winget just installed are usable
REM in THIS window (winget only updates PATH for newly-created processes).
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "SYSPATH=%%B"
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "USRPATH=%%B"
set "PATH=%SYSPATH%;%USRPATH%"
exit /b 0


========================================================================
  FILE:  setup.bat        (alternative: assumes Python + ffmpeg)
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

  run_hidden.bat - optional: start Parroty with no window at all (see the
                   run instructions above). Use instead of run.bat.
  stop.bat       - stops a running Parroty server.
  check_gpu.bat  - shows whether your GPU is being used.
  fix_gpu.bat    - reinstalls the GPU build of PyTorch if it fell back
                   to CPU (run this if check_gpu shows "GPU available: False"
                   but you have an NVIDIA card).


========================================================================
  FILE:  run_hidden.bat  (optional - start with no window, full GPU speed)
========================================================================

@echo off
REM ============================================================
REM  Parroty - start HIDDEN (no console window).
REM  Runs the server with pythonw.exe, so nothing shows on screen
REM  and there is no window to keep in the foreground. The app
REM  opts out of Windows background throttling itself, so the GPU
REM  still runs at full speed.
REM
REM  Chrome still opens at http://127.0.0.1:5000, and all output
REM  is saved to parroty.log. To stop it, use stop.bat (or end
REM  "pythonw.exe" in Task Manager).
REM
REM  Run this AFTER setup.bat - it's an alternative to run.bat,
REM  not a replacement for setup.
REM ============================================================

cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo No virtual environment found. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

REM Tell the server it's running windowless so it logs to parroty.log.
set "PARROTY_HIDDEN=1"

REM Launch windowless and detached; this launcher then exits, leaving no window.
start "" "%CD%\venv\Scripts\pythonw.exe" -m app.server

exit /b 0


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
