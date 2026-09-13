# PowerShell Build Script for GPU Preference Tuner Standalone Executable

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Building GPU Preference Tuner Standalone Executable     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Ensure PyInstaller is installed in .venv
Write-Host "`n[1/3] Installing PyInstaller into .venv..." -ForegroundColor Yellow
uv pip install pyinstaller --python .venv

# 2. Check python executable path
$python = ".\\.venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Python executable not found at $python"
    exit 1
}

# 3. Run PyInstaller via Python module (avoids uv trampoline path issues)
Write-Host "`n[2/3] Bundling standalone executable with PyInstaller..." -ForegroundColor Yellow
& $python -m PyInstaller `
    --name "GPUTuner" `
    --onefile `
    --windowed `
    --clean `
    --noconfirm `
    --hidden-import "ctypes" `
    --hidden-import "ctypes.wintypes" `
    --hidden-import "winreg" `
    gpu_pref_tuner.py

# 4. Check output
$outputExe = ".\\dist\\GPUTuner.exe"
if (Test-Path $outputExe) {
    $sizeMb = [math]::Round((Get-Item $outputExe).Length / 1MB, 2)
    Write-Host "`n[3/3] Build SUCCESSFUL!" -ForegroundColor Green
    Write-Host "Output executable: $outputExe ($sizeMb MB)" -ForegroundColor Green
} else {
    Write-Error "Build failed: $outputExe not found."
    exit 1
}