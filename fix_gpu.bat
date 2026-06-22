@echo off
REM ============================================================
REM  Restore GPU (CUDA) PyTorch if setup installed the CPU build.
REM  Run this if check_gpu.bat shows "GPU available: False" but
REM  you have an NVIDIA card.
REM ============================================================
echo.
echo Reinstalling PyTorch with CUDA 12.8 GPU support...
echo (Large download ~2.5 GB)
echo.

set "VPY=venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo No venv found. Run setup.bat first.
    pause
    exit /b 1
)

"%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu128
if %errorlevel% neq 0 (
    echo CUDA 12.8 failed, trying CUDA 12.4...
    "%VPY%" -m pip install --force-reinstall --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu124
)

echo.
echo Verifying...
"%VPY%" -c "import torch; ok=torch.cuda.is_available(); print('PyTorch', torch.__version__); print('GPU available:', ok); print('GPU:', torch.cuda.get_device_name(0) if ok else '(CPU only)')"
echo.
pause
