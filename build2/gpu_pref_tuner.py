#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Preference Tuner - Windows 11 per-app GPU preference inventory & bulk editor.

Data sources (all read-only except registry writes, which touch ONLY the per-app
GPU preference key for the current user):
  * Registry   : HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences
                 (value name = full exe path, value data = "GpuPreference=1;"/"=2;")
                 Verified against Microsoft DXGI_GPU_PREFERENCE enum:
                   0 = unspecified / let Windows decide (entry removed or token dropped)
                   1 = minimum power    (iGPU / "Power Saving")
                   2 = high performance (dGPU)
  * Performance counters via PowerShell Get-Counter (same counters Task Manager uses):
                 \\GPU Engine(*)\\Utilization Percentage     -> per-process engine util
                 \\GPU Process Memory(*)\\Dedicated|Shared Usage -> per-process VRAM
                 \\GPU Adapter Memory(*)\\Dedicated Usage     -> per-adapter totals
                 PnP property {60B193CB-5276-4D0F-96FC-F173ABAD3EC6} 2 -> LUID -> name
  * nvidia-smi --query-compute-apps   -> confirmation a process holds a context on the
                 NVIDIA GPU + per-app VRAM when the driver reports it (often [N/A] in
                 WDDM mode; the perf-counter values are used instead).

No third-party packages.  Requires: Python 3.9+ on Windows 10/11.

Run:
    python gpu_pref_tuner.py                 # GUI
    python gpu_pref_tuner.py --self-test     # headless verification of every backend
    python gpu_pref_tuner.py --headless      # one-shot text inventory dump
"""

import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

APP_TITLE = "GPU Preference Tuner"
REG_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
# Values under this key that are NOT per-app preference entries:
RESERVED_VALUES = {"DirectXUserGlobalSettings", "GraphicsFeaturesNotificationConfig"}
GPU_TOKEN = "GpuPreference"
PREF_LABEL = {0: "Windows decides", 1: "Power Saving", 2: "High Performance"}
PREF_FULL = {0: "Let Windows decide", 1: "Power Saving (iGPU)", 2: "High Performance (dGPU)"}
EXE_PATH_RE = re.compile(r"^[A-Za-z]:\\.+\.exe$", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Registry: read / write per-app GPU preferences                                #
# --------------------------------------------------------------------------- #

class GpuPrefError(Exception):
    pass


def parse_tokens(raw):
    """'GpuPreference=2;SpecificAdapter=1002&6660&380F17AA;' -> [(k, v), ...]"""
    toks = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            toks.append((k.strip(), v.strip()))
        else:
            toks.append((part, ""))          # malformed/no-'=' token: preserve
    return toks


def tokens_to_str(toks):
    out = "".join("%s=%s;" % (k, v) if v else ("%s;" % k) for k, v in toks)
    return out if out.endswith(";") else out + ";"


def _open_key(create=False):
    import winreg
    try:
        if create:
            return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_KEY, 0,
                                      winreg.KEY_READ | winreg.KEY_WRITE)
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ)
    except OSError as e:
        raise GpuPrefError("Cannot %s registry key %r: %s"
                           % ("create" if create else "open", REG_KEY, e))


def gpu_mode_of(raw):
    """Programmatic GPU-preference mode parsed from a registry raw string:
    returns 1 (power saving) / 2 (high performance) / None (unset)."""
    for k, v in parse_tokens(raw):
        if k == GPU_TOKEN and v.isdigit():
            iv = int(v)
            if iv in (1, 2):
                return iv
            if iv == 0:
                return None
    return None


def read_gpu_prefs():
    """Return {exe_path: {"mode": 0|1|2, "raw": str}} for every per-app value."""
    import winreg
    out = {}
    try:
        with _open_key() as k:
            i = 0
            while True:
                try:
                    name, data, _typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name in RESERVED_VALUES or not isinstance(data, str):
                    continue
                if not EXE_PATH_RE.match(name):
                    continue
                mode = gpu_mode_of(data)
                out[name] = {"mode": (mode if mode is not None else 0), "raw": data or ""}
        return out
    except GpuPrefError:
        return {}


def _transform_tokens(toks, mode):
    """Return a copy of toks with the GPU token replaced/removed per mode.
    mode 1/2 -> one token GpuPreference=<mode> (other tokens preserved);
    mode 0   -> GPU token removed (other tokens preserved)."""
    toks = [t for t in toks if t[0] != GPU_TOKEN]
    if mode in (1, 2):
        toks.append((GPU_TOKEN, str(mode)))
    return toks


def set_gpu_pref(path, mode):
    """Write a per-app GPU preference. mode 1/2 sets it; mode 0 (or None) clears
    the preference ('Let Windows decide'), deleting the value once it is empty.
    Returns (old_raw, new_raw).
    Raises GpuPrefError on failure."""
    import winreg
    assert mode in (0, 1, 2)
    assert EXE_PATH_RE.match(path), "not a Windows exe path: %r" % path
    with _open_key(create=True) as k:
        old = None
        try:
            old = winreg.QueryValueEx(k, path)[0]
        except OSError:
            pass
        toks = parse_tokens(old) if old else []
        toks = _transform_tokens(toks, mode)
        new = tokens_to_str(toks)
        try:
            if not toks:
                try:
                    winreg.DeleteValue(k, path)
                except OSError:
                    pass
            else:
                winreg.SetValueEx(k, path, 0, winreg.REG_SZ, new)
        except OSError as e:
            raise GpuPrefError("Registry write failed for %r: %s" % (path, e))
    return (old, new if toks else None)


# --------------------------------------------------------------------------- #
# Process table (ctypes + Windows Toolhelp)                                    #
# --------------------------------------------------------------------------- #

def snapshot_processes():
    """{pid: {"name": ..., "exe": ...}} using CreateToolhelp32Snapshot.

    Parses a RAW entry buffer.  On current Windows 11 builds the entry layout
    is (verified by hexdump): dwSize @0x00, dwProcessId @0x08, ...,
    szExeFile @0x2C (44), entry size 568.  The MSDN-documented layout
    (pid @0x0C, name @0x30 with LPARAM alignment) is auto-detected from the
    first entry so Windows 10 builds keep working."""
    import struct as _s
    # NOTE: must use a fresh WinDLL("kernel32") instance -- the process-wide
    # ctypes.windll singleton does NOT write into ctypes buffers correctly
    # under the uv-managed Python runtime (verified empirically).
    lib = ctypes.WinDLL("kernel32")
    TH32CS_SNAPPROCESS = 0x00000002
    ENTRY = 568
    out = {}
    try:
        lib.CreateToolhelp32Snapshot.restype = ctypes.c_ulong
        lib.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        lib.Process32FirstW.restype = ctypes.c_bool
        lib.Process32FirstW.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        lib.Process32NextW.restype = ctypes.c_bool
        lib.Process32NextW.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        h = lib.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h == 0:
            return out
        pid_off, name_off = None, None
        try:
            buf = ctypes.create_string_buffer(ENTRY)
            _s.pack_into("<I", buf, 0x00, ENTRY)          # dwSize
            ok = lib.Process32FirstW(h, buf)

            def _name_at(off):
                # decode the whole region, cut at the first NUL -- avoids
                # binary-split artifacts with the wide-char terminator
                txt = buf.raw[off:off + 520].decode("utf-16-le", errors="ignore")
                return txt.split("\x00", 1)[0]

            if ok:
                # layout auto-detect from the first entry
                n48, n44 = _name_at(0x30), _name_at(0x2C)
                if 1 <= len(n44) <= 64 and (len(n48) <= len(n44) or not n48):
                    pid_off, name_off = 0x08, 0x2C     # Win11 (2026) layout
                else:
                    pid_off, name_off = 0x0C, 0x30     # classic/MSDN layout
            while ok:
                pid = _s.unpack_from("<I", buf, pid_off or 0x0C)[0]
                name = _name_at(name_off or 0x30)
                out[pid] = {"name": name, "exe": None}
                ok = lib.Process32NextW(h, buf)
        finally:
            lib.CloseHandle(h)
    except Exception:
        return {}
    # wrap with exe paths (GetModuleFileNameExW lives in PSAPI, not kernel32)
    try:
        psapi = ctypes.WinDLL("psapi.dll")
        psapi.GetModuleFileNameExW.restype = ctypes.c_ulong
        psapi.GetModuleFileNameExW.argtypes = [ctypes.c_ulong, ctypes.c_ulong,
                                               ctypes.c_void_p, ctypes.c_ulong]
        lib.OpenProcess.restype = ctypes.c_ulong
        lib.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        for pid, info in out.items():
            try:
                h = lib.OpenProcess(0x10 | 0x400, False, pid)  # QUERY | QUERY_INFORMATION
                if h:
                    buf = ctypes.create_unicode_buffer(260)
                    if psapi.GetModuleFileNameExW(h, 0, buf, 260) and buf.value:
                        info["exe"] = buf.value
                    lib.CloseHandle(h)
            except Exception:
                pass
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- #
# GPU perf counters (PowerShell Get-Counter, one process per refresh)          #
# --------------------------------------------------------------------------- #

PS_PROBE = r"""
$ErrorActionPreference = 'SilentlyContinue'
# NOTE: one Get-Counter call per path.  Batching paths into a single call is
# NOT possible: Get-Counter returns one aggregated object (no per-sample
# counter path), so dedicated/shared could not be told apart.  The first call
# on the engine counter costs ~5s with the NVIDIA driver (WDDM); later calls
# ~1s each.  The GUI shows registry/process rows immediately and fills the
# live columns when this returns.
$eng = @()
foreach ($cs in (Get-Counter '\GPU Engine(*)\Utilization Percentage')) {
    foreach ($s in $cs.CounterSamples) {
        $eng += @{ inst = [string]$s.InstanceName; val = [double]$s.CookedValue }
    }
}
$mem = @()
foreach ($cs in (Get-Counter '\GPU Process Memory(*)\Dedicated Usage')) {
    foreach ($s in $cs.CounterSamples) { $mem += @{ inst = [string]$s.InstanceName; val = [double]$s.CookedValue; kind = 'Dedicated' } }
}
foreach ($cs in (Get-Counter '\GPU Process Memory(*)\Shared Usage')) {
    foreach ($s in $cs.CounterSamples) { $mem += @{ inst = [string]$s.InstanceName; val = [double]$s.CookedValue; kind = 'Shared' } }
}
$adp = @()
foreach ($cs in (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage')) {
    foreach ($s in $cs.CounterSamples) { $adp += @{ inst = [string]$s.InstanceName; val = [double]$s.CookedValue; kind = 'Dedicated' } }
}
foreach ($cs in (Get-Counter '\GPU Adapter Memory(*)\Shared Usage')) {
    foreach ($s in $cs.CounterSamples) { $adp += @{ inst = [string]$s.InstanceName; val = [double]$s.CookedValue; kind = 'Shared' } }
}
$lus = @()
foreach ($dev in (Get-PnpDevice -Class Display -PresentOnly)) {
    $prop = Get-PnpDeviceProperty -InstanceId $dev.InstanceId -KeyName '{60B193CB-5276-4D0F-96FC-F173ABAD3EC6} 2'
    if ($prop -and $prop.Data) {
        $luidRaw = [uint64]$prop.Data
        $lus += @{ name = [string]$dev.FriendlyName; low = [string]('0x{0:x}' -f [uint32]($luidRaw % 4294967296)) }
    }
}
Write-Output (ConvertTo-Json -Depth 8 -Compress @{ eng = $eng; mem = $mem; adp = $adp; lus = $lus })
"""

_INST_PID = re.compile(r"^pid_(\d+)_luid_0x[0-9a-f]+_(0x[0-9a-f]+)_phys_(\d+)_eng_\d+_engtype_(\w+)")
_INST_LUID = re.compile(r"^(pid_\d+_luid_0x[0-9a-f]+_0x[0-9a-f]+_phys_\d+)")


def probe_gpu_counters(timeout=90):
    """One PowerShell call -> dict with engines/memory/adapters/LUID table.
    Never raises: returns {} on failure."""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", PS_PROBE],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        if r.returncode != 0:
            return {}
        line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        d = json.loads(line) if line else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def parse_probe(d):
    """Structure the raw probe dict into:
      engines: {pid: {"util": float, "adapters": {luid_low: util}, "engtypes": {...}}}
      mem:     {pid: {"Dedicated": bytes, "Shared": bytes}}
      adapters:{luid_low: {"Dedicated": bytes, "Shared": bytes}}
      luid_names: {luid_low: name}
    """
    engines, mem, adapters, luid_names = {}, {}, {}, {}
    for l in d.get("lus", []):
        if l.get("low"):
            luid_names[l["low"].lower()] = l.get("name", l["low"])
    for e in d.get("eng", []):
        if not isinstance(e, dict):
            continue
        m = _INST_PID.match(e.get("inst") or "")
        if not m:
            continue
        pid, luid, _phys, engtype = int(m.group(1)), m.group(2).lower(), m.group(3), m.group(4)
        v = float(e.get("val") or 0.0)
        g = engines.setdefault(pid, {"util": 0.0, "adapters": {}, "engtypes": {}})
        g["util"] += v
        g["adapters"][luid] = g["adapters"].get(luid, 0.0) + v
        g["engtypes"][engtype] = g["engtypes"].get(engtype, 0.0) + v
    for mrow in d.get("mem", []):
        if not isinstance(mrow, dict):
            continue
        m = _INST_LUID.match(mrow.get("inst") or "")
        if not m:
            continue
        pid = int(m.group(1).split("_")[1])
        kind = mrow.get("kind") or "Shared"
        mem.setdefault(pid, {"Dedicated": 0.0, "Shared": 0.0})
        mem[pid][kind] += float(mrow.get("val") or 0.0)
    for a in d.get("adp", []):
        if not isinstance(a, dict):
            continue
        m = re.match(r"^luid_0x[0-9a-f]+_(0x[0-9a-f]+)_phys_\d+$", a.get("inst") or "")
        if not m:
            continue
        luid = m.group(1).lower()
        kind = a.get("kind") or "Shared"
        adapters.setdefault(luid, {"Dedicated": 0.0, "Shared": 0.0})
        adapters[luid][kind] += float(a.get("val") or 0.0)
    return {"engines": engines, "mem": mem, "adapters": adapters, "luid_names": luid_names}


# --------------------------------------------------------------------------- #
# nvidia-smi                                                                   #
# --------------------------------------------------------------------------- #

def _nvidia_smi_path():
    for p in (r"C:\Windows\System32\nvidia-smi.exe",
              r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        if os.path.isfile(p):
            return p
    return "nvidia-smi"  # assume on PATH


def nvidia_smi_info():
    """Returns (compute: {pid: {"path": str, "vram_mb": float|None}},
                    gpu: {...} or None).  compute is {} when smi is unavailable."""
    smi = _nvidia_smi_path()
    compute, gpu = {}, None
    try:
        r = subprocess.run([smi, "--query-compute-apps=pid,process_name,used_gpu_memory",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                pid = int(parts[0]) if parts[0].isdigit() else None
                vram = None
                if len(parts) > 2 and parts[2] not in ("", "[N/A]", "N/A"):
                    try:
                        vram = float(parts[2])  # MiB
                    except ValueError:
                        vram = None
                compute[pid] = {"path": parts[1], "vram_mb": vram}
        else:
            compute = {}
        r2 = subprocess.run([smi, "--query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total",
                             "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=20)
        if r2.returncode == 0:
            p = [x.strip() for x in r2.stdout.splitlines()[0].split(",")]
            if len(p) >= 5:
                gpu = {"name": p[0], "driver": p[1], "util": p[2],
                       "mem_used_mb": p[3], "mem_total_mb": p[4]}
    except Exception:
        pass
    return compute, gpu


# --------------------------------------------------------------------------- #
# Inventory                                                                    #
# --------------------------------------------------------------------------- #

def build_inventory(probe=None, compute=None, gpu=None, prefs=None, procs=None):
    """Merge everything into rows. Everything optional so callers can cache."""
    if prefs is None:
        prefs = read_gpu_prefs()
    if procs is None:
        procs = snapshot_processes()
    if probe is None:
        probe = parse_probe(probe_gpu_counters())
    if compute is None and gpu is None:
        compute, gpu = nvidia_smi_info()
    elif compute is None:
        compute = {}
    eng, mem, adapters, luid_names = (probe.get(k, {}) for k in
                                      ("engines", "mem", "adapters", "luid_names"))

    rows = []
    seen = set()
    # 1) running processes with GPU activity
    for pid in sorted(set(eng) | set(mem) | set(compute)):
        p = procs.get(pid, {})
        exe = (p.get("exe") or (compute.get(pid) or {}).get("path") or "")
        g = eng.get(pid, {})
        util = g.get("util", 0.0)
        adap_util = g.get("adapters", {})
        adap_txt = ", ".join("%.1f%% %s" % (v, luid_names.get(k, "LUID " + k))
                             for k, v in sorted(adap_util.items(), key=lambda kv: -kv[1]))
        engtypes = g.get("engtypes", {})
        et_txt = " ".join("%s %.1f" % (et, v) for et, v in sorted(engtypes.items(),
                                                                  key=lambda kv: -kv[1]))
        mv = mem.get(pid, {})
        vram = (mv.get("Dedicated", 0.0) + mv.get("Shared", 0.0)) / 1048576.0
        vram_nv = None
        nv = pid in compute
        if nv:
            vram_nv = (compute[pid].get("vram_mb")
                       if compute[pid].get("vram_mb") is not None else None)
        key = exe.lower() if exe else ("pid:%d" % pid)
        saved = prefs.get(exe, {}).get("mode", 0) if exe in prefs else 0
        rows.append({"name": p.get("name") or os.path.basename(exe) or ("pid %d" % pid),
                     "path": exe or "",
                     "pid": pid,
                     "util": util,
                     "adapter": adap_txt,
                     "engtypes": et_txt,
                     "vram_mb": vram_nv if vram_nv is not None else vram,
                     "nvidia": nv,
                     "saved": saved,
                     "raw": prefs.get(exe, {}).get("raw", "") if exe in prefs else "",
                     "running": True,
                     "needs_restart": False})
        seen.add(key)
    # 2) registry entries for apps not currently running
    for path, info in prefs.items():
        if path.lower() in seen:
            continue
        rows.append({"name": os.path.basename(path) or path, "path": path, "pid": None,
                     "util": 0.0, "adapter": "", "engtypes": "", "vram_mb": 0.0,
                     "nvidia": False, "saved": info["mode"], "raw": info["raw"],
                     "running": False, "needs_restart": False})
    # 3) GPU summary for the status bar
    gpu_txt = ""
    if gpu:
        gpu_txt = "%s | driver %s | GPU %s%% | VRAM %s/%s MiB" % (
            gpu["name"], gpu["driver"], gpu["util"], gpu["mem_used_mb"], gpu["mem_total_mb"])
    rows.sort(key=lambda r: (-r["running"], -r["util"]))
    return rows, {"gpu": gpu_txt, "probe_fail": not bool(probe)}


# --------------------------------------------------------------------------- #
# GUI                                                                          #
# --------------------------------------------------------------------------- #

class App:
    COLS = [("name", "App", 240), ("path", "Executable", 300), ("util", "Live GPU", 110),
            ("vram_mb", "VRAM (MB)", 90), ("nvidia", "NVIDIA", 60), ("saved", "Saved pref", 130)]

    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1180x620")
        top = ttk.Frame(root, padding=4)
        top.pack(fill="x")
        self.filter_var = tk.StringVar()
        ttk.Label(top, text="Filter:").pack(side="left")
        ttk.Entry(top, textvariable=self.filter_var, width=24).pack(side="left", padx=4)
        self.filter_var.trace_add("write", lambda *a: self.refresh_rows())
        ttk.Button(top, text="Refresh now", command=self.do_refresh).pack(side="left", padx=6)
        self.auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Auto-refresh 5s", variable=self.auto,
                        command=self._toggle_auto).pack(side="left")
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(top, text="Power Saving  \u2192", command=lambda: self.apply_pref(1)).pack(side="left")
        ttk.Button(top, text="High Performance  \u2192", command=lambda: self.apply_pref(2)).pack(side="left")
        ttk.Button(top, text="Let Windows Decide  \u2192", command=lambda: self.apply_pref(0)).pack(side="left")

        wrap = ttk.Frame(root, padding=4)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in self.COLS],
                                 show="headings", selectmode="extended")
        for cid, label, w in self.COLS:
            self.tree.heading(cid, text=label, command=lambda c=cid: self._sort(c))
            self.tree.column(cid, width=w, anchor="w")
        self.tree.tag_configure("running", background="#f2f7ff")
        self.tree.tag_configure("changed", background="#ffe9c7")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(root, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

        self.rows = []
        self._sort_col, self._sort_desc = None, False
        self._busy = False
        self._refresh_again = False
        self.q = queue.Queue()
        self.root.after(50, self._pump)
        self.do_refresh()

    # -- data -- ----------------------------------------------------------
    def do_refresh(self):
        if self._busy:
            return
        self._busy = True
        self.status.set("Scanning GPU counters, nvidia-smi, registry...")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            # phase 1: registry + processes (fast) -- table is usable at once
            prefs = read_gpu_prefs()
            procs = snapshot_processes()
            rows0, _meta = build_inventory(probe={}, compute={}, gpu=None,
                                           prefs=prefs, procs=procs)
            self.q.put(("partial", rows0))
            # phase 2: GPU counters + nvidia-smi (slow, ~5-8s on cold start)
            probe = parse_probe(probe_gpu_counters())
            compute, gpu = nvidia_smi_info()
            rows, meta = build_inventory(probe=probe, compute=compute, gpu=gpu,
                                         prefs=prefs, procs=procs)
            self.q.put(("done", rows, meta))
        except Exception as e:  # pragma: no cover
            self.q.put(("err", str(e)))

    def _pump(self):
        try:
            while True:
                kind, *args = self.q.get_nowait()
                if kind == "partial":
                    rows, = args
                    self.rows = rows
                    self.refresh_rows()
                    self.status.set("Gathering live GPU counters (%d apps)..."
                                    % len(rows))
                elif kind == "done":
                    rows, meta = args
                    self.rows = rows
                    self._busy = False
                    self.refresh_rows()
                    n = len(rows)
                    run = sum(1 for r in rows if r["running"])
                    self.status.set("GPU Preference Tuner | %d apps (%d running) | %s"
                                    % (n, run, meta["gpu"] or "nvidia-smi unavailable"))
                    if self._refresh_again:
                        # a settings change landed while this scan was running:
                        # re-scan so live columns reflect the new state
                        self._refresh_again = False
                        self.do_refresh()
                    elif self.auto.get():
                        self.root.after(5000, self.do_refresh)
                elif kind == "err":
                    self._busy = False
                    self.status.set("Error: %s" % args[0])
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    def _toggle_auto(self):
        if self.auto.get() and not self._busy:
            self.root.after(5000, self.do_refresh)

    # -- rows -- ----------------------------------------------------------
    def refresh_rows(self):
        self.tree.delete(*self.tree.get_children())
        filt = self.filter_var.get().strip().lower()
        for i, r in enumerate(self.rows):
            if filt and filt not in (r["name"] + " " + r["path"]).lower():
                continue
            util = "%.1f%%" % r["util"] if r["running"] else "not running"
            if r["engtypes"] and r["running"]:
                util += "  [%s]" % r["engtypes"]
            if r["adapter"] and r["running"]:
                util += "  (%s)" % r["adapter"]
            pref = PREF_LABEL.get(r["saved"], str(r["saved"]))
            if r.get("needs_restart"):
                pref += "  \u21bb restart"
            tag = "changed" if r.get("needs_restart") else ("running" if r["running"] else None)
            self.tree.insert("", "end", iid=str(i), values=(
                r["name"], r["path"] or "", util,
                "%.0f" % r["vram_mb"] if r["vram_mb"] else "",
                "yes" if r["nvidia"] else "", pref), tags=(tag,) if tag else ())

    def _sort(self, col):
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col, self._sort_desc = col, False
        def key(r):
            v = r.get(col)
            if col in ("util", "vram_mb"):
                return (v if isinstance(v, (int, float)) else 0.0)
            return str(v if v is not None else "").lower()
        self.rows.sort(key=key, reverse=self._sort_desc)
        self.refresh_rows()

    # -- actions -- -------------------------------------------------------
    def selected_rows(self):
        sel = [int(i) for i in self.tree.selection()]
        return [self.rows[i] for i in sel]

    def apply_pref(self, mode):
        rows = self.selected_rows()
        if not rows:
            self.status.set("Select one or more apps first.")
            return
        done, failed, restarts = [], [], []
        for r in rows:
            if not r["path"]:
                failed.append(r["name"] + " (no exe path)")
                continue
            try:
                old, new = set_gpu_pref(r["path"], mode)
                done.append(r["name"])
                # update the row in place: the Saved pref column reflects the
                # change immediately, no full rescan needed for it
                r["saved"] = mode
                r["raw"] = new or ""
                if r["running"] and gpu_mode_of(old or "") != mode:
                    restarts.append(r["name"])
                    r["needs_restart"] = True
            except GpuPrefError as e:
                failed.append(str(e))
        txt = (["%d app(s) updated: %s" % (len(done), ", ".join(done[:6]))] +
               (["restart required for: %s" % ", ".join(restarts[:6])] if restarts else []) +
               (["FAILED: %s" % "; ".join(failed[:3])] if failed else []))
        self.status.set(" | ".join(txt))
        self.refresh_rows()                       # immediate column update
        self._refresh_again = True                # re-scan live data (queued if busy)
        self.do_refresh()


def self_test():
    """Headless verification of every backend (registry round-trip included)."""
    print("== GPU Preference Tuner self-test ==")
    ok = True

    def chk(name, cond, extra=""):
        nonlocal ok
        ok = ok and cond
        print(("PASS" if cond else "FAIL"), "-", name, extra)

    import winreg
    # 1. registry read
    prefs = read_gpu_prefs()
    chk("registry read", isinstance(prefs, dict))
    for p, i in list(prefs.items())[:6]:
        print("     %s = %r  -> mode %s" % (p, i["raw"], PREF_LABEL[i["mode"]]))

    # 2. registry write round-trip (self-reverting, harmless HKCU entry)
    probe_path = r"C:\GPUPrefTuner__self_test__.exe"
    old_global = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            pass
    except OSError:
        pass
    try:
        _o, _n = set_gpu_pref(probe_path, 2)
        chk("write GpuPreference=2", _n == "GpuPreference=2;", "-> %r" % _n)
        r1 = read_gpu_prefs().get(probe_path, {}).get("mode")
        chk("read-back mode 2", r1 == 2, "mode=%s" % r1)
        _o, _n = set_gpu_pref(probe_path, 1)
        r2 = read_gpu_prefs().get(probe_path, {}).get("mode")
        chk("rewrite to mode 1 (overwrites in place)", r2 == 1)
        _o, _n = set_gpu_pref(probe_path, 0)
        _after = read_gpu_prefs().get(probe_path)
        chk("clear mode (token removed, value deleted)", _after is None)
    finally:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as k:
                try:
                    winreg.DeleteValue(k, probe_path)
                except OSError:
                    pass
        except OSError:
            pass
    print("   (cleanup: dummy value deleted)")

    # 3. process snapshot
    procs = snapshot_processes()
    chk("process snapshot", len(procs) > 10, "(%d pids)" % len(procs))
    sample = next((p for p in procs.values() if p["exe"]), None)
    chk("exe path resolution", sample is not None, "e.g. %s" % (sample["exe"] if sample else ""))

    # 4. GPU counters
    probe = parse_probe(probe_gpu_counters())
    n_eng = sum(len(e) for e in [probe["engines"]])
    chk("GPU Engine counters", n_eng > 0 and any(g["util"] >= 0 for g in probe["engines"].values()),
        "(%d pids with engines)" % n_eng)
    chk("GPU Process Memory counters", len(probe["mem"]) > 0, "(%d pids)" % len(probe["mem"]))
    chk("adapter LUID name mapping", len(probe["luid_names"]) > 0,
        "(%s)" % ", ".join(probe["luid_names"].values()))

    # 5. nvidia-smi
    compute, gpu = nvidia_smi_info()
    chk("nvidia-smi compute-apps", len(compute) > 0 or gpu is None,
        "(pid entries: %d)" % len(compute))
    if gpu:
        chk("nvidia-smi GPU info", bool(gpu["name"]), "(%s driver %s)" % (gpu["name"], gpu["driver"]))

    # 6. merged inventory
    rows, meta = build_inventory(probe=probe, compute=compute, gpu=gpu, prefs=prefs, procs=procs)
    chk("inventory merge", len(rows) >= len(prefs), "(%d rows)" % len(rows))
    for r in rows[:5]:
        print("     %-28s %-38s util=%6.1f%% vram=%7.0f nv=%s saved=%s"
              % (r["name"][:28], (r["path"] or "")[-37:], r["util"], r["vram_mb"],
                 r["nvidia"], PREF_LABEL[r["saved"]]))

    print("\nSELFTEST:", "ALL PASS" if ok else "SOME FAILURES - see above")
    return 0 if ok else 1


def headless_dump():
    rows, meta = build_inventory()
    print(meta["gpu"])
    for r in rows:
        print("%-30s %-50s %6.1f%% %8.0fMB %-4s %s" % (
            r["name"][:30], r["path"][:50], r["util"], r["vram_mb"],
            "NV" if r["nvidia"] else "--", PREF_LABEL[r["saved"]]))
    return 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    if "--headless" in sys.argv:
        return headless_dump()
    root = tk.Tk()
    try:
        import ctypes as _c
        _c.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())