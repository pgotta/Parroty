@echo off
setlocal enabledelayedexpansion
set "PORT=5000"
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr LISTENING') do (
  taskkill /F /PID %%P >nul 2>&1
  set "FOUND=1"
)
if "!FOUND!"=="0" (
  echo Parroty was not running.
) else (
  echo Parroty stopped.
)
timeout /t 2 >nul
exit /b 0
