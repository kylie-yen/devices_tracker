"""SQLite 存取层。

只管 SQL，不做任何业务计算 —— 持有天数和日均价格都不在这里，它们读的时候
由 :mod:`devicetracker.models` 现算。

日期一律显式转成 ISO 字符串再入库。Python 3.12 起 sqlite3 的隐式 ``date``
适配器已弃用，直接把 date 对象当参数传会触发 DeprecationWarning。
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from .models import Device

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    category       TEXT    NOT NULL DEFAULT '',
    purchase_price REAL    NOT NULL CHECK (purchase_price >= 0),
    purchase_date  TEXT    NOT NULL,               -- 'YYYY-MM-DD'
    sale_price     REAL             CHECK (sale_price IS NULL OR sale_price >= 0),
    sale_date      TEXT,                           -- 'YYYY-MM-DD'，未售出为 NULL
    note           TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    -- 售出价与售出日期同生共死，杜绝「有价无期」这种半售出状态
    CHECK ((sale_price IS NULL) = (sale_date IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_devices_category ON devices(category);
"""


def _to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_iso(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _row_to_device(row: sqlite3.Row) -> Device:
    return Device(
        id=row["id"],
        name=row["name"],
        category=row["category"],
        purchase_price=row["purchase_price"],
        purchase_date=date.fromisoformat(row["purchase_date"]),
        sale_price=row["sale_price"],
        sale_date=_from_iso(row["sale_date"]),
        note=row["note"],
    )


class Database:
    """设备表的读写入口。

    路径由调用方注入（生产传 :func:`devicetracker.paths.default_db_path`，
    测试传临时目录），这样测试永远不会碰到真实数据。

    连接只在 GUI 线程使用 —— sqlite3 的连接默认不能跨线程。
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # --- 查询 -------------------------------------------------------------

    def list_devices(self) -> list[Device]:
        """全部设备，按购入日期倒序（最近买的在最上面）。"""
        rows = self._conn.execute(
            "SELECT * FROM devices ORDER BY purchase_date DESC, id DESC"
        ).fetchall()
        return [_row_to_device(row) for row in rows]

    def get_device(self, device_id: int) -> Device | None:
        row = self._conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return _row_to_device(row) if row is not None else None

    def distinct_categories(self) -> list[str]:
        """已用过的分类，供筛选下拉使用。空分类不返回。"""
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM devices "
            "WHERE category <> '' ORDER BY category"
        ).fetchall()
        return [row["category"] for row in rows]

    # --- 写入 -------------------------------------------------------------

    def add_device(self, device: Device) -> Device:
        """插入并返回带 id 的副本。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO devices
                    (name, category, purchase_price, purchase_date,
                     sale_price, sale_date, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device.name,
                    device.category,
                    device.purchase_price,
                    _to_iso(device.purchase_date),
                    device.sale_price,
                    _to_iso(device.sale_date),
                    device.note,
                    now,
                    now,
                ),
            )
        return replace(device, id=cursor.lastrowid)

    def update_device(self, device: Device) -> None:
        if device.id is None:
            raise ValueError("更新设备需要 id")
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute(
                """
                UPDATE devices
                   SET name = ?, category = ?, purchase_price = ?, purchase_date = ?,
                       sale_price = ?, sale_date = ?, note = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    device.name,
                    device.category,
                    device.purchase_price,
                    _to_iso(device.purchase_date),
                    device.sale_price,
                    _to_iso(device.sale_date),
                    device.note,
                    now,
                    device.id,
                ),
            )

    def delete_device(self, device_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
