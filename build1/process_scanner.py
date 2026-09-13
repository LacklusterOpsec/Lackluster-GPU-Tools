"""
Process Scanner and Unified Inventory Builder
Merges running processes with saved registry preferences into an inventory.
"""
import os
import psutil
from typing import Dict, List, Optional, Set
from registry_manager import GpuRegistryManager, RegistryPreference, normalize_path, PREF_POWER_SAVING, PREF_HIGH_PERFORMANCE, PREF_LET_WINDOWS_DECIDE
from perf_monitor import GpuPerformanceMonitor, ProcessGpuActivity

class AppInventoryItem:
    def __init__(self, exe_path: str, display_name: str = ""):
        self.exe_path = exe_path
        self.norm_path = normalize_path(exe_path)
        self.display_name = display_name or os.path.basename(exe_path)
        self.pids: List[int] = []
        self.is_running: bool = False
        
        # Live GPU telemetry
        self.nvidia_util: float = 0.0
        self.nvidia_vram_mb: int = 0
        self.nvidia_in_smi: bool = False
        self.intel_util: float = 0.0
        self.other_util: float = 0.0
        self.active_engines: List[str] = []
        
        # Saved Registry Preference
        self.saved_pref: Optional[int] = None
        self.saved_raw_str: str = ""
        self.has_saved_entry: bool = False
        
        # Restart tracking
        self.pending_restart: bool = False
        self.restart_reason: str = ""

    @property
    def live_gpu_summary(self) -> str:
        if not self.is_running:
            return "—"
        parts = []
        if self.nvidia_in_smi or self.nvidia_util > 0.05:
            s = f"NVIDIA ({self.nvidia_util:.1f}%"
            if self.nvidia_vram_mb > 0:
                s += f", {self.nvidia_vram_mb} MB"
            s += ")"
            parts.append(s)
        if self.intel_util > 0.05:
            parts.append(f"Intel ({self.intel_util:.1f}%)")
        if self.other_util > 0.05 and not parts:
            parts.append(f"Other ({self.other_util:.1f}%)")
        
        if not parts:
            return "Idle"
        return " + ".join(parts)

    @property
    def dominant_live_gpu(self) -> str:
        if not self.is_running:
            return "None"
        if (self.nvidia_in_smi or self.nvidia_util > 0.05) and self.intel_util > 0.05:
            return "Hybrid"
        elif self.nvidia_in_smi or self.nvidia_util > 0.05:
            return "NVIDIA"
        elif self.intel_util > 0.05:
            return "Intel"
        return "Idle"

    @property
    def saved_pref_label(self) -> str:
        if self.saved_pref == PREF_HIGH_PERFORMANCE:
            return "High Performance (NVIDIA)"
        elif self.saved_pref == PREF_POWER_SAVING:
            return "Power Saving (Intel)"
        elif self.saved_pref == PREF_LET_WINDOWS_DECIDE or (self.has_saved_entry and self.saved_pref is None):
            return "Let Windows Decide"
        return "Unconfigured"

    def check_restart_needed(self, was_running_when_modified: bool = False):
        if not self.is_running:
            self.pending_restart = False
            self.restart_reason = ""
            return

        if was_running_when_modified:
            self.pending_restart = True
            self.restart_reason = "Preference changed while process is running"
            return

        # Check mismatch between saved preference and live GPU
        if self.saved_pref == PREF_HIGH_PERFORMANCE and self.dominant_live_gpu == "Intel":
            self.pending_restart = True
            self.restart_reason = "Active on Intel; preferred High Performance (NVIDIA)"
        elif self.saved_pref == PREF_POWER_SAVING and self.dominant_live_gpu == "NVIDIA":
            self.pending_restart = True
            self.restart_reason = "Active on NVIDIA; preferred Power Saving (Intel)"


class InventoryScanner:
    def __init__(self, reg_manager: GpuRegistryManager, perf_monitor: GpuPerformanceMonitor):
        self.reg_mgr = reg_manager
        self.perf_mon = perf_monitor
        self.modified_running_apps: Set[str] = set()
        self._pid_cache: Dict[int, Optional[Tuple[str, str, str]]] = {}  # pid -> (name, exe, norm_path)

    def mark_modified_running(self, norm_path: str):
        self.modified_running_apps.add(norm_path)

    def scan_inventory(self) -> List[AppInventoryItem]:
        items_map: Dict[str, AppInventoryItem] = {}

        # 1. Read all saved registry preferences
        saved_prefs = self.reg_mgr.get_all_preferences()
        for norm_path, pref_obj in saved_prefs.items():
            item = AppInventoryItem(pref_obj.raw_path)
            item.saved_pref = pref_obj.gpu_preference
            item.saved_raw_str = pref_obj.raw_value
            item.has_saved_entry = True
            items_map[norm_path] = item

        # 2. Collect Live GPU Performance and SMI telemetry
        live_activities = self.perf_mon.collect_live_gpu_activity()

        # 3. Enumerate all running processes using fast PID caching
        current_pids = set(psutil.pids())

        # Prune exited PIDs from cache
        for p in list(self._pid_cache.keys()):
            if p not in current_pids:
                del self._pid_cache[p]

        # Scan active PIDs (only resolve new PIDs)
        for pid in current_pids:
            if pid <= 4:
                continue

            cached = self._pid_cache.get(pid)
            if cached is None and pid not in self._pid_cache:
                try:
                    p = psutil.Process(pid)
                    name = p.name()
                    exe = p.exe()
                    if exe:
                        norm = normalize_path(exe)
                        self._pid_cache[pid] = (name, exe, norm)
                    else:
                        self._pid_cache[pid] = None
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    self._pid_cache[pid] = None
                cached = self._pid_cache.get(pid)

            if not cached:
                continue

            name, exe, norm_path = cached
            item = items_map.get(norm_path)
            if not item:
                item = AppInventoryItem(exe, display_name=name)
                items_map[norm_path] = item

            item.is_running = True
            item.pids.append(pid)

            # Merge live GPU activity
            act = live_activities.get(pid)
            if act:
                item.nvidia_util += act.nvidia_util
                item.intel_util += act.intel_util
                item.other_util += act.other_util
                item.nvidia_vram_mb = max(item.nvidia_vram_mb, act.nvidia_vram_mb)
                if act.nvidia_in_smi:
                    item.nvidia_in_smi = True
                item.active_engines.extend(act.active_engines)

        # 4. Check restart conditions
        for norm_path, item in items_map.items():
            was_modified = norm_path in self.modified_running_apps
            item.check_restart_needed(was_running_when_modified=was_modified)

        # Return stably sorted list: active/running apps first, then by normalized path
        # Using norm_path guarantees row stability across polls so only cell values change in-place
        return sorted(items_map.values(), key=lambda x: (not x.is_running, x.norm_path))


if __name__ == "__main__":
    reg = GpuRegistryManager()
    perf = GpuPerformanceMonitor()
    scanner = InventoryScanner(reg, perf)
    items = scanner.scan_inventory()
    print(f"Inventory scanned: {len(items)} items")
    for it in items[:15]:
        print(f"[{'RUNNING' if it.is_running else 'SAVED'}] {it.display_name:25s} | GPU: {it.live_gpu_summary:30s} | Pref: {it.saved_pref_label}")
    perf.close()
