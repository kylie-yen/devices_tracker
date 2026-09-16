"""数据访问层测试。

全部使用临时数据库，绝不碰真实的 devices.db。
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from devicetracker.database import SCHEMA_VERSION, Database
from devicetracker.models import Device


def make_device(**overrides) -> Device:
    defaults = {
        "name": "测试设备",
        "category": "其他",
        "purchase_price": 1000.0,
        "purchase_date": date(2026, 1, 1),
    }
    defaults.update(overrides)
    return Device(**defaults)


@pytest.fixture
def db(db_path):
    with Database(db_path) as database:
        yield database


# --- 建表 -----------------------------------------------------------------


def test_schema_creation_is_idempotent(db_path):
    """重复打开同一个库不应报错，也不应丢数据。"""
    with Database(db_path) as first:
        first.add_device(make_device(name="保留我"))
    with Database(db_path) as second:
        assert [d.name for d in second.list_devices()] == ["保留我"]


def test_schema_version_is_recorded(db):
    version = db._conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


# --- 往返 -----------------------------------------------------------------


def test_add_then_list_roundtrip(db):
    original = make_device(
        name="iPhone 15 Pro",
        category="手机",
        purchase_price=8999.0,
        purchase_date=date(2026, 9, 6),
        note="官网购入",
    )
    saved = db.add_device(original)

    assert saved.id is not None

    (loaded,) = db.list_devices()
    assert loaded.name == "iPhone 15 Pro"
    assert loaded.category == "手机"
    assert loaded.purchase_price == 8999.0
    assert loaded.purchase_date == date(2026, 9, 6)
    assert loaded.note == "官网购入"
    assert loaded.sale_price is None
    assert loaded.sale_date is None


def test_sold_device_roundtrip_preserves_both_sale_fields(db):
    device = make_device(
        purchase_price=9499.0,
        purchase_date=date(2026, 1, 1),
        sale_price=6500.0,
        sale_date=date(2026, 4, 11),
    )
    db.add_device(device)

    (loaded,) = db.list_devices()
    assert loaded.sale_price == 6500.0
    assert loaded.sale_date == date(2026, 4, 11)
    assert loaded.is_sold is True


def test_zero_sale_price_is_not_confused_with_unsold(db):
    """0.0 和 None 必须能区分开：送人（售价 0）不是「持有中」。"""
    db.add_device(make_device(name="送人的旧手机", sale_price=0.0,
                              sale_date=date(2026, 3, 1)))

    (loaded,) = db.list_devices()
    assert loaded.sale_price == 0.0
    assert loaded.sale_price is not None
    assert loaded.sale_date == date(2026, 3, 1)
    assert loaded.is_sold is True


def test_dates_are_persisted_as_iso_strings(db, db_path):
    """防回归：Python 3.12 已弃用 sqlite3 的隐式 date 适配器。"""
    db.add_device(make_device(purchase_date=date(2026, 9, 6)))
    db._conn.commit()

    with sqlite3.connect(db_path) as raw:
        purchase_date, = raw.execute(
            "SELECT purchase_date FROM devices"
        ).fetchone()

    assert isinstance(purchase_date, str)
    assert purchase_date == "2026-09-06"


def test_no_deprecation_warning_on_write(db, recwarn):
    """直接传 date 对象会触发 DeprecationWarning；显式转换后应当干净。"""
    db.add_device(make_device(purchase_date=date(2026, 9, 6)))
    assert not [w for w in recwarn if "adapter" in str(w.message).lower()]


# --- 更新与删除 -----------------------------------------------------------


def test_update_changes_only_target_row(db):
    first = db.add_device(make_device(name="A"))
    second = db.add_device(make_device(name="B"))

    db.update_device(
        Device(
            id=first.id,
            name="A 改过了",
            category="手机",
            purchase_price=500.0,
            purchase_date=date(2026, 2, 2),
        )
    )

    by_id = {d.id: d for d in db.list_devices()}
    assert by_id[first.id].name == "A 改过了"
    assert by_id[first.id].purchase_price == 500.0
    assert by_id[first.id].purchase_date == date(2026, 2, 2)
    # 另一行完全不受影响
    assert by_id[second.id].name == "B"
    assert by_id[second.id].purchase_price == 1000.0


def test_update_can_mark_device_as_sold(db):
    saved = db.add_device(make_device(name="待售出"))
    assert db.get_device(saved.id).is_sold is False

    db.update_device(
        Device(
            id=saved.id,
            name="待售出",
            purchase_price=1000.0,
            purchase_date=date(2026, 1, 1),
            sale_price=700.0,
            sale_date=date(2026, 6, 1),
        )
    )

    loaded = db.get_device(saved.id)
    assert loaded.is_sold is True
    assert loaded.sale_price == 700.0


def test_update_can_revert_sold_back_to_held(db):
    """误标售出后要能改回持有中 —— 两个字段必须一起清空。"""
    saved = db.add_device(
        make_device(sale_price=700.0, sale_date=date(2026, 6, 1))
    )

    db.update_device(
        Device(
            id=saved.id,
            name="测试设备",
            purchase_price=1000.0,
            purchase_date=date(2026, 1, 1),
        )
    )

    loaded = db.get_device(saved.id)
    assert loaded.sale_price is None
    assert loaded.sale_date is None
    assert loaded.is_sold is False


def test_update_without_id_raises(db):
    with pytest.raises(ValueError):
        db.update_device(make_device())


def test_delete_removes_only_target_row(db):
    first = db.add_device(make_device(name="A"))
    second = db.add_device(make_device(name="B"))
    third = db.add_device(make_device(name="C"))

    db.delete_device(second.id)

    remaining = {d.id for d in db.list_devices()}
    assert remaining == {first.id, third.id}


def test_get_device_returns_none_for_missing_id(db):
    assert db.get_device(9999) is None


# --- 分类 -----------------------------------------------------------------


def test_distinct_categories_dedupes_sorts_and_skips_empty(db):
    for category in ["手机", "电脑", "手机", "", "平板", "电脑"]:
        db.add_device(make_device(category=category))

    assert db.distinct_categories() == ["平板", "手机", "电脑"]


def test_distinct_categories_on_empty_table(db):
    assert db.distinct_categories() == []


# --- 排序与约束 -----------------------------------------------------------


def test_list_devices_orders_by_purchase_date_descending(db):
    db.add_device(make_device(name="最早", purchase_date=date(2025, 1, 1)))
    db.add_device(make_device(name="最晚", purchase_date=date(2026, 8, 1)))
    db.add_device(make_device(name="中间", purchase_date=date(2026, 3, 1)))

    assert [d.name for d in db.list_devices()] == ["最晚", "中间", "最早"]


def test_schema_rejects_half_sold_state(db):
    """售价和售出日期必须同生共死，这是 schema 层的保证。"""
    with pytest.raises(sqlite3.IntegrityError):
        db._conn.execute(
            """
            INSERT INTO devices
                (name, category, purchase_price, purchase_date,
                 sale_price, sale_date, note, created_at, updated_at)
            VALUES ('半售出', '', 100.0, '2026-01-01', 50.0, NULL, '', 'x', 'x')
            """
        )


def test_schema_rejects_negative_purchase_price(db):
    with pytest.raises(sqlite3.IntegrityError):
        db._conn.execute(
            """
            INSERT INTO devices
                (name, category, purchase_price, purchase_date,
                 sale_price, sale_date, note, created_at, updated_at)
            VALUES ('负数', '', -1.0, '2026-01-01', NULL, NULL, '', 'x', 'x')
            """
        )
