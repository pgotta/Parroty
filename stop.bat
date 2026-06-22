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
