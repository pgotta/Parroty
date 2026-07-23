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
using System.Threading;

public static class ParrotyNativeWindow {
  [DllImport("user32.dll")]
  public static extern bool IsWindow(IntPtr hWnd);
}

public static class NativeWindowHarness {
  private const uint WM_CLOSE = 0x0010;
  private const uint WM_DESTROY = 0x0002;
  private static readonly IntPtr HWND_MESSAGE = new IntPtr(-3);
  private delegate IntPtr WndProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  private static readonly WndProc WindowProcedure = HandleMessage;
  private static readonly ManualResetEventSlim Ready = new ManualResetEventSlim(false);
  private static IntPtr windowHandle = IntPtr.Zero;

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
  private struct MSG {
    public IntPtr hwnd;
    public uint message;
    public UIntPtr wParam;
    public IntPtr lParam;
    public uint time;
    public int ptX;
    public int ptY;
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

  public static IntPtr Start() {
    Ready.Reset();
    Thread thread = new Thread(() => {
      string className = "ParrotyNativeTest_" + Guid.NewGuid().ToString("N");
      WNDCLASS windowClass = new WNDCLASS {
        lpfnWndProc = WindowProcedure,
        hInstance = GetModuleHandle(null),
        lpszClassName = className
      };
      ushort atom = RegisterClass(ref windowClass);
      if (atom == 0) {
        Ready.Set();
        return;
      }

      windowHandle = CreateWindowEx(
        0, className, "Parroty regression window", 0,
        0, 0, 0, 0, HWND_MESSAGE, IntPtr.Zero,
        windowClass.hInstance, IntPtr.Zero);
      Ready.Set();

      MSG message;
      while (GetMessage(out message, IntPtr.Zero, 0, 0) > 0) {
        TranslateMessage(ref message);
        DispatchMessage(ref message);
      }

      Thread.Sleep(4000);
    });
    thread.IsBackground = true;
    thread.Start();
    Ready.Wait(5000);
    return windowHandle;
  }

  public static void CloseAfter(IntPtr hWnd, int milliseconds) {
    Thread closer = new Thread(() => {
      Thread.Sleep(milliseconds);
      PostMessage(hWnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
    });
    closer.IsBackground = true;
    closer.Start();
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

Write-Host "Creating native message window..."
$handle = [NativeWindowHarness]::Start()
Write-Host "Handle: $([int64]$handle)"
if ($handle -eq [IntPtr]::Zero) { throw "Native test window was not created" }
if (-not [ParrotyNativeWindow]::IsWindow($handle)) {
  throw "Native test handle is not a live window"
}

[NativeWindowHarness]::CloseAfter($handle, 1000)
$host = [System.Diagnostics.Process]::GetCurrentProcess()
$watch = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "Waiting for native window destruction while host PID $($host.Id) stays alive..."
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

Write-Host "Native window close detection passed."
