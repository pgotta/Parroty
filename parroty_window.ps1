param(
  [string]$Url = "http://127.0.0.1:5000",
  [string]$Root = $PSScriptRoot,
  [int]$Port = 5000
)

$ErrorActionPreference = "SilentlyContinue"

function Find-Browser {
  # Match Stemmy: prefer Edge for a clean dedicated app window, then Chrome.
  $candidates = @(
    "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  return $null
}

function Get-ParrotyBackendPids {
  param([int]$ListenerPort)

  # Capture the exact process already listening for Parroty before opening the
  # browser. When the app window closes we stop only these recorded PIDs, never
  # an unrelated process that might later reuse the port.
  $ids = [System.Collections.Generic.HashSet[int]]::new()

  try {
    Get-NetTCPConnection -LocalPort $ListenerPort -State Listen -ErrorAction Stop |
      ForEach-Object {
        if ($_.OwningProcess -gt 0) {
          [void]$ids.Add([int]$_.OwningProcess)
        }
      }
  } catch {}

  # Fallback for systems where Get-NetTCPConnection is unavailable or restricted.
  if ($ids.Count -eq 0) {
    try {
      $escapedPort = [regex]::Escape([string]$ListenerPort)
      $pattern = "^\s*TCP\s+\S+:$escapedPort\s+\S+\s+LISTENING\s+(\d+)\s*$"
      foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
        if ($line -match $pattern) {
          [void]$ids.Add([int]$Matches[1])
        }
      }
    } catch {}
  }

  return @($ids)
}

function Stop-ParrotyBackend {
  param([int[]]$ProcessIds)

  foreach ($backendProcessId in $ProcessIds) {
    if ($backendProcessId -le 0 -or $backendProcessId -eq $PID) { continue }
    try {
      Get-Process -Id $backendProcessId -ErrorAction Stop | Out-Null
      Stop-Process -Id $backendProcessId -Force -ErrorAction Stop
      try { Wait-Process -Id $backendProcessId -Timeout 5 -ErrorAction SilentlyContinue } catch {}
    } catch {}
  }
}

function Maximize-ParrotyWindow {
  param(
    [System.Diagnostics.Process]$InitialProcess,
    [string]$BrowserPath,
    [datetime]$LaunchTime
  )

  try {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ParrotyNativeWindow {
  [DllImport("user32.dll")]
  public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool IsWindow(IntPtr hWnd);
}
"@
  } catch {}

  $browserName = [System.IO.Path]::GetFileNameWithoutExtension($BrowserPath)
  $chosen = $null

  # Chromium can hand the app window to a child process. Wait for the newest
  # visible process created by this launch rather than maximizing ordinary
  # Chrome/Edge windows that were already open.
  for ($attempt = 0; $attempt -lt 80; $attempt++) {
    Start-Sleep -Milliseconds 250
    $visible = @(
      Get-Process -Name $browserName -ErrorAction SilentlyContinue |
      Where-Object {
        $_.MainWindowHandle -ne 0 -and
        $_.StartTime -ge $LaunchTime.AddSeconds(-5)
      } |
      Sort-Object StartTime -Descending
    )

    if ($visible.Count -gt 0) {
      $chosen = $visible[0]
      break
    }

    try {
      $InitialProcess.Refresh()
      if ($InitialProcess.MainWindowHandle -ne 0) {
        $chosen = $InitialProcess
        break
      }
    } catch {}
  }

  if ($chosen -and $chosen.MainWindowHandle -ne 0) {
    try {
      # SW_MAXIMIZE = 3. Repeat briefly because Chromium may apply its stored
      # app-window placement immediately after the first visible frame.
      for ($pass = 0; $pass -lt 5; $pass++) {
        [ParrotyNativeWindow]::ShowWindowAsync($chosen.MainWindowHandle, 3) | Out-Null
        [ParrotyNativeWindow]::SetForegroundWindow($chosen.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 300
        try { $chosen.Refresh() } catch {}
      }
    } catch {}
    return $chosen
  }

  return $InitialProcess
}

function Wait-ParrotyWindowClose {
  param(
    [IntPtr]$WindowHandle,
    [System.Diagnostics.Process]$WindowProcess
  )

  # Chrome and Edge may keep their process alive after an app-mode window is
  # closed. Watch the exact native window handle instead of waiting for the
  # Chromium process to exit.
  if ($WindowHandle -ne [IntPtr]::Zero) {
    while ($true) {
      $windowStillExists = $false
      try {
        $windowStillExists = [ParrotyNativeWindow]::IsWindow($WindowHandle)
      } catch {}

      if (-not $windowStillExists) { break }
      Start-Sleep -Milliseconds 250
    }
    return
  }

  # Last-resort fallback if Chromium never exposed a usable native handle.
  try { $WindowProcess.WaitForExit() } catch {}
}

$browser = Find-Browser
if (-not $browser) {
  # A normal browser tab cannot be reliably monitored for its close event, so
  # retain the browser fallback without automatic backend shutdown.
  Start-Process $Url
  exit 0
}

# Record the currently healthy Parroty listener before starting the app window.
# This mirrors stop.bat when the window later closes, while avoiding broad
# process-name matching or interference with normal browser windows.
$backendPids = @(Get-ParrotyBackendPids -ListenerPort $Port)

# A dedicated Chromium profile prevents an existing normal browser session from
# restoring Parroty to a remembered windowed size. This is the same launcher
# pattern used by Stemmy.
$profile = Join-Path $Root ".parroty-browser-profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$args = @(
  "--app=$Url",
  "--user-data-dir=$profile",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-background-mode",
  "--disable-session-crashed-bubble",
  "--start-maximized",
  "--window-position=0,0"
)

$launchTime = Get-Date
$process = Start-Process -FilePath $browser -ArgumentList $args -PassThru
if (-not $process) {
  Start-Process $Url
  exit 0
}

$windowProcess = Maximize-ParrotyWindow -InitialProcess $process -BrowserPath $browser -LaunchTime $launchTime
$windowHandle = [IntPtr]$windowProcess.MainWindowHandle
Set-Content -LiteralPath (Join-Path $Root ".parroty.browser.pid") -Value $windowProcess.Id

# Watch the actual Parroty app window. Closing it with X is treated the same as
# running stop.bat, even if Chromium keeps its process alive in the background.
Wait-ParrotyWindowClose -WindowHandle $windowHandle -WindowProcess $windowProcess
Remove-Item -LiteralPath (Join-Path $Root ".parroty.browser.pid") -Force -ErrorAction SilentlyContinue
Stop-ParrotyBackend -ProcessIds $backendPids
