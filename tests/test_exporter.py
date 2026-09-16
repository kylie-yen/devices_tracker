"""导出测试。

重点验证两件在真实使用中会立刻暴露的问题：中文编码，以及金额被写成字符串。
"""

from __future__ import annotations

import csv
from datetime import date

import pytest
from openpyxl import load_workbook

from devicetracker.exporter import HEADERS, export_csv, export_excel, row_for
from devicetracker.models import Device


@pytest.fixture
def devices(held_device, sold_device) -> list[Device]:
    return [held_device, sold_device]


# --- 行内容 ---------------------------------------------------------------


def test_row_for_keeps_money_as_numbers(held_device, today):
    row = row_for(held_device, today)
    assert isinstance(row[3], float)  # 购入价格
    assert isinstance(row[7], float)  # 购入成本日均
    assert isinstance(row[8], float)  # 净成本日均
    assert isinstance(row[6], int)  # 持有天数


def test_row_for_leaves_sale_columns_blank_when_unsold(held_device, today):
    row = row_for(held_device, today)
    assert row[4] == ""  # 售出日期
    assert row[5] == ""  # 售出价格
    assert row[9] == "持有中"


def test_row_for_fills_sale_columns_when_sold(sold_device, today):
    row = row_for(sold_device, today)
    assert row[4] == "2026-04-11"
    assert row[5] == 6500.0
    assert row[6] == 100
    assert row[9] == "已售出"


def test_row_for_keeps_zero_sale_price_as_number(today):
    """售价 0 要写成 0，不能和「未售出」的空串混为一谈。"""
    device = Device(
        name="送人",
        purchase_price=2000.0,
        purchase_date=date(2026, 1, 1),
        sale_price=0.0,
        sale_date=date(2026, 3, 1),
    )
    row = row_for(device, today)
    assert row[5] == 0.0
    assert row[9] == "已售出"


# --- CSV ------------------------------------------------------------------


def test_csv_has_utf8_bom(tmp_path, devices, today):
    """没有 BOM 的话 Excel 双击打开中文是乱码。"""
    path = export_csv(devices, tmp_path / "out.csv", today)
    assert path.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_csv_header_and_row_count(tmp_path, devices, today):
    path = export_csv(devices, tmp_path / "out.csv", today)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    assert tuple(rows[0]) == HEADERS
    assert len(rows) == len(devices) + 1


def test_csv_writes_no_blank_rows_on_windows(tmp_path, devices, today):
    """缺 newline="" 时 Windows 上每行之间会插入空行。"""
    path = export_csv(devices, tmp_path / "out.csv", today)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.reader(handle) if row]

    assert len(rows) == len(devices) + 1


def test_csv_handles_empty_device_list(tmp_path, today):
    path = export_csv([], tmp_path / "out.csv", today)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    assert tuple(rows[0]) == HEADERS
    assert len(rows) == 1


def test_csv_roundtrips_chinese_and_commas_in_note(tmp_path, today):
    device = Device(
        name="耳机, 带麦",
        category="耳机",
        purchase_price=899.0,
        purchase_date=date(2026, 5, 1),
        note='备注里有"引号"和,逗号',
    )
    path = export_csv([device], tmp_path / "out.csv", today)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    assert rows[1][0] == "耳机, 带麦"
    assert rows[1][10] == '备注里有"引号"和,逗号'


# --- Excel ----------------------------------------------------------------


def test_excel_is_readable_and_has_headers(tmp_path, devices, today):
    path = export_excel(devices, tmp_path / "out.xlsx", today)
    sheet = load_workbook(path).active

    assert [cell.value for cell in sheet[1]] == list(HEADERS)
    assert sheet.max_row == len(devices) + 1


def test_excel_money_cells_are_numeric_not_text(tmp_path, devices, today):
    """写成 "¥5,999.00" 字符串的话，用户在 Excel 里没法求和。"""
    path = export_excel(devices, tmp_path / "out.xlsx", today)
    sheet = load_workbook(path).active

    purchase_cell = sheet.cell(row=2, column=4)
    assert isinstance(purchase_cell.value, (int, float))
    assert purchase_cell.number_format == "#,##0.00"


def test_excel_sold_device_has_numeric_sale_price(tmp_path, sold_device, today):
    path = export_excel([sold_device], tmp_path / "out.xlsx", today)
    sheet = load_workbook(path).active

    assert sheet.cell(row=2, column=6).value == 6500.0
    assert isinstance(sheet.cell(row=2, column=6).value, (int, float))


def test_excel_freezes_header_row(tmp_path, devices, today):
    path = export_excel(devices, tmp_path / "out.xlsx", today)
    assert load_workbook(path).active.freeze_panes == "A2"


def test_excel_handles_empty_device_list(tmp_path, today):
    path = export_excel([], tmp_path / "out.xlsx", today)
    sheet = load_workbook(path).active

    assert [cell.value for cell in sheet[1]] == list(HEADERS)
    assert sheet.max_row == 1
