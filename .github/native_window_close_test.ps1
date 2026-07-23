$ErrorActionPreference = "Stop"

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path "parroty_window.ps1"),
  [ref]$tokens,
  [ref]$errors
)
if ($errors.Count -gt 0) { throw "PowerShell parser errors found" }

$functions = $ast.FindAll({
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true)
foreach ($function in $functions) {
  Invoke-Expression $function.Extent.Text
}

$script:windowChecks = 0
$simulatedWindow = {
  param([IntPtr]$Handle)
  Write-Host "Predicate check $($script:windowChecks + 1), handle=$([int64]$Handle)"
  if ([int64]$Handle -ne 12345) { throw "Unexpected test handle: $([int64]$Handle)" }
  $script:windowChecks++
  return ($script:windowChecks -lt 5)
}

$hostProcess = [System.Diagnostics.Process]::GetCurrentProcess()
$testHandle = [IntPtr]::new(12345)
$watch = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "Calling watcher with PID $($hostProcess.Id)..."
Wait-ParrotyWindowClose `
  -WindowHandle $testHandle `
  -WindowProcess $hostProcess `
  -WindowExists $simulatedWindow `
  -PollMilliseconds 25
$watch.Stop()

Write-Host "Watcher returned after $($watch.Elapsed.TotalMilliseconds) ms and $script:windowChecks checks"
if ($script:windowChecks -ne 5) {
  throw "Watcher did not poll until the window disappeared: $script:windowChecks checks"
}
if ($watch.Elapsed.TotalMilliseconds -lt 70 -or $watch.Elapsed.TotalSeconds -gt 2) {
  throw "Watcher timing was unexpected: $($watch.Elapsed.TotalMilliseconds) ms"
}
if (-not (Get-Process -Id $hostProcess.Id -ErrorAction SilentlyContinue)) {
  throw "Host process exited even though only the window disappeared"
}

Write-Host "Direct watcher test passed."
