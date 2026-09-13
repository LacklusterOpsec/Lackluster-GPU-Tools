"""
PySide6 Modern, Ultra-Fast Table Model Architecture
for Windows 11 GPU Preference Manager & Live Monitor
"""
import os
import sys
import subprocess
from datetime import datetime
from typing import List, Optional, Set, Dict, Any

from PySide6.QtCore import (
    Qt, QThread, Signal, QTimer, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
)
from PySide6.QtGui import (
    QColor, QCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableView,
    QHeaderView, QFileDialog, QMessageBox, QMenu, QCheckBox,
    QFrame, QStatusBar
)

from dxgi_util import enumerate_gpu_adapters
from registry_manager import (
    GpuRegistryManager, PREF_HIGH_PERFORMANCE, PREF_POWER_SAVING,
    PREF_LET_WINDOWS_DECIDE, normalize_path
)
from perf_monitor import GpuPerformanceMonitor
from process_scanner import InventoryScanner, AppInventoryItem


DARK_STYLESHEET = """
QMainWindow {
    background-color: #0f1117;
    color: #e2e8f0;
}
QWidget {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    color: #cbd5e1;
}

#headerWidget {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a1e2e, stop:1 #161925);
    border-bottom: 1px solid #283046;
    padding: 14px 20px;
}
#appTitle {
    font-size: 19px;
    font-weight: 700;
    color: #f8fafc;
}
#appSubtitle {
    font-size: 12px;
    color: #94a3b8;
    margin-top: 2px;
}
.kpi-card {
    background-color: #171b26;
    border: 1px solid #232a3d;
    border-radius: 8px;
    padding: 8px 14px;
}
.kpi-title {
    font-size: 11px;
    color: #64748b;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.kpi-value {
    font-size: 18px;
    font-weight: 700;
    color: #f1f5f9;
}

#toolbarWidget {
    background-color: #131620;
    border-bottom: 1px solid #1e2436;
    padding: 10px 20px;
}
QLineEdit {
    background-color: #1a1e2d;
    border: 1px solid #2e3852;
    border-radius: 6px;
    padding: 6px 12px;
    color: #f8fafc;
    font-size: 13px;
    min-height: 20px;
}
QLineEdit:focus {
    border: 1px solid #3b82f6;
    background-color: #1e2336;
}

QPushButton {
    background-color: #1e2438;
    border: 1px solid #2e3854;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 12px;
    color: #e2e8f0;
}
QPushButton:hover {
    background-color: #28324e;
    border-color: #3b4b72;
}
QPushButton:pressed {
    background-color: #192033;
}
#btnHighPerf {
    background-color: #102e21;
    border: 1px solid #10b981;
    color: #6ee7b7;
}
#btnHighPerf:hover {
    background-color: #13422e;
    border-color: #34d399;
}
#btnPowerSave {
    background-color: #132742;
    border: 1px solid #3b82f6;
    color: #93c5fd;
}
#btnPowerSave:hover {
    background-color: #1a385f;
    border-color: #60a5fa;
}
#btnWindowsDecide {
    background-color: #282119;
    border: 1px solid #f59e0b;
    color: #fcd34d;
}
#btnWindowsDecide:hover {
    background-color: #3d3121;
    border-color: #fbbf24;
}
#btnAddCustom {
    background-color: #241d38;
    border: 1px solid #8b5cf6;
    color: #c4b5fd;
}
#btnAddCustom:hover {
    background-color: #342a52;
    border-color: #a78bfa;
}

/* Virtualized Table View */
QTableView {
    background-color: #0d0f16;
    border: none;
    gridline-color: #161c2b;
    selection-background-color: #1e2d4a;
    selection-color: #ffffff;
    alternate-background-color: #10131d;
    outline: none;
}
QTableView::item {
    padding: 6px 10px;
    border-bottom: 1px solid #141926;
}
QTableView::item:selected {
    background-color: #1e2d4a;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #151824;
    color: #94a3b8;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: none;
    border-bottom: 2px solid #232b3f;
    border-right: 1px solid #1b2131;
}
QHeaderView::section:hover {
    background-color: #1c2133;
    color: #f1f5f9;
}

QScrollBar:vertical {
    background-color: #0f1118;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #262e44;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background-color: #3b4768;
}
QScrollBar:horizontal {
    background-color: #0f1118;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background-color: #262e44;
    min-width: 20px;
    border-radius: 5px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
}

QMenu {
    background-color: #181d2c;
    border: 1px solid #2e3852;
    border-radius: 6px;
    padding: 5px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
    color: #e2e8f0;
}
QMenu::item:selected {
    background-color: #2b354f;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background-color: #2a334a;
    margin: 4px 6px;
}

QStatusBar {
    background-color: #11141e;
    color: #64748b;
    border-top: 1px solid #1c2233;
    padding: 4px 12px;
}
"""

COLUMNS = [
    "Application",
    "Status",
    "Live GPU Activity",
    "Saved Preference",
    "Restart Required",
    "PID(s)",
    "Executable Path"
]

COLOR_RUNNING = QColor("#4ade80")
COLOR_SAVED = QColor("#64748b")
COLOR_NVIDIA = QColor("#34d399")
COLOR_INTEL = QColor("#60a5fa")
COLOR_HYBRID = QColor("#a78bfa")
COLOR_WARN = QColor("#fbbf24")
COLOR_RESTART = QColor("#f87171")
COLOR_UNSET = QColor("#475569")
COLOR_MUTED = QColor("#334155")
COLOR_PID = QColor("#94a3b8")
COLOR_PATH = QColor("#64748b")


class GpuInventoryModel(QAbstractTableModel):
    """
    High-performance, purely virtualized model for QTableView.
    Allocates zero QWidget items, guaranteeing 60 FPS scrolling and instantaneous updates.
    """
    def __init__(self):
        super().__init__()
        self.items: List[AppInventoryItem] = []
        self._path_to_row: Dict[str, int] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(COLUMNS):
                return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self.items):
            return None

        it = self.items[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return it.display_name
            elif col == 1:
                return "🟢 Running" if it.is_running else "⚪ Saved Only"
            elif col == 2:
                return it.live_gpu_summary
            elif col == 3:
                return it.saved_pref_label
            elif col == 4:
                return "⚠️ Restart Needed" if it.pending_restart else "—"
            elif col == 5:
                return ", ".join(str(p) for p in it.pids) if it.pids else "—"
            elif col == 6:
                return it.exe_path

        elif role == Qt.ForegroundRole:
            if col == 1:
                return COLOR_RUNNING if it.is_running else COLOR_SAVED
            elif col == 2:
                gpu_text = it.live_gpu_summary
                if "NVIDIA" in gpu_text and "Intel" in gpu_text:
                    return COLOR_HYBRID
                elif "NVIDIA" in gpu_text:
                    return COLOR_NVIDIA
                elif "Intel" in gpu_text:
                    return COLOR_INTEL
                return COLOR_SAVED
            elif col == 3:
                if it.saved_pref == PREF_HIGH_PERFORMANCE:
                    return COLOR_NVIDIA
                elif it.saved_pref == PREF_POWER_SAVING:
                    return COLOR_INTEL
                elif it.saved_pref == PREF_LET_WINDOWS_DECIDE or (it.has_saved_entry and it.saved_pref is None):
                    return COLOR_WARN
                return COLOR_UNSET
            elif col == 4:
                return COLOR_RESTART if it.pending_restart else COLOR_MUTED
            elif col == 5:
                return COLOR_PID
            elif col == 6:
                return COLOR_PATH

        elif role == Qt.ToolTipRole:
            if col == 0 or col == 6:
                return f"{it.display_name}\nPath: {it.exe_path}"
            elif col == 4 and it.pending_restart:
                return it.restart_reason or "Preference modified while application is running"

        elif role == Qt.UserRole:
            return it.norm_path

        return None

    def update_data(self, new_items: List[AppInventoryItem]):
        """
        Updates the table data.
        If row count and order match, updates cells in-place via dataChanged (<0.1ms).
        Otherwise, resets model.
        """
        # Check if items match existing rows exactly
        can_in_place = (len(new_items) == len(self.items))
        if can_in_place:
            for i in range(len(new_items)):
                if new_items[i].norm_path != self.items[i].norm_path:
                    can_in_place = False
                    break

        if can_in_place:
            self.items = new_items
            top_left = self.index(0, 1)
            bottom_right = self.index(len(self.items) - 1, 5)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.ForegroundRole, Qt.ToolTipRole])
        else:
            self.beginResetModel()
            self.items = new_items
            self._path_to_row = {it.norm_path: idx for idx, it in enumerate(new_items)}
            self.endResetModel()


class GpuFilterProxyModel(QSortFilterProxyModel):
    """Filter and sort proxy model running in C++ Qt speed."""
    def __init__(self):
        super().__init__()
        self.category_filter = "ALL"
        self.search_query = ""

    def set_category_filter(self, cat: str):
        self.category_filter = cat
        self.invalidateFilter()

    def set_search_query(self, q: str):
        self.search_query = q.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model: GpuInventoryModel = self.sourceModel()
        if source_row >= len(model.items):
            return False

        it = model.items[source_row]

        # Search query matching
        if self.search_query:
            if (self.search_query not in it.display_name.lower() and
                self.search_query not in it.exe_path.lower()):
                return False

        # Category filters
        if self.category_filter == "RUNNING" and not it.is_running:
            return False
        if self.category_filter == "ACTIVE_GPU" and not (it.nvidia_in_smi or it.nvidia_util > 0.05 or it.intel_util > 0.05):
            return False
        if self.category_filter == "CONFIGURED" and not it.has_saved_entry:
            return False
        if self.category_filter == "RESTART" and not it.pending_restart:
            return False

        return True


class WorkerThread(QThread):
    inventory_ready = Signal(list)

    def __init__(self, scanner: InventoryScanner):
        super().__init__()
        self.scanner = scanner

    def run(self):
        try:
            items = self.scanner.scan_inventory()
            self.inventory_ready.emit(items)
        except Exception as e:
            print(f"Background worker scan error: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Windows 11 GPU Preference Manager & Live Monitor")
        self.resize(1200, 750)
        self.setStyleSheet(DARK_STYLESHEET)

        # Core components
        self.reg_mgr = GpuRegistryManager()
        self.perf_mon = GpuPerformanceMonitor()
        self.scanner = InventoryScanner(self.reg_mgr, self.perf_mon)
        self.cached_items: List[AppInventoryItem] = []

        self._init_ui()
        self._init_worker()

        # Auto-refresh timer (every 2.5 seconds)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.trigger_refresh)
        self.refresh_timer.start(2500)

        # First load
        self.trigger_refresh()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Header with GPU detected info & KPI cards
        header = QWidget()
        header.setObjectName("headerWidget")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_box = QVBoxLayout()
        title_lbl = QLabel("GPU Preference Manager & Live Monitor")
        title_lbl.setObjectName("appTitle")
        
        adapters = self.perf_mon.adapters
        adapter_names = " | ".join([f"{a.vendor}: {a.name}" for a in adapters if not a.is_software])
        if not adapter_names:
            adapter_names = "Standard Graphics Infrastructure"
        sub_lbl = QLabel(f"DirectX 12 / WDDM • {adapter_names}")
        sub_lbl.setObjectName("appSubtitle")
        
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        # KPI Cards
        self.kpi_total = self._create_kpi_card("Total Apps", "0")
        self.kpi_running = self._create_kpi_card("Running", "0")
        self.kpi_nvidia = self._create_kpi_card("On NVIDIA", "0", color="#34d399")
        self.kpi_intel = self._create_kpi_card("On Intel", "0", color="#60a5fa")
        self.kpi_saved = self._create_kpi_card("Configured", "0", color="#fcd34d")
        self.kpi_restart = self._create_kpi_card("Needs Restart", "0", color="#f87171")

        header_layout.addWidget(self.kpi_total)
        header_layout.addWidget(self.kpi_running)
        header_layout.addWidget(self.kpi_nvidia)
        header_layout.addWidget(self.kpi_intel)
        header_layout.addWidget(self.kpi_saved)
        header_layout.addWidget(self.kpi_restart)

        root_layout.addWidget(header)

        # 2. Controls & Actions Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("toolbarWidget")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        tb_layout.setSpacing(10)

        # Search box with debounce
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(120)
        self.search_timer.timeout.connect(self._on_search_debounced)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search by executable or path...")
        self.search_input.setFixedWidth(280)
        self.search_input.textChanged.connect(lambda: self.search_timer.start(120))
        tb_layout.addWidget(self.search_input)

        # Filter buttons
        self.btn_filter_all = QPushButton("All")
        self.btn_filter_running = QPushButton("Running")
        self.btn_filter_active = QPushButton("Active on GPU")
        self.btn_filter_configured = QPushButton("Configured")
        self.btn_filter_restart = QPushButton("Needs Restart")

        for b, f_val in [
            (self.btn_filter_all, "ALL"),
            (self.btn_filter_running, "RUNNING"),
            (self.btn_filter_active, "ACTIVE_GPU"),
            (self.btn_filter_configured, "CONFIGURED"),
            (self.btn_filter_restart, "RESTART")
        ]:
            b.setCheckable(True)
            b.clicked.connect(lambda checked, v=f_val: self._set_filter(v))
            tb_layout.addWidget(b)

        self.btn_filter_all.setChecked(True)
        tb_layout.addSpacing(15)

        # Bulk Actions
        self.btn_high_perf = QPushButton("⚡ High Performance (NVIDIA)")
        self.btn_high_perf.setObjectName("btnHighPerf")
        self.btn_high_perf.setToolTip("Set selected applications to High Performance (Discrete NVIDIA GPU)")
        self.btn_high_perf.clicked.connect(lambda: self._apply_bulk_preference(PREF_HIGH_PERFORMANCE))

        self.btn_power_save = QPushButton("🍃 Power Saving (Intel)")
        self.btn_power_save.setObjectName("btnPowerSave")
        self.btn_power_save.setToolTip("Set selected applications to Power Saving (Integrated Intel GPU)")
        self.btn_power_save.clicked.connect(lambda: self._apply_bulk_preference(PREF_POWER_SAVING))

        self.btn_let_decide = QPushButton("⚙️ Let Windows Decide")
        self.btn_let_decide.setObjectName("btnWindowsDecide")
        self.btn_let_decide.setToolTip("Remove override and let Windows / driver decide default GPU")
        self.btn_let_decide.clicked.connect(lambda: self._apply_bulk_preference(PREF_LET_WINDOWS_DECIDE))

        self.btn_add_app = QPushButton("➕ Add App...")
        self.btn_add_app.setObjectName("btnAddCustom")
        self.btn_add_app.setToolTip("Browse and add any unlisted executable")
        self.btn_add_app.clicked.connect(self._add_custom_app_dialog)

        tb_layout.addWidget(self.btn_high_perf)
        tb_layout.addWidget(self.btn_power_save)
        tb_layout.addWidget(self.btn_let_decide)
        tb_layout.addWidget(self.btn_add_app)
        tb_layout.addStretch()

        # Refresh button & auto-refresh
        self.auto_refresh_chk = QCheckBox("Auto Refresh (2.5s)")
        self.auto_refresh_chk.setChecked(True)
        self.auto_refresh_chk.stateChanged.connect(self._toggle_auto_refresh)
        tb_layout.addWidget(self.auto_refresh_chk)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self.trigger_refresh)
        tb_layout.addWidget(self.btn_refresh)

        root_layout.addWidget(toolbar)

        # 3. Main Data Table (Virtualized QTableView + ProxyModel)
        self.table_model = GpuInventoryModel()
        self.proxy_model = GpuFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.Interactive)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 260)

        root_layout.addWidget(self.table)

        # 4. Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready • Monitoring GPU Engine counters and registry")

    def _create_kpi_card(self, title: str, default_val: str, color: str = "#f1f5f9") -> QWidget:
        card = QFrame()
        card.setProperty("class", "kpi-card")
        l = QVBoxLayout(card)
        l.setContentsMargins(10, 4, 10, 4)
        l.setSpacing(2)
        
        t_lbl = QLabel(title)
        t_lbl.setProperty("class", "kpi-title")
        
        v_lbl = QLabel(default_val)
        v_lbl.setProperty("class", "kpi-value")
        v_lbl.setStyleSheet(f"color: {color};")
        
        l.addWidget(t_lbl)
        l.addWidget(v_lbl)
        card.val_label = v_lbl
        return card

    def _init_worker(self):
        self.worker = WorkerThread(self.scanner)
        self.worker.inventory_ready.connect(self._on_inventory_scanned)

    def trigger_refresh(self):
        if not self.worker.isRunning():
            self.worker.start()

    def _toggle_auto_refresh(self, state):
        if state == Qt.Checked:
            self.refresh_timer.start(2500)
        else:
            self.refresh_timer.stop()

    def _set_filter(self, filter_name: str):
        self.btn_filter_all.setChecked(filter_name == "ALL")
        self.btn_filter_running.setChecked(filter_name == "RUNNING")
        self.btn_filter_active.setChecked(filter_name == "ACTIVE_GPU")
        self.btn_filter_configured.setChecked(filter_name == "CONFIGURED")
        self.btn_filter_restart.setChecked(filter_name == "RESTART")
        self.proxy_model.set_category_filter(filter_name)

    def _on_search_debounced(self):
        self.proxy_model.set_search_query(self.search_input.text())

    def _on_inventory_scanned(self, items: List[AppInventoryItem]):
        self.cached_items = items
        self._update_kpi_cards(items)
        self.table_model.update_data(items)
        now_str = datetime.now().strftime("%H:%M:%S")
        self.status_bar.showMessage(f"Last updated: {now_str} • {len(items)} applications tracked")

    def _update_kpi_cards(self, items: List[AppInventoryItem]):
        total = len(items)
        running = sum(1 for i in items if i.is_running)
        on_nvidia = sum(1 for i in items if i.nvidia_in_smi or i.nvidia_util > 0.05)
        on_intel = sum(1 for i in items if i.intel_util > 0.05)
        configured = sum(1 for i in items if i.has_saved_entry and i.saved_pref is not None)
        restart = sum(1 for i in items if i.pending_restart)

        self.kpi_total.val_label.setText(str(total))
        self.kpi_running.val_label.setText(str(running))
        self.kpi_nvidia.val_label.setText(str(on_nvidia))
        self.kpi_intel.val_label.setText(str(on_intel))
        self.kpi_saved.val_label.setText(str(configured))
        self.kpi_restart.val_label.setText(str(restart))

    def _get_selected_items(self) -> List[AppInventoryItem]:
        selected_indexes = self.table.selectionModel().selectedRows()
        results = []
        for proxy_idx in selected_indexes:
            src_idx = self.proxy_model.mapToSource(proxy_idx)
            if src_idx.isValid() and src_idx.row() < len(self.table_model.items):
                results.append(self.table_model.items[src_idx.row()])
        return results

    def _apply_bulk_preference(self, pref_value: int):
        selected = self._get_selected_items()
        if not selected:
            QMessageBox.information(self, "No Apps Selected", "Please select one or more applications from the table first.")
            return

        pref_names = {
            PREF_HIGH_PERFORMANCE: "High Performance (NVIDIA)",
            PREF_POWER_SAVING: "Power Saving (Intel)",
            PREF_LET_WINDOWS_DECIDE: "Let Windows Decide (Clear Override)"
        }
        target_label = pref_names.get(pref_value, "Default")

        success_count = 0
        running_modified_count = 0

        for item in selected:
            ok = self.reg_mgr.set_gpu_preference(item.exe_path, pref_value)
            if ok:
                success_count += 1
                item.saved_pref = pref_value if pref_value != PREF_LET_WINDOWS_DECIDE else None
                item.has_saved_entry = (pref_value != PREF_LET_WINDOWS_DECIDE)
                if item.is_running:
                    running_modified_count += 1
                    self.scanner.mark_modified_running(item.norm_path)
                    item.check_restart_needed(was_running_when_modified=True)

        self.table_model.update_data(self.cached_items)
        self.status_bar.showMessage(f"Updated {success_count} app(s) to '{target_label}'. ({running_modified_count} running apps need restart)")

    def _add_custom_app_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Application Executable",
            "C:\\Program Files",
            "Executable Files (*.exe);;All Files (*.*)"
        )
        if file_path:
            reply = QMessageBox.question(
                self,
                "Set GPU Preference",
                f"Add '{os.path.basename(file_path)}'?\n\nChoose preference:\n- Yes: High Performance (NVIDIA)\n- No: Power Saving (Intel)\n- Cancel: Abort",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self.reg_mgr.set_gpu_preference(file_path, PREF_HIGH_PERFORMANCE)
            elif reply == QMessageBox.No:
                self.reg_mgr.set_gpu_preference(file_path, PREF_POWER_SAVING)
            else:
                return

            self.trigger_refresh()

    def _show_context_menu(self, pos):
        selected = self._get_selected_items()
        if not selected:
            return

        menu = QMenu(self)
        
        act_nvidia = menu.addAction("⚡ Set High Performance (NVIDIA)")
        act_nvidia.triggered.connect(lambda: self._apply_bulk_preference(PREF_HIGH_PERFORMANCE))

        act_intel = menu.addAction("🍃 Set Power Saving (Intel)")
        act_intel.triggered.connect(lambda: self._apply_bulk_preference(PREF_POWER_SAVING))

        act_clear = menu.addAction("⚙️ Let Windows Decide (Clear Override)")
        act_clear.triggered.connect(lambda: self._apply_bulk_preference(PREF_LET_WINDOWS_DECIDE))

        menu.addSeparator()

        single_item = selected[0] if len(selected) == 1 else None
        if single_item:
            act_open_folder = menu.addAction("📂 Open File Location")
            act_open_folder.triggered.connect(lambda: self._open_file_location(single_item.exe_path))

            act_copy_path = menu.addAction("📋 Copy Executable Path")
            act_copy_path.triggered.connect(lambda: QApplication.clipboard().setText(single_item.exe_path))

            if single_item.is_running:
                menu.addSeparator()
                act_restart = menu.addAction("🔄 Restart Application")
                act_restart.triggered.connect(lambda: self._restart_application(single_item))

                act_terminate = menu.addAction("🛑 Terminate Process")
                act_terminate.triggered.connect(lambda: self._terminate_application(single_item))

        menu.exec(QCursor.pos())

    def _open_file_location(self, exe_path: str):
        if os.path.exists(exe_path):
            subprocess.run(["explorer.exe", f"/select,{exe_path}"])

    def _restart_application(self, item: AppInventoryItem):
        if not item.pids or not os.path.exists(item.exe_path):
            return
        
        reply = QMessageBox.question(
            self,
            "Restart Application",
            f"Are you sure you want to terminate and relaunch '{item.display_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            import psutil
            for pid in item.pids:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                except Exception:
                    pass
            try:
                subprocess.Popen([item.exe_path], cwd=os.path.dirname(item.exe_path))
                self.scanner.modified_running_apps.discard(item.norm_path)
                item.pending_restart = False
            except Exception as e:
                QMessageBox.warning(self, "Relaunch Failed", f"Failed to relaunch application: {e}")
            
            QTimer.singleShot(1000, self.trigger_refresh)

    def _terminate_application(self, item: AppInventoryItem):
        if not item.pids:
            return
        import psutil
        for pid in item.pids:
            try:
                p = psutil.Process(pid)
                p.kill()
            except Exception:
                pass
        QTimer.singleShot(800, self.trigger_refresh)

    def closeEvent(self, event):
        self.refresh_timer.stop()
        if self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        self.perf_mon.close()
        event.accept()


def run_app():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setApplicationName("Windows 11 GPU Preference Manager")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()
