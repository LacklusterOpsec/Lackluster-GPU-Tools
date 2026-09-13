"""
Registry Manager for Windows 11 DirectX Per-App GPU Preferences
Key: HKEY_CURRENT_USER\\Software\\Microsoft\\DirectX\\UserGpuPreferences
"""
import winreg
import os
import re
from typing import Dict, Optional, Tuple, Any

REG_KEY_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"

# Preference Constants
PREF_LET_WINDOWS_DECIDE = 0
PREF_POWER_SAVING = 1      # Intel / Integrated
PREF_HIGH_PERFORMANCE = 2  # NVIDIA / Discrete

PREF_LABELS = {
    PREF_LET_WINDOWS_DECIDE: "Let Windows Decide",
    PREF_POWER_SAVING: "Power Saving (Intel)",
    PREF_HIGH_PERFORMANCE: "High Performance (NVIDIA)",
}

def normalize_path(path: str) -> str:
    """Normalizes a Windows filesystem path to avoid duplicate entries with different casings."""
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(path.strip().strip('"')))

class RegistryPreference:
    def __init__(self, raw_path: str, raw_value: str):
        self.raw_path = raw_path
        self.norm_path = normalize_path(raw_path)
        self.raw_value = raw_value
        self.fields: Dict[str, str] = self._parse_fields(raw_value)

    @staticmethod
    def _parse_fields(value_str: str) -> Dict[str, str]:
        fields = {}
        if not value_str:
            return fields
        for part in value_str.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                fields[k.strip()] = v.strip()
            else:
                fields[part] = ""
        return fields

    @property
    def gpu_preference(self) -> Optional[int]:
        if "GpuPreference" in self.fields:
            try:
                return int(self.fields["GpuPreference"])
            except ValueError:
                return None
        return None

    @property
    def label(self) -> str:
        pref = self.gpu_preference
        if pref is not None and pref in PREF_LABELS:
            return PREF_LABELS[pref]
        return "Not Set"

    def serialize(self) -> str:
        """Serializes back into the Windows 11 semicolon-terminated format."""
        tokens = []
        for k, v in self.fields.items():
            if v != "":
                tokens.append(f"{k}={v};")
            else:
                tokens.append(f"{k};")
        return "".join(tokens)


class GpuRegistryManager:
    def __init__(self):
        self._ensure_key_exists()

    def _ensure_key_exists(self):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH) as key:
                pass
        except Exception as e:
            print(f"Failed to ensure registry key exists: {e}")

    def get_all_preferences(self) -> Dict[str, RegistryPreference]:
        """
        Reads all saved preferences from HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences.
        Returns a dict mapping normalized path to RegistryPreference.
        """
        prefs: Dict[str, RegistryPreference] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
                num_values = winreg.QueryInfoKey(key)[1]
                for i in range(num_values):
                    try:
                        name, val, val_type = winreg.EnumValue(key, i)
                        # Filter out internal DirectX global settings
                        if name.lower() in ("directxuserglobalsettings", "graphicsfeaturesnotificationconfig"):
                            continue
                        if val_type == winreg.REG_SZ:
                            pref_obj = RegistryPreference(name, val)
                            prefs[pref_obj.norm_path] = pref_obj
                    except Exception:
                        continue
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Error reading registry preferences: {e}")
        return prefs

    def set_gpu_preference(self, exe_path: str, preference: int) -> bool:
        """
        Sets the GPU preference for the given executable path.
        preference: 1 (Power Saving), 2 (High Performance), or 0 (Let Windows Decide).
        Preserves any other companion settings (e.g. AutoHDREnable, SwapEffectUpgradeEnable).
        """
        norm = normalize_path(exe_path)
        if not norm:
            return False

        all_prefs = self.get_all_preferences()
        existing = all_prefs.get(norm)

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                if preference == PREF_LET_WINDOWS_DECIDE:
                    # Clear override
                    if existing:
                        # Remove GpuPreference key
                        existing.fields.pop("GpuPreference", None)
                        if existing.fields:
                            # Still has other flags (like AutoHDREnable), update it
                            winreg.SetValueEx(key, existing.raw_path, 0, winreg.REG_SZ, existing.serialize())
                        else:
                            # Empty, delete the value entirely
                            try:
                                winreg.DeleteValue(key, existing.raw_path)
                            except FileNotFoundError:
                                pass
                    return True

                # Setting Power Saving (1) or High Performance (2)
                if existing:
                    existing.fields["GpuPreference"] = str(preference)
                    target_name = existing.raw_path
                    serialized = existing.serialize()
                else:
                    target_name = exe_path  # use passed original casing/path
                    serialized = f"GpuPreference={preference};"

                winreg.SetValueEx(key, target_name, 0, winreg.REG_SZ, serialized)
                return True
        except Exception as e:
            print(f"Error setting registry preference for {exe_path}: {e}")
            return False

    def remove_app(self, exe_path: str) -> bool:
        """Completely removes any preference entry for the given executable path."""
        norm = normalize_path(exe_path)
        all_prefs = self.get_all_preferences()
        existing = all_prefs.get(norm)
        if not existing:
            return True

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_WRITE) as key:
                winreg.DeleteValue(key, existing.raw_path)
                return True
        except Exception as e:
            print(f"Error removing registry entry for {exe_path}: {e}")
            return False


if __name__ == "__main__":
    mgr = GpuRegistryManager()
    prefs = mgr.get_all_preferences()
    print(f"Found {len(prefs)} saved preferences:")
    for path, p in prefs.items():
        print(f"  {p.raw_path} => {p.label} (raw: '{p.raw_value}')")
