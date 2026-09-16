"""表格模型与筛选代理。

这里有个很容易埋进去的坑：``DisplayRole`` 返回的是给人看的 ``"¥1,234.56"``，
直接拿它排序会变成字符串比较 —— ``"9.5" > "10.2"``。所以另设一个
``SORT_ROLE`` 返回原始数值，用 :meth:`QSortFilterProxyModel.setSortRole` 指定。

筛选和排序都在内存里做，不回头查库。数据量是个人台账级别，而且持有天数和
日均价格这两个派生列根本不在数据库里，SQL 没法对它们排序。
"""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)

from ..exporter import HEADERS, MONEY_COLUMNS
from ..models import STATUS_ALL, Device, matches

# 排序专用的 role：返回原始值，而不是格式化后的字符串
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1

COL_NAME = 0
COL_CATEGORY = 1
COL_PURCHASE_DATE = 2
COL_PURCHASE_PRICE = 3
COL_SALE_DATE = 4
COL_SALE_PRICE = 5
COL_DAYS_HELD = 6
COL_DAILY_PURCHASE = 7
COL_DAILY_NET = 8
COL_STATUS = 9
COL_NOTE = 10

# 排到末尾的哨兵值：未售出设备的售出日期/售出价
_NO_VALUE = -1

_MONEY_COLUMNS = frozenset(MONEY_COLUMNS)
_RIGHT_ALIGNED = _MONEY_COLUMNS | {COL_DAYS_HELD}


def _money(value: float) -> str:
    return f"¥{value:,.2f}"


def _display(device: Device, column: int, today: date) -> str | None:
    """给人看的文本。"""
    if column == COL_NAME:
        return device.name
    if column == COL_CATEGORY:
        return device.category
    if column == COL_PURCHASE_DATE:
        return device.purchase_date.isoformat()
    if column == COL_PURCHASE_PRICE:
        return _money(device.purchase_price)
    if column == COL_SALE_DATE:
        return device.sale_date.isoformat() if device.sale_date else "—"
    if column == COL_SALE_PRICE:
        return _money(device.sale_price) if device.sale_price is not None else "—"
    if column == COL_DAYS_HELD:
        return f"{device.days_held(today)} 天"
    if column == COL_DAILY_PURCHASE:
        return _money(device.daily_purchase_cost(today))
    if column == COL_DAILY_NET:
        return _money(device.daily_net_cost(today))
    if column == COL_STATUS:
        return device.status_text
    if column == COL_NOTE:
        return device.note
    return None


def _sort_key(device: Device, column: int, today: date):
    """排序用的原始值。未售出的设备用哨兵值排到一端。"""
    if column == COL_NAME:
        return device.name.casefold()
    if column == COL_CATEGORY:
        return device.category.casefold()
    if column == COL_PURCHASE_DATE:
        return device.purchase_date.toordinal()
    if column == COL_PURCHASE_PRICE:
        return device.purchase_price
    if column == COL_SALE_DATE:
        return device.sale_date.toordinal() if device.sale_date else _NO_VALUE
    if column == COL_SALE_PRICE:
        return device.sale_price if device.sale_price is not None else float(_NO_VALUE)
    if column == COL_DAYS_HELD:
        return device.days_held(today)
    if column == COL_DAILY_PURCHASE:
        return device.daily_purchase_cost(today)
    if column == COL_DAILY_NET:
        return device.daily_net_cost(today)
    if column == COL_STATUS:
        return device.status_text
    if column == COL_NOTE:
        return device.note.casefold()
    return None


class DeviceTableModel(QAbstractTableModel):
    """把 :class:`Device` 列表暴露给 QTableView。"""

    def __init__(self, devices=None, today: date | None = None, parent=None):
        super().__init__(parent)
        self._devices: list[Device] = list(devices or [])
        self._today: date = today or date.today()

    @property
    def today(self) -> date:
        """当前渲染所用的「今天」。同一次渲染里表格和统计共用它。"""
        return self._today

    def set_devices(self, devices) -> None:
        """整体替换数据。行数变化时才用，会重置选中状态。"""
        self.beginResetModel()
        self._devices = list(devices)
        self.endResetModel()

    def set_today(self, today: date) -> None:
        """跨零点时刷新派生列。

        只发 dataChanged，不 reset —— reset 会清掉选中行和滚动位置，
        用户把窗口开一整夜回来发现选中没了会很烦。
        """
        if today == self._today:
            return
        self._today = today
        if not self._devices:
            return
        top = self.index(0, COL_DAYS_HELD)
        bottom = self.index(self.rowCount() - 1, COL_DAILY_NET)
        self.dataChanged.emit(
            top, bottom, [Qt.ItemDataRole.DisplayRole, SORT_ROLE]
        )

    def device_at(self, row: int) -> Device:
        return self._devices[row]

    def all_devices(self) -> list[Device]:
        """未经筛选的全部设备。导出「全部记录」用。"""
        return list(self._devices)

    # --- QAbstractTableModel 接口 ----------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._devices)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation is Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        device = self._devices[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return _display(device, column, self._today)
        if role == SORT_ROLE:
            return _sort_key(device, column, self._today)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            horizontal = (
                Qt.AlignmentFlag.AlignRight
                if column in _RIGHT_ALIGNED
                else Qt.AlignmentFlag.AlignLeft
            )
            return int(horizontal | Qt.AlignmentFlag.AlignVCenter)
        # 未处理的 role 一律 None，返回 "" 或 False 会被误当成有效值
        return None


class DeviceFilterProxy(QSortFilterProxyModel):
    """筛选 + 排序。筛选规则本身在 :func:`devicetracker.models.matches`。"""

    filterChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self._query = ""
        self._category: str | None = None
        self._status = STATUS_ALL

    # --- 筛选条件 ---------------------------------------------------------

    def set_query(self, text: str) -> None:
        self._query = text or ""
        self._invalidate()

    def set_category(self, category: str | None) -> None:
        self._category = category
        self._invalidate()

    def set_status(self, status: str) -> None:
        self._status = status
        self._invalidate()

    def _invalidate(self) -> None:
        self.invalidateFilter()
        self.filterChanged.emit()

    # --- QSortFilterProxyModel 接口 --------------------------------------

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        device = model.device_at(source_row)
        return matches(
            device,
            query=self._query,
            category=self._category,
            status=self._status,
        )

    def visible_devices(self) -> list[Device]:
        """当前筛选并排序后的设备，顺序与屏幕一致。导出「当前视图」用。"""
        model = self.sourceModel()
        if model is None:
            return []
        return [
            model.device_at(self.mapToSource(self.index(row, 0)).row())
            for row in range(self.rowCount())
        ]
