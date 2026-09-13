"""
Performance Counter & nvidia-smi GPU Activity Monitor
Combines Windows PDH 'GPU Engine' counters with nvidia-smi driver queries
to deliver authoritative per-process GPU utilization for NVIDIA and Intel.
"""
import ctypes
from ctypes import wintypes
import subprocess
import re
import shutil
import time
from typing import Dict, List, Optional, Tuple, Any
from dxgi_util import enumerate_gpu_adapters, GpuAdapterInfo

# PDH Types and Constants
pdh = ctypes.windll.pdh

class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [
            ("longValue", wintypes.LONG),
            ("doubleValue", ctypes.c_double),
            ("largeValue", ctypes.c_int64),
            ("AnsiStringValue", ctypes.c_char_p),
            ("WideStringValue", ctypes.c_wchar_p)
        ]
    _fields_ = [
        ("CStatus", wintypes.DWORD),
        ("_u", _U)
    ]

class PDH_FMT_COUNTERVALUE_ITEM(ctypes.Structure):
    _fields_ = [
        ("szName", wintypes.LPWSTR),
        ("FmtValue", PDH_FMT_COUNTERVALUE)
    ]

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2

# Regex to parse GPU Engine instance name:
# e.g.: pid_10536_luid_0x00000000_0x0001a7b3_phys_0_eng_0_engtype_3D
INSTANCE_REGEX = re.compile(
    r"pid_(\d+)_luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_(\d+)_eng_(\d+)_engtype_([a-zA-Z0-9_]+)",
    re.IGNORECASE
)

class ProcessGpuActivity:
    def __init__(self, pid: int):
        self.pid = pid
        self.nvidia_util = 0.0
        self.nvidia_vram_mb = 0
        self.nvidia_in_smi = False
        self.intel_util = 0.0
        self.other_util = 0.0
        self.active_engines: List[str] = []

    @property
    def has_activity(self) -> bool:
        return self.nvidia_in_smi or self.nvidia_util > 0.05 or self.intel_util > 0.05

    def get_summary_label(self) -> str:
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
            parts.append(f"Other GPU ({self.other_util:.1f}%)")

        if not parts:
            return "Idle"
        return " + ".join(parts)

    def get_dominant_gpu(self) -> str:
        if self.nvidia_in_smi or self.nvidia_util > 0.05:
            if self.intel_util > 0.05:
                return "Hybrid (NVIDIA + Intel)"
            return "NVIDIA"
        elif self.intel_util > 0.05:
            return "Intel"
        return "None"


class nvmlProcessInfo_v2_t(ctypes.Structure):
    _fields_ = [
        ('pid', ctypes.c_uint),
        ('usedGpuMemory', ctypes.c_ulonglong),
        ('gpuInstanceId', ctypes.c_uint),
        ('computeInstanceId', ctypes.c_uint)
    ]

class GpuPerformanceMonitor:
    def __init__(self):
        self.adapters: List[GpuAdapterInfo] = []
        self.luid_to_adapter: Dict[str, GpuAdapterInfo] = {}
        self.has_nvidia_smi = shutil.which("nvidia-smi") is not None
        self.h_query = None
        self.h_counter = None
        self.initialized = False
        
        # Native NVML ctypes support for zero-overhead in-process querying
        self.nvml = None
        self.nvml_device_handles = []
        self.has_nvml = False
        self._last_smi_time = 0.0
        self._cached_smi_results: Dict[int, Dict[str, Any]] = {}

        self._init_nvml()
        self._init_system()

    def _init_nvml(self):
        try:
            self.nvml = ctypes.windll.LoadLibrary('nvml.dll')
            if self.nvml.nvmlInit_v2() == 0:
                device_count = ctypes.c_uint(0)
                if self.nvml.nvmlDeviceGetCount_v2(ctypes.byref(device_count)) == 0:
                    for i in range(device_count.value):
                        handle = ctypes.c_void_p()
                        if self.nvml.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(handle)) == 0:
                            self.nvml_device_handles.append(handle)
                if self.nvml_device_handles:
                    self.has_nvml = True
        except Exception:
            self.has_nvml = False
            self.nvml = None

    def _init_system(self):
        self.adapters = enumerate_gpu_adapters()
        self.luid_to_adapter = {a.luid_str: a for a in self.adapters}

        # Initialize PDH query
        self.h_query = wintypes.HANDLE()
        st = pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.h_query))
        if st == 0:
            self.h_counter = wintypes.HANDLE()
            counter_path = r"\GPU Engine(*)\Utilization Percentage"
            st_c = pdh.PdhAddEnglishCounterW(self.h_query, counter_path, 0, ctypes.byref(self.h_counter))
            if st_c == 0:
                # Prime the counter with the first collect
                pdh.PdhCollectQueryData(self.h_query)
                self.initialized = True
            else:
                pdh.PdhCloseQuery(self.h_query)
                self.h_query = None

    def query_nvidia_smi(self) -> Dict[int, Dict[str, Any]]:
        """
        Queries active NVIDIA applications.
        Uses in-process native NVML (0.1ms) when available,
        falling back to throttled nvidia-smi.
        """
        # Fast path: Native NVML via ctypes in-process
        if self.has_nvml and self.nvml and self.nvml_device_handles:
            results = {}
            for handle in self.nvml_device_handles:
                # 1. Graphics processes
                count = ctypes.c_uint(128)
                procs = (nvmlProcessInfo_v2_t * 128)()
                if self.nvml.nvmlDeviceGetGraphicsRunningProcesses_v2(handle, ctypes.byref(count), procs) == 0:
                    for i in range(count.value):
                        pid = procs[i].pid
                        vram_raw = procs[i].usedGpuMemory
                        # Check for NVML_VALUE_NOT_AVAILABLE (0xFFFFFFFFFFFF)
                        vram = 0 if vram_raw >= 0xFFFFFF000000 else (vram_raw // (1024 * 1024))
                        results[pid] = {"process_name": "", "vram_mb": vram}

                # 2. Compute processes
                count_c = ctypes.c_uint(128)
                procs_c = (nvmlProcessInfo_v2_t * 128)()
                if self.nvml.nvmlDeviceGetComputeRunningProcesses_v2(handle, ctypes.byref(count_c), procs_c) == 0:
                    for i in range(count_c.value):
                        pid = procs_c[i].pid
                        vram_raw = procs_c[i].usedGpuMemory
                        vram = 0 if vram_raw >= 0xFFFFFF000000 else (vram_raw // (1024 * 1024))
                        results[pid] = {"process_name": "", "vram_mb": vram}
            return results

        # Slow fallback path: nvidia-smi throttled to at most once every 5 seconds
        if not self.has_nvidia_smi:
            return {}

        now = time.time()
        if now - self._last_smi_time < 5.0 and self._cached_smi_results:
            return self._cached_smi_results

        self._last_smi_time = now
        results = {}
        try:
            cmd = ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0, creationflags=subprocess.CREATE_NO_WINDOW)
            if proc.returncode == 0 and proc.stdout:
                for line in proc.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        try:
                            pid = int(parts[0])
                            pname = parts[1]
                            vram_str = parts[2]
                            vram = int(vram_str) if vram_str.isdigit() else 0
                            results[pid] = {"process_name": pname, "vram_mb": vram}
                        except ValueError:
                            continue
            self._cached_smi_results = results
        except Exception:
            pass
        return results

    def collect_live_gpu_activity(self) -> Dict[int, ProcessGpuActivity]:
        """
        Samples GPU Engine performance counters and queries nvidia-smi.
        Returns a mapping from PID to ProcessGpuActivity.
        """
        activities: Dict[int, ProcessGpuActivity] = {}

        # 1. Query nvidia-smi first
        smi_data = self.query_nvidia_smi()
        for pid, data in smi_data.items():
            act = activities.setdefault(pid, ProcessGpuActivity(pid))
            act.nvidia_in_smi = True
            act.nvidia_vram_mb = data["vram_mb"]

        # 2. Query PDH counters
        if self.initialized and self.h_query and self.h_counter:
            # Collect second/current sample to compute utilization percentage
            pdh.PdhCollectQueryData(self.h_query)

            buffer_size = wintypes.DWORD(0)
            item_count = wintypes.DWORD(0)

            # First call to get required buffer size
            status = pdh.PdhGetFormattedCounterArrayW(
                self.h_counter,
                PDH_FMT_DOUBLE,
                ctypes.byref(buffer_size),
                ctypes.byref(item_count),
                None
            )

            if (status == ctypes.c_long(PDH_MORE_DATA).value or buffer_size.value > 0) and item_count.value > 0:
                buf = (ctypes.c_byte * buffer_size.value)()
                status = pdh.PdhGetFormattedCounterArrayW(
                    self.h_counter,
                    PDH_FMT_DOUBLE,
                    ctypes.byref(buffer_size),
                    ctypes.byref(item_count),
                    ctypes.byref(buf)
                )

                if status == 0:
                    items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM))
                    for i in range(item_count.value):
                        item = items[i]
                        val = item.FmtValue._u.doubleValue
                        if val <= 0.01:
                            continue

                        name = item.szName
                        m = INSTANCE_REGEX.match(name)
                        if not m:
                            continue

                        pid = int(m.group(1))
                        luid = m.group(2).lower()
                        eng_type = m.group(5)

                        act = activities.setdefault(pid, ProcessGpuActivity(pid))
                        act.active_engines.append(f"{eng_type}:{val:.1f}%")

                        adapter = self.luid_to_adapter.get(luid)
                        if adapter:
                            if adapter.vendor == "NVIDIA":
                                act.nvidia_util += val
                            elif adapter.vendor == "Intel":
                                act.intel_util += val
                            else:
                                act.other_util += val
                        else:
                            act.other_util += val

        return activities

    def close(self):
        if self.h_query:
            try:
                pdh.PdhCloseQuery(self.h_query)
            except Exception:
                pass
            self.h_query = None
            self.initialized = False

    def __del__(self):
        self.close()

if __name__ == "__main__":
    mon = GpuPerformanceMonitor()
    print("Collecting GPU activity for 1 second...")
    time.sleep(1.0)
    acts = mon.collect_live_gpu_activity()
    active_procs = [a for a in acts.values() if a.has_activity]
    print(f"Total active GPU processes: {len(active_procs)}")
    for a in active_procs[:15]:
        print(f"PID {a.pid:6d} -> {a.get_summary_label()} [Engines: {', '.join(a.active_engines)}]")
    mon.close()
