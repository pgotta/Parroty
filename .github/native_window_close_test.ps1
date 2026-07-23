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

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ParrotyNativeWindow {
  [DllImport("user32.dll")]
  public static extern bool IsWindow(IntPtr hWnd);
}
"@

$work = Join-Path $env:RUNNER_TEMP "parroty-native-host"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$hostExe = Join-Path $work "NativeWindowHost.exe"
$handleFile = Join-Path $work "handle.txt"

$source = @"
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

public static class Program {
  private const uint WM_CLOSE = 0x0010;
  private const uint WM_DESTROY = 0x0002;
  private static readonly IntPtr HWND_MESSAGE = new IntPtr(-3);
  private delegate IntPtr WndProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  private static readonly WndProc WindowProcedure = HandleMessage;

  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  private struct WNDCLASS {
    public uint style;
    public WndProc lpfnWndProc;
    public int cbClsExtra;
    public int cbWndExtra;
    public IntPtr hInstance;
    public IntPtr hIcon;
    public IntPtr hCursor;
    public IntPtr hbrBackground;
    [MarshalAs(UnmanagedType.LPWStr)] public string lpszMenuName;
    [MarshalAs(UnmanagedType.LPWStr)] public string lpszClassName;
  }

  [StructLayout(LayoutKind.Sequential)]
  private struct POINT {
    public int x;
    public int y;
  }

  [StructLayout(LayoutKind.Sequential)]
  private struct MSG {
    public IntPtr hwnd;
    public uint message;
    public UIntPtr wParam;
    public IntPtr lParam;
    public uint time;
    public POINT pt;
    public uint lPrivate;
  }

  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
  private static extern IntPtr GetModuleHandle(string moduleName);

  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  private static extern ushort RegisterClass(ref WNDCLASS windowClass);

  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  private static extern IntPtr CreateWindowEx(
    uint exStyle, string className, string windowName, uint style,
    int x, int y, int width, int height, IntPtr parent, IntPtr menu,
    IntPtr instance, IntPtr parameter);

  [DllImport("user32.dll")]
  private static extern bool DestroyWindow(IntPtr hWnd);

  [DllImport("user32.dll")]
  private static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

  [DllImport("user32.dll")]
  private static extern void PostQuitMessage(int exitCode);

  [DllImport("user32.dll")]
  private static extern int GetMessage(out MSG message, IntPtr hWnd, uint min, uint max);

  [DllImport("user32.dll")]
  private static extern bool TranslateMessage(ref MSG message);

  [DllImport("user32.dll")]
  private static extern IntPtr DispatchMessage(ref MSG message);

  [DllImport("user32.dll")]
  private static extern IntPtr DefWindowProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

  public static int Main(string[] args) {
    if (args.Length != 1) return 2;

    string className = "ParrotyNativeHost_" + Guid.NewGuid().ToString("N");
    WNDCLASS windowClass = new WNDCLASS {
      lpfnWndProc = WindowProcedure,
      hInstance = GetModuleHandle(null),
      lpszClassName = className
    };
    if (RegisterClass(ref windowClass) == 0) return 3;

    IntPtr windowHandle = CreateWindowEx(
      0, className, "Parroty regression window", 0,
      0, 0, 0, 0, HWND_MESSAGE, IntPtr.Zero,
      windowClass.hInstance, IntPtr.Zero);
    if (windowHandle == IntPtr.Zero) return 4;

    File.WriteAllText(args[0], windowHandle.ToInt64().ToString());

    Thread closer = new Thread(() => {
      Thread.Sleep(1000);
      PostMessage(windowHandle, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
    });
    closer.IsBackground = true;
    closer.Start();

    MSG message;
    while (GetMessage(out message, IntPtr.Zero, 0, 0) > 0) {
      TranslateMessage(ref message);
      DispatchMessage(ref message);
    }

    // The native window is gone, but the host process deliberately remains alive.
    Thread.Sleep(4000);
    return 0;
  }

  private static IntPtr HandleMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam) {
    if (msg == WM_CLOSE) {
      DestroyWindow(hWnd);
      return IntPtr.Zero;
    }
    if (msg == WM_DESTROY) {
      PostQuitMessage(0);
      return IntPtr.Zero;
    }
    return DefWindowProc(hWnd, msg, wParam, lParam);
  }
}
"@

Write-Host "Compiling native host..."
Add-Type -TypeDefinition $source -Language CSharp -OutputAssembly $hostExe -OutputType ConsoleApplication

Write-Host "Starting native host..."
$host = Start-Process -FilePath $hostExe -ArgumentList $handleFile -PassThru -WindowStyle Hidden
try {
  for ($i = 0; $i -lt 40 -and -not (Test-Path $handleFile); $i++) {
    Start-Sleep -Milliseconds 250
  }
  if (-not (Test-Path $handleFile)) {
    throw "Native host did not publish a window handle. Exit code: $($host.ExitCode)"
  }

  $handle = [IntPtr][int64](Get-Content $handleFile -Raw)
  Write-Host "Native handle: $([int64]$handle), host PID: $($host.Id)"
  if (-not [ParrotyNativeWindow]::IsWindow($handle)) {
    throw "Native test handle is not a live window"
  }

  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  Wait-ParrotyWindowClose -WindowHandle $handle -WindowProcess $host
  $watch.Stop()
  Write-Host "Watcher returned after $($watch.Elapsed.TotalSeconds) seconds"

  if ($watch.Elapsed.TotalSeconds -lt 0.5 -or $watch.Elapsed.TotalSeconds -gt 8) {
    throw "Window watcher returned at an unexpected time: $($watch.Elapsed.TotalSeconds)s"
  }
  if (-not (Get-Process -Id $host.Id -ErrorAction SilentlyContinue)) {
    throw "Host process exited; test did not reproduce Chromium staying alive"
  }
  if ([ParrotyNativeWindow]::IsWindow($handle)) {
    throw "Window watcher returned while the native window still existed"
  }

  Write-Host "Native window close detection passed while the host process remained alive."
}
finally {
  Stop-Process -Id $host.Id -Force -ErrorAction SilentlyContinue
}
