"""添加 / 编辑设备的对话框。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..models import Device

# 常用分类，给下拉框做预置；用户也可以直接输入新的
PRESET_CATEGORIES: tuple[str, ...] = (
    "手机",
    "电脑",
    "平板",
    "耳机",
    "显示器",
    "配件",
    "其他",
)

# QDoubleSpinBox 的默认上限只有 99.99。不显式设范围的话，用户输入 5999 会被
# 静默截断成 99.99，然后以为程序算错了 —— 极难排查的一类 bug。
MAX_PRICE = 99_999_999.99

# QDateEdit 默认范围从 1752 年开始，显式收紧到合理区间
MIN_DATE = QDate(2000, 1, 1)
DATE_FORMAT = "yyyy-MM-dd"


class DeviceDialog(QDialog):
    """返回一个 :class:`Device`，或者被取消。

    传入的 ``device`` 会被复制一份，避免用户点「取消」时控件里的值已经写回了
    调用方持有的那个对象，造成内存与数据库不一致。
    """

    def __init__(
        self,
        parent=None,
        device: Device | None = None,
        categories: Iterable[str] = (),
    ):
        super().__init__(parent)
        self._original = replace(device) if device is not None else None
        self._known_categories = tuple(categories)

        self.setWindowTitle("编辑设备" if device else "添加设备")
        self.setMinimumWidth(440)

        self._build_ui()
        if self._original is not None:
            self._load(self._original)
        self._on_sold_toggled(self._sold_check.isChecked())
        self._validate()

    # --- 构建界面 ---------------------------------------------------------

    def _build_ui(self) -> None:
        self._name = QLineEdit()
        self._name.setPlaceholderText("例如：iPhone 15 Pro")

        self._category = QComboBox()
        self._category.setEditable(True)
        self._category.addItems(self._category_choices())
        self._category.setCurrentText(PRESET_CATEGORIES[0])

        self._purchase_price = self._make_price_edit()
        self._purchase_date = self._make_date_edit()

        self._sold_check = QCheckBox("已售出")

        self._sale_price = self._make_price_edit()
        self._sale_date = self._make_date_edit()

        self._note = QPlainTextEdit()
        self._note.setPlaceholderText("可选：购买渠道、成色、买家等")
        self._note.setFixedHeight(72)

        form = QFormLayout()
        form.addRow("名称", self._name)
        form.addRow("分类", self._category)
        form.addRow("购入价格", self._purchase_price)
        form.addRow("购入日期", self._purchase_date)
        form.addRow("", self._sold_check)
        form.addRow("售出价格", self._sale_price)
        form.addRow("售出日期", self._sale_date)
        form.addRow("备注", self._note)

        # 校验不通过时禁用 OK 并在这里说明原因，而不是弹窗打断
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #c0392b;")

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(self._buttons)

        self._name.textChanged.connect(self._validate)
        self._purchase_date.dateChanged.connect(self._validate)
        self._sale_date.dateChanged.connect(self._validate)
        self._sold_check.toggled.connect(self._on_sold_toggled)

    def _category_choices(self) -> list[str]:
        """预置分类 + 库里已用过的分类，去重且保持顺序。"""
        choices = list(PRESET_CATEGORIES)
        for category in self._known_categories:
            if category and category not in choices:
                choices.append(category)
        return choices

    def _make_price_edit(self) -> QDoubleSpinBox:
        edit = QDoubleSpinBox()
        edit.setDecimals(2)
        edit.setRange(0.0, MAX_PRICE)
        edit.setSingleStep(100.0)
        edit.setPrefix("¥ ")
        edit.setGroupSeparatorShown(True)
        return edit

    def _make_date_edit(self) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat(DATE_FORMAT)
        edit.setDateRange(MIN_DATE, QDate.currentDate().addYears(1))
        edit.setDate(QDate.currentDate())
        return edit

    # --- 载入与取值 -------------------------------------------------------

    def _load(self, device: Device) -> None:
        self._name.setText(device.name)
        self._set_category(device.category)
        self._purchase_price.setValue(device.purchase_price)
        self._purchase_date.setDate(
            QDate(
                device.purchase_date.year,
                device.purchase_date.month,
                device.purchase_date.day,
            )
        )

        if device.is_sold:
            self._sold_check.setChecked(True)
            # 售价可能是 0（送人），所以判空不能用 truthiness
            self._sale_price.setValue(device.sale_price or 0.0)
            self._sale_date.setDate(
                QDate(
                    device.sale_date.year,
                    device.sale_date.month,
                    device.sale_date.day,
                )
            )
        else:
            self._sold_check.setChecked(False)

        self._note.setPlainText(device.note)

    def _set_category(self, category: str) -> None:
        index = self._category.findText(category)
        if index >= 0:
            self._category.setCurrentIndex(index)
        else:
            self._category.setEditText(category)

    def result_device(self) -> Device:
        """把控件里的值收成一个 Device。

        未售出时售出价和售出日期**一起**置 None —— 数据库有 CHECK 约束要求
        两者同生共死，这里不遵守会直接写库失败。
        """
        sold = self._sold_check.isChecked()
        return Device(
            id=self._original.id if self._original is not None else None,
            name=self._name.text().strip(),
            category=self._category.currentText().strip(),
            purchase_price=self._purchase_price.value(),
            purchase_date=self._purchase_date.date().toPyDate(),
            sale_price=self._sale_price.value() if sold else None,
            sale_date=self._sale_date.date().toPyDate() if sold else None,
            note=self._note.toPlainText().strip(),
        )

    # --- 校验 -------------------------------------------------------------

    def _on_sold_toggled(self, checked: bool) -> None:
        self._sale_price.setEnabled(checked)
        self._sale_date.setEnabled(checked)
        self._validate()

    def _validation_message(self) -> str | None:
        if not self._name.text().strip():
            return "请填写设备名称"
        if self._sold_check.isChecked():
            if self._sale_date.date() < self._purchase_date.date():
                return "售出日期不能早于购入日期"
        return None

    def _validate(self) -> None:
        message = self._validation_message()
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setEnabled(message is None)
        self._hint.setText(message or "")
