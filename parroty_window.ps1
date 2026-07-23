param(
  [string]$Url = "http://127.0.0.1:5000",
  [string]$Root = $PSScriptRoot
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

$browser = Find-Browser
if (-not $browser) {
  Start-Process $Url
  exit 0
}

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
Set-Content -LiteralPath (Join-Path $Root ".parroty.browser.pid") -Value $windowProcess.Id

try { $windowProcess.WaitForExit() } catch {}
Remove-Item -LiteralPath (Join-Path $Root ".parroty.browser.pid") -Force -ErrorAction SilentlyContinue
