"""主窗口：统计面板 + 工具栏 + 筛选行 + 设备表格。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..database import Database
from ..exporter import export_csv, export_excel
from ..models import STATUS_LABELS, Device, summarize
from .device_dialog import DeviceDialog
from .table_model import (
    COL_PURCHASE_DATE,
    DeviceFilterProxy,
    DeviceTableModel,
)

_GOOD = "#1e8449"
_BAD = "#c0392b"
_MUTED = "#666"

# 跨零点刷新用的轮询间隔。不用「定时到零点触发」是因为笔记本会休眠，
# 睡眠跨过零点时那种单次定时器可能永远不触发。轮询能自愈，开销可忽略。
_DAY_POLL_MS = 60_000


def _money(value: float) -> str:
    return f"¥{value:,.2f}"


class _StatTile(QFrame):
    """统计面板里的一个指标：上面小标题，下面数值。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._title = QLabel(title)
        self._title.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")

        self._value = QLabel("—")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        layout.addWidget(self._title)
        layout.addWidget(self._value)

        self.set_value("¥0.00")

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_value(self, text: str, tone: str | None = None) -> None:
        color = {"good": _GOOD, "bad": _BAD}.get(tone, "#111")
        self._value.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {color};"
        )
        self._value.setText(text)


class MainWindow(QMainWindow):
    def __init__(self, database: Database):
        super().__init__()
        self._db = database
        self._today = date.today()

        self.setWindowTitle("设备持有成本跟踪")
        self.resize(1200, 700)

        self._build_summary()
        self._build_filters()
        self._build_table()
        self._build_actions()

        self._wire_signals()
        self._reload()
        self._start_day_watch()

    # --- 构建界面 ---------------------------------------------------------

    def _build_summary(self) -> None:
        self._caption = QLabel()
        self._caption.setStyleSheet(f"color: {_MUTED};")

        self._tiles = {
            name: _StatTile(name)
            for name in ("总投入", "已回血", "净支出", "购入日均合计", "净日均合计")
        }

        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(8)
        for tile in self._tiles.values():
            tiles_row.addWidget(tile)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 4)
        panel_layout.setSpacing(6)
        panel_layout.addWidget(self._caption)
        panel_layout.addLayout(tiles_row)

        self._summary_panel = panel

    def _build_filters(self) -> None:
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索名称 / 分类 / 备注")
        self._search.setClearButtonEnabled(True)

        self._category_filter = QComboBox()
        self._category_filter.addItem("全部分类", None)

        self._status_filter = QComboBox()
        for status, label in STATUS_LABELS.items():
            self._status_filter.addItem(label, status)

        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)
        row.addWidget(self._search, 1)
        row.addWidget(self._category_filter)
        row.addWidget(self._status_filter)

        self._filter_bar = QWidget()
        self._filter_bar.setLayout(row)

    def _build_table(self) -> None:
        # 模型 / proxy / 数据库都存成实例属性。写成局部变量的话，Python 回收
        # 对象后底层 C++ 对象被销毁，表格会空白甚至崩溃。
        self._model = DeviceTableModel([], self._today)
        self._proxy = DeviceFilterProxy()
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)  # 先设 model
        self._table.setSortingEnabled(True)  # 再开排序
        self._table.sortByColumn(COL_PURCHASE_DATE, Qt.SortOrder.DescendingOrder)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        # 编辑统一走对话框，表格内不直接改
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._summary_panel)
        layout.addWidget(self._filter_bar)
        layout.addWidget(self._table, 1)
        self.setCentralWidget(central)

    def _build_actions(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._add_action = self._make_action(
            "添加设备", QKeySequence.StandardKey.New, self._add_device
        )
        self._edit_action = self._make_action(
            "编辑", QKeySequence("Ctrl+E"), self._edit_selected
        )
        self._delete_action = self._make_action(
            "删除", QKeySequence.StandardKey.Delete, self._delete_selected
        )
        self._export_view_action = self._make_action(
            "导出当前视图", QKeySequence.StandardKey.Save,
            lambda: self._export(visible_only=True),
        )

        for action in (
            self._add_action,
            self._edit_action,
            self._delete_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self._export_view_action)

        # 表格右键菜单
        self._table.addAction(self._edit_action)
        self._table.addAction(self._delete_action)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.ActionsContextMenu
        )

    def _make_action(self, text, shortcut, slot) -> QAction:
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _wire_signals(self) -> None:
        self._search.textChanged.connect(self._proxy.set_query)
        self._category_filter.currentIndexChanged.connect(
            self._on_category_filter_changed
        )
        self._status_filter.currentIndexChanged.connect(
            self._on_status_filter_changed
        )
        self._table.doubleClicked.connect(lambda _index: self._edit_selected())

        # 统计跟随筛选。modelReset 由增删改触发，dataChanged 由跨零点刷新触发。
        self._proxy.filterChanged.connect(self._refresh_summary)
        self._model.modelReset.connect(self._refresh_summary)
        self._model.dataChanged.connect(self._refresh_summary)

    # --- 筛选 -------------------------------------------------------------

    def _on_category_filter_changed(self, _index: int) -> None:
        self._proxy.set_category(self._category_filter.currentData())

    def _on_status_filter_changed(self, _index: int) -> None:
        self._proxy.set_status(self._status_filter.currentData())

    def _reload_categories(self) -> None:
        """重填分类下拉。

        必须屏蔽信号：clear() 会发出 currentIndexChanged(-1)，addItems() 又会
        带来一次 index=0，不加保护的话这些中间态会污染筛选条件。
        """
        previous = self._category_filter.currentData()
        self._category_filter.blockSignals(True)
        self._category_filter.clear()
        self._category_filter.addItem("全部分类", None)
        for category in self._db.distinct_categories():
            self._category_filter.addItem(category, category)
        index = self._category_filter.findData(previous)
        self._category_filter.setCurrentIndex(max(index, 0))
        self._category_filter.blockSignals(False)

    # --- 数据 -------------------------------------------------------------

    def _reload(self) -> None:
        self._model.set_devices(self._db.list_devices())
        self._reload_categories()

    def _refresh_summary(self) -> None:
        # 用 proxy 的可见行而不是原始列表 —— 统计口径要跟着筛选走，
        # 否则用户筛出「手机」后看到全量数字会以为算错了。
        visible = self._proxy.visible_devices()
        total = self._model.rowCount()
        summary = summarize(visible, self._today)

        self._caption.setText(
            f"统计（当前筛选 {summary.count} 台 / 共 {total} 台"
            f" · 持有中 {summary.held_count} · 已售出 {summary.sold_count}）"
        )

        self._tiles["总投入"].set_value(_money(summary.total_invested))
        self._tiles["已回血"].set_value(_money(summary.total_recovered))

        net = summary.net_spend
        net_tile = self._tiles["净支出"]
        if net < 0:
            net_tile.set_title("净收益")
            net_tile.set_value(_money(abs(net)), tone="good")
        else:
            net_tile.set_title("净支出")
            net_tile.set_value(_money(net))

        self._tiles["购入日均合计"].set_value(
            _money(summary.total_daily_purchase)
        )

        daily_net_tile = self._tiles["净日均合计"]
        if summary.total_daily_net < 0:
            daily_net_tile.set_value(
                _money(summary.total_daily_net), tone="good"
            )
        else:
            daily_net_tile.set_value(_money(summary.total_daily_net))

    def _selected_device(self) -> Device | None:
        index = self._table.currentIndex()
        if not index.isValid():
            return None
        return self._model.device_at(self._proxy.mapToSource(index).row())

    # --- 增删改 -----------------------------------------------------------

    def _add_device(self) -> None:
        dialog = DeviceDialog(
            self, categories=self._db.distinct_categories()
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._db.add_device(dialog.result_device())
        self._reload()

    def _edit_selected(self) -> None:
        device = self._selected_device()
        if device is None:
            QMessageBox.information(
                self, "未选中设备", "请先在表格里选中一台设备。"
            )
            return

        dialog = DeviceDialog(
            self, device=device, categories=self._db.distinct_categories()
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._db.update_device(dialog.result_device())
        self._reload()

    def _delete_selected(self) -> None:
        device = self._selected_device()
        if device is None:
            QMessageBox.information(
                self, "未选中设备", "请先在表格里选中一台设备。"
            )
            return

        answer = QMessageBox.question(
            self,
            "删除确认",
            f"确定删除「{device.name}」吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._db.delete_device(device.id)
        self._reload()

    # --- 导出 -------------------------------------------------------------

    def _export(self, *, visible_only: bool) -> None:
        """导出表格。

        默认导出当前视图（筛选 + 排序后，与屏幕一致）。导出文件里的派生列用
        和界面同一个 today，保证表里表外数字对得上。
        """
        devices = (
            self._proxy.visible_devices()
            if visible_only
            else self._model.all_devices()
        )
        if not devices:
            QMessageBox.information(
                self, "没有可导出的数据", "当前没有设备记录。"
            )
            return

        scope = "当前视图" if visible_only else "全部记录"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            f"导出{scope}",
            str(Path.home() / "设备台账.xlsx"),
            "Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv)",
        )
        if not path:
            return

        target = Path(path)
        if target.suffix.lower() not in (".xlsx", ".csv"):
            target = target.with_suffix(".xlsx")

        try:
            if target.suffix.lower() == ".csv":
                export_csv(devices, target, self._today)
            else:
                export_excel(devices, target, self._today)
        except OSError as error:
            QMessageBox.critical(self, "导出失败", str(error))
            return

        self.statusBar().showMessage(
            f"已导出 {len(devices)} 台设备到 {target}", 8000
        )

    # --- 跨零点刷新 -------------------------------------------------------

    def _start_day_watch(self) -> None:
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(_DAY_POLL_MS)
        self._day_timer.timeout.connect(self._check_day_rollover)
        self._day_timer.start()

    def _check_day_rollover(self) -> None:
        """日期变了就重算派生列。只更新表格内容，不重置选中状态。"""
        today = date.today()
        if today == self._today:
            return
        self._today = today
        self._model.set_today(today)
        self._refresh_summary()

    def changeEvent(self, event) -> None:
        # 休眠唤醒后切回窗口时也补一次检查
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowActivate:
            self._check_day_rollover()
