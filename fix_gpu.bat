@echo off
setlocal
title Parroty - fix GPU throttling

REM --- powercfg power-throttling + scheme changes need admin -------
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0"

echo ==========================================================
echo   Parroty - fix GPU throttling  (running as admin)
echo ==========================================================
echo.
echo Applies the same Windows-level fix used by Stemmy:
echo a High Performance power plan, plus a power-throttling
echo (EcoQoS) opt-out for the Python executables that run Parroty,
echo so Windows does not slow narration when PowerShell loses focus
echo or is minimized.
echo.

echo [1/2] Setting the High Performance power plan ...
powercfg /setactive SCHEME_MIN
if errorlevel 1 (echo       could not change the power plan.) else (echo       done.)
echo.

REM --- locate the virtual-environment Python Parroty actually runs --
set "PYEXE="
set "PYWEXE="
if exist "%~dp0venv\Scripts\python.exe" set "PYEXE=%~dp0venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\pythonw.exe" set "PYWEXE=%~dp0venv\Scripts\pythonw.exe"
if not defined PYEXE if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not defined PYWEXE if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYWEXE=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYEXE for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYEXE set "PYEXE=%%P"

echo [2/2] Disabling power throttling for Parroty ...
if not defined PYEXE (
  echo       no python.exe found - install Parroty first, then re-run this.
  goto :end
)

echo       target: %PYEXE%
powercfg /powerthrottling disable /path "%PYEXE%"
if errorlevel 1 (
  echo       this Windows build may not support per-app power-throttling
  echo       control; the High Performance plan above still helps.
) else (
  echo       python.exe opt-out applied.
)

if defined PYWEXE (
  echo       target: %PYWEXE%
  powercfg /powerthrottling disable /path "%PYWEXE%"
  if errorlevel 1 (
    echo       pythonw.exe opt-out could not be applied.
  ) else (
    echo       pythonw.exe opt-out applied.
  )
)

:end
echo.
echo ==========================================================
echo   Finished. Close and restart Parroty before testing.
echo.
echo   To undo later:
echo     powercfg /powerthrottling reset /path "the python.exe above"
echo     powercfg /setactive SCHEME_BALANCED
echo ==========================================================
echo.
pause
exit /b 0
