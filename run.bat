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
