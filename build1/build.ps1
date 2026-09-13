# PowerShell Build Script for GPUPreferenceManager Standalone Executable

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Building GPU Preference Manager Standalone Executable    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Ensure PyInstaller is installed in .venv
Write-Host "`n[1/3] Installing PyInstaller into .venv..." -ForegroundColor Yellow
uv pip install pyinstaller --python .venv

# 2. Check pyinstaller.exe path
$pyinstaller = ".\.venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    Write-Error "PyInstaller executable not found at $pyinstaller"
    exit 1
}

# 3. Run PyInstaller
Write-Host "`n[2/3] Bundling standalone executable with PyInstaller..." -ForegroundColor Yellow
& $pyinstaller `
    --name "GPUPreferenceManager" `
    --onefile `
    --windowed `
    --clean `
    --noconfirm `
    --hidden-import "ctypes" `
    --hidden-import "ctypes.wintypes" `
    --hidden-import "winreg" `
    --hidden-import "psutil" `
    --hidden-import "PySide6.QtCore" `
    --hidden-import "PySide6.QtGui" `
    --hidden-import "PySide6.QtWidgets" `
    main.py

# 4. Check output
$outputExe = ".\dist\GPUPreferenceManager.exe"
if (Test-Path $outputExe) {
    $sizeMb = [math]::Round((Get-Item $outputExe).Length / 1MB, 2)
    Write-Host "`n[3/3] Build SUCCESSFUL!" -ForegroundColor Green
    Write-Host "Output executable: $outputExe ($sizeMb MB)" -ForegroundColor Green
} else {
    Write-Error "Build failed: $outputExe not found."
    exit 1
}
