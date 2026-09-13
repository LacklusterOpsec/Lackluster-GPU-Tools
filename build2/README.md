# GPU Preference Tuner

A single-file **tkinter** desktop utility (zero third-party runtime dependencies) to inventory which GPU your Windows apps are actually using, and to bulk-set per-app GPU preferences — **Power Saving (iGPU)** / **High Performance (dGPU)** / **Let Windows decide** — by writing the same registry entries the Windows Settings "Graphics" page uses.

Sibling of the PySide6 app in `I:\source\GPU\build1`; this build trades GUI richness for a zero-dependency, fully auditable single script.

---

## Features

- **Live GPU inventory** — per-process GPU engine utilization, per-process VRAM, and per-adapter totals, read from the same Windows performance counters Task Manager uses (vendor-agnostic: NVIDIA, Intel, AMD, virtual adapters).
- **NVIDIA cross-check** — `nvidia-smi --query-compute-apps` confirms which processes actually hold contexts on the NVIDIA GPU.
- **Registry merge** — apps with a saved GPU preference appear even when not running.
- **Bulk editing** — multi-select rows, apply one of the three states; unknown tokens (e.g. `AppStatus=`, `AutoHDREnable=`) and `SpecificAdapter=` pins are preserved, only `GpuPreference` is rewritten.
- **Instant feedback** — the Saved pref column updates the moment you click; rows for running apps get a **↻ restart** badge (preferences only apply at next launch).
- **Two-phase refresh** — registry/process rows render in ~1s; live GPU columns fill in when the (~6–10s) counter probe returns. Auto-refresh optional.
- **Headless modes** — `--self-test` and `--headless` for unattended verification/CI.

---

## Technical Specifications & Windows 11 Citations

### 1. Per-App GPU Preference Registry Path

* **Key:** `HKEY_CURRENT_USER\Software\Microsoft\DirectX\UserGpuPreferences`
* **Scope:** strictly **HKCU** (per-user). *Verified on this machine: no `HKLM\...\UserGpuPreferences` exists; Windows manages these per user.*
* **Privileges:** **standard user** — no admin/elevation needed to read, write, or delete (verified live via the self-test round-trip).
* **Group Policy / MDM:** no per-app GPU preference GPO or policy CSP exists (only global WDDM settings like `HagsEnabled` live under driver policy).

### 2. Preference Value Syntax

* **Value name:** full normalized exe path, e.g. `C:\Program Files\App\app.exe`
* **Value type:** `REG_SZ` (string); semicolon-terminated key=value pairs:
  * `GpuPreference=1;` → **Power Saving** (`DXGI_GPU_PREFERENCE_MINIMUM_POWER`, iGPU)
  * `GpuPreference=2;` → **High Performance** (`DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE`, dGPU)
  * `GpuPreference=0;` or token removed → **Let Windows decide** (`DXGI_GPU_PREFERENCE_UNSPECIFIED`)
  * Mapping confirmed against **Microsoft's own `DXGI_GPU_PREFERENCE` enum** (learn.microsoft.com, `dxgi1_6.h`) and multiple independent dumps.
* **Companion tokens preserved on write:** `AutoHDREnable=`, `SwapEffectUpgradeEnable=`, `VRROptimizeEnable=`, `AppStatus=`, `SpecificAdapter=<VEN&DID&SSID>;GpuPreference=1073741824;` (specific-adapter pin). Example live entry: `AppStatus=0;GpuPreference=2;`
* **Reserved values never touched:** `DirectXUserGlobalSettings` (global DX settings), `GraphicsFeaturesNotificationConfig`.
* **"Let Windows Decide"** = remove only the `GpuPreference` token; the value is deleted if nothing remains.

### 3. GPU Performance Counters

* **Category:** `GPU Engine`, counter **`\GPU Engine(*)\Utilization Percentage`** (note: *"Utilization Percentage"* — the older `Utilization` name is gone on current builds).
* **Instance format:** `pid_<PID>_luid_<High>_<Low>_phys_<N>_eng_<N>_engtype_<3D|Copy|Video|Compute|...>` — instances must be **enumerated, never guessed**.
* Per-process utilization = sum over that PID's engine instances (shown with per-engine breakdown and per-adapter attribution).
* **VRAM:** `\GPU Process Memory(*)\Dedicated Usage` / `\Shared Usage` (per PID), `\GPU Adapter Memory(*)\Dedicated Usage` (per LUID). On WDDM systems the per-process dedicated figure is typically 0 and shared carries the bytes.
* **Adapter identification:** LUID low-32 bits in counter instances map 1:1 to PnP device property `{60B193CB-5276-4D0F-96FC-F173ABAD3EC6} 2` (`DEVPKEY_Gpu_Luid`) — resolves friendly names like *"NVIDIA GeForce RTX 5060 Ti"*.

### 4. nvidia-smi (NVIDIA confirmation layer)

* `--query-compute-apps=pid,process_name,used_gpu_memory` — confirms contexts and, when the driver reports it, per-app VRAM.
* **WDDM caveat (verified here):** on consumer setups running WDDM (the default), `used_gpu_memory` returns `[N/A]` — so VRAM comes from the perf counters instead, and nvidia-smi provides the confirmation + whole-GPU stats (`--query-gpu`) only.
* `--query-accounted-apps` **rejects** `process_name` as a field and requires accounting to be enabled (`nvidia-smi -am 1`) — not used.

---

## Windows 11 Platform Quirks (verified on this machine, 2026 build)

1. **`PROCESSENTRY32` layout drift** — on current Win11 the Toolhelp snapshot entry has the PID at byte **0x08** and the exe name at **0x2C** (44), *not* the MSDN-documented 0x0C/0x30. `snapshot_processes()` parses a raw 568-byte buffer and auto-detects both layouts (classic Win10 layout still supported).
2. **`ctypes.windll` pitfall under uv-managed Python** — the process-wide `ctypes.windll` singleton fails to write into ctypes buffers; the code uses fresh `WinDLL("kernel32")` instances. Also: `GetModuleFileNameExW` lives in **psapi.dll**, not kernel32.
3. **`Get-Counter` batching is a trap** — a multi-path call returns one aggregated object with no per-sample counter path, making Dedicated/Shared indistinguishable. The PowerShell probe therefore uses one call per counter path (first call pays ~5s NVIDIA/WDDM counter registration; subsequent ~1s each).
4. **Probe latency** (~6–10s) is why the app renders registry/process rows first and fills live columns in the background.

---

## Running

### Option A: uv (recommended)
```powershell
cd I:\source\GPU\build2
uv sync                 # create .venv (no runtime deps to install)
uv run gpu_pref_tuner.py
```

### Option B: venv directly
```powershell
I:\source\GPU\build2\.venv\Scripts\python.exe gpu_pref_tuner.py
```

### GUI
Sortable/filterable table (App, Executable, Live GPU % with engine/adapter detail, VRAM MB, NVIDIA flag, Saved pref). Select one or more rows → **Power Saving** / **High Performance** / **Let Windows Decide**. Status bar shows the whole-GPU summary (name, driver, util, VRAM). Auto-refresh toggle (5s), manual Refresh, restart badges on changed running apps.

### Headless
```powershell
python gpu_pref_tuner.py --self-test    # exercises every backend; writes+deletes one dummy HKCU value
python gpu_pref_tuner.py --headless     # one-shot text inventory
```

---

## What to Test Carefully

1. **MSIX/Store apps** may register under package identity (`AppId!...`) rather than an exe path — standard Win32 paths are what this tool targets.
2. **Restart requirement is real:** DirectX evaluates GPU preference at device/swapchain creation — a running app's existing contexts don't move; relaunch required (the app flags it).
3. **Chromium/Electron multi-process apps:** the preference set on the main exe governs all child processes.
4. **Windows 10 / older Win11 builds:** the Toolhelp layout auto-detect is the thing to verify (`--self-test` → "process snapshot" must PASS).
5. **Hybrid laptops:** per-adapter engine attribution (via LUID→name) is exercised only there — verify iGPU-classified rows.
6. **`SpecificAdapter=` entries** coexist with generic tokens in the raw string; combining them is unusual — check the written value in the UI after applying.

---

## Packaging (standalone .exe)

```powershell
cd I:\source\GPU\build2
uv sync --group build        # installs pyinstaller (also possible: uv pip install pyinstaller --python .venv)
powershell -File build.ps1   # or: build.bat
```
Output: `dist\GPUTuner.exe` (~10 MB, verified build). Flags: `--onefile --windowed --clean --noconfirm` + hidden imports `ctypes`, `ctypes.wintypes`, `winreg` (tkinter is handled by PyInstaller's own hooks). `requirements.txt` mirrors `pyproject.toml [dependency-groups].build` for build1 parity.

---

## Project Layout

| File | Purpose |
|---|---|
| `gpu_pref_tuner.py` | Everything: registry manager, Toolhelp process table, PowerShell counter probe, nvidia-smi wrapper, inventory merge, tkinter GUI |
| `build.ps1` / `build.bat` | PyInstaller build (mirrors build1 convention) |
| `pyproject.toml` / `uv.lock` | uv project manifest (no runtime deps; `build` dependency group) |
| `requirements.txt` | build1-style pin list (pyinstaller) |
| `.venv/` | uv-managed virtual env (Python 3.11, tkinter included) |

---

## Troubleshooting

- **Live GPU columns stay empty** — the counter probe takes ~6–10s on first scan; check PowerShell is not blocked by AV, `Get-Counter` works in a shell (`powershell -c "Get-Counter '\GPU Engine(*)\Utilization Percentage'"`).
- **NVIDIA column empty / status "nvidia-smi unavailable"** — driver CLI not on PATH; the app also checks `C:\Windows\System32\nvidia-smi.exe` and the NVSMI folder.
- **Registry write error in status bar** — the tool only ever writes `HKCU\...\UserGpuPreferences` without elevation; a failure here means the key is ACL-locked (unusual) or the path isn't a `C:\...\.exe` path.
- **Sorting/redraw problems after editing** — safe to re-run; all state is read from the registry each scan.