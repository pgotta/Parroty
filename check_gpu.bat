@echo off
REM ============================================================
REM  Parroty - GPU check
REM  Double-click to see whether PyTorch can use your GPU.
REM ============================================================
if not exist "venv\Scripts\python.exe" (
    echo No virtual environment found. Run setup.bat first.
    pause
    exit /b 1
)
echo Checking PyTorch / GPU status...
echo.
"venv\Scripts\python.exe" -c "import torch; ok=torch.cuda.is_available(); print('PyTorch version :', torch.__version__); print('Built with CUDA :', torch.version.cuda); print('GPU available   :', ok); print('GPU name        :', torch.cuda.get_device_name(0) if ok else '(none - will use CPU)')"
echo.
echo If 'GPU available' is False but you have an NVIDIA card, reinstall the
echo CUDA build:  see the README "If you have an NVIDIA GPU but it's still
echo using CPU" section (uses the cu128 PyTorch build).
echo.
pause
