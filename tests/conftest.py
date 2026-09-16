from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from devicetracker.models import Device

# 固定「今天」。派生计算全部注入 today，测试才不会被真实日期影响。
TODAY = date(2026, 9, 16)


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def held_device() -> Device:
    """持有中：2026-09-06 买入，到今天正好 10 天。"""
    return Device(
        id=1,
        name="iPhone 15 Pro",
        category="手机",
        purchase_price=8999.0,
        purchase_date=date(2026, 9, 6),
    )


@pytest.fixture
def sold_device() -> Device:
    """已售出：2026-01-01 买入，2026-04-11 卖出，持有 100 天。"""
    return Device(
        id=2,
        name="MacBook Air M2",
        category="电脑",
        purchase_price=9499.0,
        purchase_date=date(2026, 1, 1),
        sale_price=6500.0,
        sale_date=date(2026, 4, 11),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """临时数据库路径。测试绝不碰真实的 devices.db。"""
    return tmp_path / "test_devices.db"
