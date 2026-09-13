@echo off
echo ==========================================================
echo  Building GPU Preference Manager Standalone Executable
echo ==========================================================

echo [1/3] Installing PyInstaller into .venv...
uv pip install pyinstaller --python .venv
if %errorlevel% neq 0 exit /b %errorlevel%

echo [2/3] Bundling standalone executable with PyInstaller...
.\.venv\Scripts\python.exe -m PyInstaller --name "GPUPreferenceManager" --onefile --windowed --clean --noconfirm --hidden-import "ctypes" --hidden-import "ctypes.wintypes" --hidden-import "winreg" --hidden-import "psutil" --hidden-import "PySide6.QtCore" --hidden-import "PySide6.QtGui" --hidden-import "PySide6.QtWidgets" main.py
if %errorlevel% neq 0 exit /b %errorlevel%

echo [3/3] Build Complete!
echo Executable located at: dist\GPUPreferenceManager.exe
pause
