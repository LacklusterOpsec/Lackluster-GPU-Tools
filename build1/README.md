# Windows 11 GPU Preference Manager & Live Monitor

A modern desktop application built in Python (PySide6) to inspect, monitor, and configure per-application GPU preferences (NVIDIA vs. Intel) on Windows 11.

---

## Technical Specifications & Windows 11 Citations

### 1. Per-App GPU Preference Registry Path
* **Key:** `HKEY_CURRENT_USER\Software\Microsoft\DirectX\UserGpuPreferences`
* **Registry Scope:** Strictly **HKCU** (per-user).
  * *Verification:* Verified directly on Windows 11 Build 26200 (24H2).
  * *HKLM Check:* `HKLM\Software\Microsoft\DirectX\UserGpuPreferences` does not exist. Windows manages app preferences exclusively within the user profile.
  * *Group Policy / CSPs:* No per-app Group Policy or MDM Policy CSP exists for DirectX GPU overrides (CSPs under `Display` only manage global WDDM settings such as `HagsEnabled`).
  * *Privilege Requirements:* Requires **Standard User** privileges only. Writing, updating, and deleting keys does not require administrator elevation.

### 2. Preference Value Syntax & Formatting
* **Value Name:** Full normalized path to the executable (e.g. `C:\Program Files\Example\app.exe`).
* **Value Type:** `REG_SZ` (string).
* **Format:** Semicolon-terminated key-value pairs:
  * `GpuPreference=1;` : **Power Saving** (`DXGI_GPU_PREFERENCE_MINIMUM_POWER` / Intel iGPU).
  * `GpuPreference=2;` : **High Performance** (`DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE` / NVIDIA dGPU).
  * `GpuPreference=0;` / field removed: **Let Windows Decide** (`DXGI_GPU_PREFERENCE_UNSPECIFIED`).
* **Companion Flags (Preserved on Update):**
  * `AutoHDREnable=0;` or `1;` (Auto HDR toggle)
  * `SwapEffectUpgradeEnable=0;` or `1;` (Windowed game optimizations / flip model presentation upgrade)
  * `VRROptimizeEnable=0;` or `1;` (Variable Refresh Rate optimization)
  * `AppStatus=0;` (Application status)
  * `SpecificAdapter=<LUID>;` (Specific GPU override on multi-GPU setups)
  * *Example combined entry:* `GpuPreference=2;AutoHDREnable=1;SwapEffectUpgradeEnable=1;`

### 3. GPU Performance Counters & Telemetry
* **Counter Set Name:** `GPU Engine`
* **Counter Path:** `\GPU Engine(*)\Utilization Percentage`
* **Instance Format:**
  `pid_<PID>_luid_<HighPart>_<LowPart>_phys_<Index>_eng_<Index>_engtype_<Type>`
  *(e.g., `pid_28912_luid_0x00000000_0x00019e33_phys_0_eng_0_engtype_3d`)*
* **LUID Matching:**
  * DXGI (`CreateDXGIFactory1` -> `EnumAdapters1` -> `GetDesc1`) returns each adapter's unique 64-bit `AdapterLuid`.
  * The LUID embedded in the performance counter instance is correlated directly to the physical adapter (NVIDIA vs Intel).
* **Driver-Level Cross Reference:**
  * `nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader,nounits` queries the NVIDIA driver directly to confirm active contexts and VRAM usage.

---

## What to Test Carefully / Potential Edge Cases

1. **Packaged / MSIX Store Applications:**
   * Desktop Win32 `.exe` applications use their standard absolute paths.
   * Store/MSIX applications (e.g. Minecraft Windows 10 Edition) may appear in `UserGpuPreferences` under their Package Family Name (e.g., `Microsoft.MinecraftUWP_8wekyb3d8bbwe!App`) rather than an executable path. Setting preferences via file picker works best for standard Win32 executables.
2. **Process Restart Requirement:**
   * DirectX evaluates GPU preferences only once per process: during device/swapchain creation (`D3D11CreateDevice`, `D3D12CreateDevice`, or `CreateDXGIFactory`).
   * Changing a preference while an app is running will **not** move its existing graphics context to another GPU on the fly. The application must be restarted to apply the new preference. The app flags these instances with a `⚠️ Restart Needed` badge.
3. **Multi-Process Architectures (Chromium / Electron):**
   * Browsers (Edge, Chrome) and Electron apps (Discord, VSCode) spawn utility, renderer, and GPU processes. The preference set for the main executable applies to all child processes spawned under that executable path.

---

## Running the Application

### Option A: Using uv (Recommended)
```powershell
uv run main.py
```

### Option B: Using the Virtual Environment directly
```powershell
.\.venv\Scripts\python.exe main.py
```

---

## Running the Automated Test Suite
```powershell
uv run python test_app_components.py
```
*(or `.\.venv\Scripts\python.exe test_app_components.py`)*

---

## PyInstaller Packaging Steps (Single Executable)

You can build the single-file executable at any time using the provided build scripts:

* **PowerShell**: `.\build.ps1`
* **Command Prompt / File Explorer**: Double-click `build.bat`

### Manual CLI Build Command
```powershell
uv run --extra build python -m PyInstaller `
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
```

The output executable is created at:
`dist\GPUPreferenceManager.exe`
