from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str, *, crlf: bool = False) -> None:
    target = ROOT / path
    if crlf:
        normalized = text.replace("\r\n", "\n")
        with target.open("w", encoding="utf-8", newline="") as file:
            file.write(normalized.replace("\n", "\r\n"))
    else:
        target.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Expected text not found while updating {label}")
    return text.replace(old, new, 1)


def update_window_launcher() -> None:
    path = "parroty_window.ps1"
    text = read(path)

    old_stop = '''function Stop-ParrotyBackend {
  param([int[]]$ProcessIds)

  foreach ($backendProcessId in $ProcessIds) {
    if ($backendProcessId -le 0 -or $backendProcessId -eq $PID) { continue }
    try {
      Get-Process -Id $backendProcessId -ErrorAction Stop | Out-Null
      Stop-Process -Id $backendProcessId -Force -ErrorAction Stop
      try { Wait-Process -Id $backendProcessId -Timeout 5 -ErrorAction SilentlyContinue } catch {}
    } catch {}
  }
}'''
    new_stop = '''function Stop-ParrotyBackend {
  param([int[]]$ProcessIds)

  foreach ($backendProcessId in $ProcessIds) {
    if ($backendProcessId -le 0 -or $backendProcessId -eq $PID) { continue }

    # Stop-Process kills only the Flask parent on Windows and can leave active
    # app.narrate_worker children orphaned. taskkill /T terminates the complete
    # Parroty process tree while the parent relationship still exists.
    try {
      & taskkill.exe /PID $backendProcessId /T /F *> $null
    } catch {}

    try {
      Wait-Process -Id $backendProcessId -Timeout 5 -ErrorAction SilentlyContinue
    } catch {}
  }
}'''
    text = replace_once(text, old_stop, new_stop, path)

    old_native = '''  [DllImport("user32.dll")]
  public static extern bool IsWindow(IntPtr hWnd);
}'''
    new_native = '''  [DllImport("user32.dll")]
  public static extern bool IsWindow(IntPtr hWnd);

  [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  public static extern IntPtr LoadImage(
    IntPtr hInst,
    string name,
    uint type,
    int cx,
    int cy,
    uint loadFlags
  );

  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern IntPtr SendMessage(
    IntPtr hWnd,
    uint message,
    IntPtr wParam,
    IntPtr lParam
  );
}'''
    text = replace_once(text, old_native, new_native, path)

    helper = '''function Set-ParrotyWindowIcon {
  param(
    [IntPtr]$WindowHandle,
    [string]$IconPath
  )

  if ($WindowHandle -eq [IntPtr]::Zero) { return }
  if (-not (Test-Path -LiteralPath $IconPath)) { return }

  try {
    $IMAGE_ICON = 1
    $LR_LOADFROMFILE = 0x10
    $WM_SETICON = 0x0080
    $ICON_SMALL = 0
    $ICON_BIG = 1

    $smallIcon = [ParrotyNativeWindow]::LoadImage(
      [IntPtr]::Zero, $IconPath, $IMAGE_ICON, 16, 16, $LR_LOADFROMFILE
    )
    $largeIcon = [ParrotyNativeWindow]::LoadImage(
      [IntPtr]::Zero, $IconPath, $IMAGE_ICON, 48, 48, $LR_LOADFROMFILE
    )

    if ($smallIcon -ne [IntPtr]::Zero) {
      [ParrotyNativeWindow]::SendMessage(
        $WindowHandle, $WM_SETICON, [IntPtr]$ICON_SMALL, $smallIcon
      ) | Out-Null
    }
    if ($largeIcon -ne [IntPtr]::Zero) {
      [ParrotyNativeWindow]::SendMessage(
        $WindowHandle, $WM_SETICON, [IntPtr]$ICON_BIG, $largeIcon
      ) | Out-Null
    }
  } catch {}
}

'''
    marker = "function Maximize-ParrotyWindow {"
    if "function Set-ParrotyWindowIcon" not in text:
        if marker not in text:
            raise RuntimeError("Maximize-ParrotyWindow marker not found")
        text = text.replace(marker, helper + marker, 1)

    old_loop = '''        [ParrotyNativeWindow]::ShowWindowAsync($chosen.MainWindowHandle, 3) | Out-Null
        [ParrotyNativeWindow]::SetForegroundWindow($chosen.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 300'''
    new_loop = '''        [ParrotyNativeWindow]::ShowWindowAsync($chosen.MainWindowHandle, 3) | Out-Null
        [ParrotyNativeWindow]::SetForegroundWindow($chosen.MainWindowHandle) | Out-Null
        Set-ParrotyWindowIcon -WindowHandle $chosen.MainWindowHandle -IconPath (Join-Path $Root "parroty.ico")
        Start-Sleep -Milliseconds 300'''
    text = replace_once(text, old_loop, new_loop, path)
    write(path, text)


def update_template_and_icon() -> None:
    path = "app/templates/index.html"
    text = read(path)
    old = "<title>Parroty — EPUB to Audiobook</title>"
    new = '''<title>Parroty — EPUB to Audiobook</title>
<meta name="application-name" content="Parroty">
<link rel="icon" type="image/x-icon" href="/static/parroty.ico?v=20260723">
<link rel="shortcut icon" type="image/x-icon" href="/static/parroty.ico?v=20260723">'''
    text = replace_once(text, old, new, path)
    text = text.replace(
        "Bundled male/female voices that run fully offline. Click Preview below to hear them.",
        "Eight reviewed audiobook voices that run fully offline. Click Preview below to hear them.",
    )
    write(path, text)

    static_icon = ROOT / "app/static/parroty.ico"
    static_icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "parroty.ico", static_icon)


def stop_bat_template() -> str:
    return r'''@echo off
setlocal
cd /d "%~dp0"
title Stop Parroty

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root=[IO.Path]::GetFullPath('%CD%');" ^
  "$targets=New-Object 'System.Collections.Generic.HashSet[int]';" ^
  "try { Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop | ForEach-Object { if ($_.OwningProcess -gt 0) { [void]$targets.Add([int]$_.OwningProcess) } } } catch {};" ^
  "Get-CimInstance Win32_Process | Where-Object {" ^
  "  $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and (" ^
  "    ($_.CommandLine -like ('*' + $root + '*launch_parroty.pyw*')) -or" ^
  "    ($_.CommandLine -like ('*' + $root + '*-m app.narrate_worker*')) -or" ^
  "    ($_.CommandLine -like ('*' + $root + '*-m app.server*'))" ^
  "  )" ^
  "} | ForEach-Object { [void]$targets.Add([int]$_.ProcessId) };" ^
  "if ($targets.Count -eq 0) { Write-Host 'Parroty was not running.'; exit 0 };" ^
  "$ordered=@($targets) | Sort-Object -Descending;" ^
  "foreach ($id in $ordered) { & taskkill.exe /PID $id /T /F 2>$null | Out-Null };" ^
  "Remove-Item -LiteralPath (Join-Path $root '.parroty.browser.pid') -Force -ErrorAction SilentlyContinue;" ^
  "Write-Host 'Parroty stopped, including active narration workers.'"

timeout /t 2 >nul
exit /b 0'''


def update_quick_start() -> None:
    path = "Quick Start Readme.txt"
    text = read(path)
    text = replace_once(
        text,
        "No API key or separate voice download is required. Closing the dedicated\nParroty Chrome/Edge app window with X automatically stops the hidden backend.",
        "No API key or separate voice download is required. The dedicated Parroty\nChrome/Edge app window uses the bird icon in its title bar and taskbar. Closing\nit with X stops Flask and any active narration workers.",
        path,
    )

    start = text.index("@echo off", text.index("FILE: stop.bat"))
    end_marker = "\n\n========================================================================\n  FILE: run_debug.bat"
    end = text.index(end_marker, start)
    text = text[:start] + stop_bat_template() + text[end:]

    text = text.replace(
        "3. Close the Parroty app window with X to stop the hidden backend automatically.\n"
        "4. Use stop.bat only if the window is already gone or a forced stop is needed.",
        "3. Close the Parroty app window with X to stop Flask and active narration workers.\n"
        "4. Use stop.bat if the window is already gone or a forced full stop is needed.",
    )
    write(path, text, crlf=True)


def update_readme() -> None:
    path = "README.md"
    text = read(path)
    highlight = (
        "- **Runs entirely on your own machine** — your files and (for the local engine)\n"
        "  your audio never leave your computer."
    )
    replacement = highlight + (
        "\n- **Windows desktop-app behavior:** opens maximized with the Parroty bird icon in\n"
        "  the window and taskbar; closing X stops Flask and active narration workers."
    )
    text = replace_once(text, highlight, replacement, path)

    old_running = (
        "Parroty in a dedicated maximized Chrome/Edge app window, and silently creates or\n"
        "refreshes the desktop shortcut. Closing that Parroty app window with **X** now\n"
        "automatically stops the hidden Flask backend, the same result as running\n"
        "`stop.bat`. Output goes to `parroty.log`; `stop.bat` remains available as a\n"
        "fallback if the window is already gone or the backend needs to be forced closed.\n"
        "These `.bat` files are deliberately ignored by Git."
    )
    new_running = (
        "Parroty in a dedicated maximized Chrome/Edge app window, applies the Parroty bird\n"
        "icon to the native window and taskbar button, and silently creates or refreshes\n"
        "the desktop shortcut. Closing that app window with **X** terminates the complete\n"
        "Parroty process tree—including an active `app.narrate_worker`—rather than only\n"
        "closing the port-5000 Flask parent. Output goes to `parroty.log`; `stop.bat` uses\n"
        "the same full-tree behavior and can also find orphaned Parroty workers if the\n"
        "listener is already gone. These `.bat` files are deliberately ignored by Git."
    )
    text = replace_once(text, old_running, new_running, path)
    write(path, text)


def update_build() -> None:
    path = "BUILD.md"
    text = read(path)
    text = replace_once(
        text,
        "tracked launcher helpers, `parroty.ico`, documentation, and `LICENSE`.",
        "tracked launcher helpers, `parroty.ico`, `app/static/parroty.ico`, documentation,\n"
        "and `LICENSE`.",
        path,
    )
    text = replace_once(
        text,
        "After installation, verify the monitor identifies CUDA/NVIDIA, the app opens in\n"
        "a dedicated maximized window without a visible console, and closing that app\n"
        "window with X stops the Flask listener and releases port 5000. Also verify the\n"
        "desktop shortcut uses `parroty.ico`, all eight voices appear, previews work, and\n"
        "`stop.bat` still shuts down port 5000 as a fallback.",
        "After installation, verify the monitor identifies CUDA/NVIDIA and the app opens in\n"
        "a dedicated maximized window without a visible console. Confirm the desktop\n"
        "shortcut, native app window, and taskbar button all use `parroty.ico`. Start a\n"
        "short narration, close the app window with X, and verify the Flask listener and\n"
        "every `app.narrate_worker` process exit. Also verify the generated `stop.bat` can\n"
        "find and stop Parroty workers even when port 5000 is no longer listening. Finally,\n"
        "confirm all eight voices appear and previews work.",
        path,
    )
    write(path, text)


def update_release_notes() -> None:
    path = "RELEASE_NOTES.md"
    text = read(path)
    old = (
        "- Closing the dedicated Parroty app window now automatically stops the hidden\n"
        "  Flask backend, matching `stop.bat` behavior without affecting normal browser windows.\n"
        "- Corrected that shutdown detection to monitor the exact native Parroty window\n"
        "  handle rather than waiting for the Chromium process, which may remain alive\n"
        "  after its app window is closed."
    )
    new = (
        "- Closing the dedicated Parroty app window now monitors the exact native window\n"
        "  handle and terminates the complete Parroty process tree, including active\n"
        "  `app.narrate_worker` children that Windows would otherwise leave orphaned.\n"
        "- Updated the local `stop.bat` template to detect both the port-5000 listener and\n"
        "  Parroty launcher/server/narration workers, preventing false “not running” reports.\n"
        "- Added the Parroty bird favicon and applies `parroty.ico` directly to the native\n"
        "  Chrome/Edge app window so the title bar and Windows taskbar show the app icon."
    )
    text = replace_once(text, old, new, path)
    write(path, text)


def main() -> None:
    update_window_launcher()
    update_template_and_icon()
    update_quick_start()
    update_readme()
    update_build()
    update_release_notes()
    print("Applied confirmed shutdown, icon, and documentation updates")


if __name__ == "__main__":
    main()
