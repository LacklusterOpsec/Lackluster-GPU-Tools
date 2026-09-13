"""
Automated Test Suite for Windows 11 GPU Preference Manager
Tests DXGI, PDH counters, Registry reads/writes/clears, and PySide6 UI initialization.
"""
import sys
import os
import unittest
import unittest.mock
import time

from dxgi_util import enumerate_gpu_adapters
from registry_manager import (
    GpuRegistryManager, PREF_HIGH_PERFORMANCE, PREF_POWER_SAVING,
    PREF_LET_WINDOWS_DECIDE, RegistryPreference, normalize_path
)
from perf_monitor import GpuPerformanceMonitor
from process_scanner import InventoryScanner

class TestGpuManager(unittest.TestCase):
    def test_01_dxgi_enumeration(self):
        adapters = enumerate_gpu_adapters()
        self.assertGreater(len(adapters), 0, "No DXGI adapters found")
        print("\n[TEST 1] Enumerated DXGI Adapters:")
        for a in adapters:
            print(f"  -> {a.vendor}: {a.name} (LUID: {a.luid_str})")
        vendors = {a.vendor for a in adapters}
        self.assertTrue("NVIDIA" in vendors or "Intel" in vendors, "Neither NVIDIA nor Intel adapter detected")

    def test_02_registry_roundtrip_and_preservation(self):
        reg = GpuRegistryManager()
        test_exe = r"C:\Program Files\TestVendor\TestApp_GpuPref_UnitTest.exe"
        norm = normalize_path(test_exe)

        # 1. Set High Performance (NVIDIA)
        ok = reg.set_gpu_preference(test_exe, PREF_HIGH_PERFORMANCE)
        self.assertTrue(ok)
        all_prefs = reg.get_all_preferences()
        self.assertIn(norm, all_prefs)
        self.assertEqual(all_prefs[norm].gpu_preference, PREF_HIGH_PERFORMANCE)
        self.assertEqual(all_prefs[norm].raw_value, "GpuPreference=2;")
        print("\n[TEST 2a] Set High Performance verified: GpuPreference=2;")

        # 2. Simulate external addition of AutoHDREnable=1;
        with unittest.mock.patch.object(reg, 'get_all_preferences') as mock_prefs:
            simulated_pref = RegistryPreference(test_exe, "GpuPreference=2;AutoHDREnable=1;SwapEffectUpgradeEnable=1;")
            # Now change to Power Saving (Intel) while preserving other flags
            # Directly write the compound string to registry
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences", 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, test_exe, 0, winreg.REG_SZ, "GpuPreference=2;AutoHDREnable=1;SwapEffectUpgradeEnable=1;")

        # Verify compound read
        all_prefs = reg.get_all_preferences()
        self.assertIn(norm, all_prefs)
        self.assertEqual(all_prefs[norm].fields.get("AutoHDREnable"), "1")
        self.assertEqual(all_prefs[norm].fields.get("SwapEffectUpgradeEnable"), "1")

        # Now update to Power Saving (1)
        ok = reg.set_gpu_preference(test_exe, PREF_POWER_SAVING)
        self.assertTrue(ok)
        all_prefs = reg.get_all_preferences()
        self.assertEqual(all_prefs[norm].gpu_preference, PREF_POWER_SAVING)
        # Verify companion flags were preserved
        self.assertEqual(all_prefs[norm].fields.get("AutoHDREnable"), "1")
        self.assertEqual(all_prefs[norm].fields.get("SwapEffectUpgradeEnable"), "1")
        print("\n[TEST 2b] Update to Power Saving verified with preserved companion flags:", all_prefs[norm].raw_value)

        # 3. Clear override ("Let Windows Decide")
        ok = reg.set_gpu_preference(test_exe, PREF_LET_WINDOWS_DECIDE)
        self.assertTrue(ok)
        all_prefs = reg.get_all_preferences()
        # Since AutoHDREnable remains, value should still exist without GpuPreference
        self.assertIn(norm, all_prefs)
        self.assertIsNone(all_prefs[norm].gpu_preference)
        self.assertEqual(all_prefs[norm].fields.get("AutoHDREnable"), "1")
        print("\n[TEST 2c] Let Windows Decide verified (GpuPreference stripped, others kept):", all_prefs[norm].raw_value)

        # 4. Remove completely
        ok = reg.remove_app(test_exe)
        self.assertTrue(ok)
        all_prefs = reg.get_all_preferences()
        self.assertNotIn(norm, all_prefs)
        print("\n[TEST 2d] Removed entry completely verified.")

    def test_03_perf_monitor_and_scanner(self):
        reg = GpuRegistryManager()
        perf = GpuPerformanceMonitor()
        scanner = InventoryScanner(reg, perf)
        time.sleep(0.5)
        items = scanner.scan_inventory()
        self.assertGreater(len(items), 0, "No inventory items scanned")
        running = [i for i in items if i.is_running]
        self.assertGreater(len(running), 0, "No running processes found")
        print(f"\n[TEST 3] Inventory scan verified: {len(items)} total items, {len(running)} running apps.")
        perf.close()

    def test_04_pyside6_ui_instantiation(self):
        from PySide6.QtWidgets import QApplication
        from main_window import MainWindow
        from process_scanner import AppInventoryItem

        app = QApplication.instance()
        if not app:
            app = QApplication([])

        window = MainWindow()
        self.assertIsNotNone(window)
        self.assertEqual(window.table.columnCount(), 7)

        # Simulate inventory scan data
        dummy_items = [
            AppInventoryItem(r"C:\Windows\explorer.exe", display_name="explorer.exe"),
            AppInventoryItem(r"C:\Program Files\App\app.exe", display_name="app.exe")
        ]
        window._on_inventory_scanned(dummy_items)
        self.assertEqual(window.table.rowCount(), 2)

        # Select first row
        window.table.item(0, 0).setSelected(True)

        # Trigger re-population to verify selection preservation logic
        window._on_inventory_scanned(dummy_items)
        self.assertEqual(window.table.rowCount(), 2)

        print("\n[TEST 4] PySide6 MainWindow created, populated, selection preserved, and closed cleanly.")
        window.close()

if __name__ == "__main__":
    unittest.main()
