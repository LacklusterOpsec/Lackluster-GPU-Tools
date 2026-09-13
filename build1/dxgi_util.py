"""
DXGI Utility: Enumerates physical GPU adapters, Vendor IDs, and LUIDs using native DXGI API via ctypes.
"""
import ctypes
from ctypes import wintypes
from typing import List, Dict, Optional

class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG)
    ]

class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
        ("Flags", wintypes.UINT)
    ]

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8)
    ]

VENDOR_NVIDIA = 0x10DE
VENDOR_INTEL = 0x8086
VENDOR_AMD = 0x1002
VENDOR_MICROSOFT = 0x1414

def get_vendor_name(vendor_id: int) -> str:
    if vendor_id == VENDOR_NVIDIA:
        return "NVIDIA"
    elif vendor_id == VENDOR_INTEL:
        return "Intel"
    elif vendor_id == VENDOR_AMD:
        return "AMD"
    elif vendor_id == VENDOR_MICROSOFT:
        return "Microsoft"
    return "Unknown"

class GpuAdapterInfo:
    def __init__(self, index: int, name: str, vendor_id: int, luid_str: str, vram_mb: int, flags: int):
        self.index = index
        self.name = name
        self.vendor_id = vendor_id
        self.vendor = get_vendor_name(vendor_id)
        self.luid_str = luid_str.lower()
        self.vram_mb = vram_mb
        self.is_software = bool(flags & 2)  # DXGI_ADAPTER_FLAG_SOFTWARE

    def __repr__(self):
        return f"<GpuAdapter {self.index}: {self.name} ({self.vendor}) LUID={self.luid_str} VRAM={self.vram_mb}MB>"

def enumerate_gpu_adapters() -> List[GpuAdapterInfo]:
    adapters: List[GpuAdapterInfo] = []
    try:
        dxgi = ctypes.oledll.LoadLibrary("dxgi.dll")
        factory = ctypes.c_void_p()
        # IID_IDXGIFactory1: {770aae78-f26f-4dba-a829-253c83d1b387}
        iid_factory1 = GUID(0x770aae78, 0xf26f, 0x4dba, (wintypes.BYTE * 8)(0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))
        hr = dxgi.CreateDXGIFactory1(ctypes.byref(iid_factory1), ctypes.byref(factory))
        if hr != 0 or not factory.value:
            return adapters

        vtable = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
        # EnumAdapters1 is at index 12 in IDXGIFactory1
        EnumAdapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(vtable[12])

        i = 0
        while True:
            adapter = ctypes.c_void_p()
            res = EnumAdapters1(factory, i, ctypes.byref(adapter))
            if res != 0 or not adapter.value:
                break
            i += 1
            adapter_vtable = ctypes.cast(ctypes.cast(adapter, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
            # GetDesc1 is at index 10 in IDXGIAdapter1
            GetDesc1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1))(adapter_vtable[10])
            desc = DXGI_ADAPTER_DESC1()
            if GetDesc1(adapter, ctypes.byref(desc)) == 0:
                luid_str = f"0x{desc.AdapterLuid.HighPart:08x}_0x{desc.AdapterLuid.LowPart:08x}".lower()
                # Skip pure software/Basic Render Driver if real hardware exists
                is_sw = bool(desc.Flags & 2)
                adapters.append(GpuAdapterInfo(
                    index=i - 1,
                    name=desc.Description,
                    vendor_id=desc.VendorId,
                    luid_str=luid_str,
                    vram_mb=desc.DedicatedVideoMemory // (1024 * 1024),
                    flags=desc.Flags
                ))
            # Release adapter: index 2
            Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(adapter_vtable[2])
            Release(adapter)

        # Release factory: index 2
        ReleaseFac = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
        ReleaseFac(factory)
    except Exception as e:
        print(f"Error enumerating DXGI adapters: {e}")

    return adapters

if __name__ == "__main__":
    for a in enumerate_gpu_adapters():
        print(a)
