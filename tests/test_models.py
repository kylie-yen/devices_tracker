"""派生计算与筛选规则的测试。

这些是全应用最值得测的部分：纯函数、无 Qt 依赖、边界情况密集。
"""

from __future__ import annotations

from datetime import date

import pytest

from devicetracker.models import (
    STATUS_ALL,
    STATUS_HELD,
    STATUS_SOLD,
    Device,
    matches,
    summarize,
)


def make_device(**overrides) -> Device:
    """构造一台默认合法的设备，只覆盖当前测试关心的字段。"""
    defaults = {
        "name": "测试设备",
        "category": "其他",
        "purchase_price": 1000.0,
        "purchase_date": date(2026, 1, 1),
    }
    defaults.update(overrides)
    return Device(**defaults)


# --- 持有天数 -------------------------------------------------------------


def test_days_held_counts_to_today_when_unsold(held_device, today):
    assert held_device.days_held(today) == 10


def test_days_held_freezes_at_sale_date_when_sold(sold_device, today):
    # 已售出的设备，天数不再随 today 增长
    assert sold_device.days_held(today) == 100
    assert sold_device.days_held(date(2030, 1, 1)) == 100


def test_days_held_is_zero_when_bought_and_sold_same_day(today):
    device = make_device(
        purchase_date=today, sale_price=800.0, sale_date=today
    )
    assert device.days_held(today) == 0


def test_days_held_is_zero_when_purchase_date_in_the_future(today):
    """误填未来日期时钳到 0，不产生负天数。"""
    device = make_device(purchase_date=date(2026, 12, 31))
    assert device.days_held(today) == 0


def test_days_held_is_zero_when_sale_date_precedes_purchase(today):
    """脏数据兜底；主防线是对话框校验和数据库 CHECK。"""
    device = make_device(
        purchase_date=date(2026, 5, 1), sale_price=500.0, sale_date=date(2026, 4, 1)
    )
    assert device.days_held(today) == 0


# --- 摊销分母 -------------------------------------------------------------


def test_billing_days_never_drops_below_one(today):
    device = make_device(purchase_date=today)
    assert device.days_held(today) == 0
    assert device.billing_days(today) == 1


def test_billing_days_passes_through_nonzero_days(held_device, today):
    assert held_device.billing_days(today) == 10


# --- 日均价格 -------------------------------------------------------------


def test_daily_costs_equal_full_price_on_purchase_day(today):
    """当天买入：分母为 1，日均等于全价，而不是除零崩溃或显示空白。"""
    device = make_device(purchase_price=3000.0, purchase_date=today)
    assert device.daily_purchase_cost(today) == pytest.approx(3000.0)
    assert device.daily_net_cost(today) == pytest.approx(3000.0)


def test_daily_purchase_cost_ignores_sale_price(sold_device, today):
    assert sold_device.daily_purchase_cost(today) == pytest.approx(9499.0 / 100)


def test_daily_net_cost_subtracts_sale_price(sold_device, today):
    assert sold_device.daily_net_cost(today) == pytest.approx((9499.0 - 6500.0) / 100)


def test_daily_net_cost_treats_unsold_as_zero_recovery(held_device, today):
    assert held_device.daily_net_cost(today) == pytest.approx(8999.0 / 10)


def test_daily_net_cost_goes_negative_on_profit_and_is_not_clamped(today):
    """卖价高于买价说明还赚了，负数是有效信息，不该被钳到 0。"""
    device = make_device(
        purchase_price=1000.0,
        purchase_date=date(2026, 1, 1),
        sale_price=1500.0,
        sale_date=date(2026, 1, 11),
    )
    assert device.daily_net_cost(today) == pytest.approx(-50.0)


def test_zero_purchase_price_does_not_raise(today):
    device = make_device(purchase_price=0.0, purchase_date=today)
    assert device.daily_purchase_cost(today) == 0.0
    assert device.daily_net_cost(today) == 0.0


def test_gifted_device_with_zero_sale_price_keeps_full_cost(today):
    """售价 0（送人/丢失）是合法输入，净成本等于全价摊到每天。"""
    device = make_device(
        purchase_price=2000.0,
        purchase_date=date(2026, 1, 1),
        sale_price=0.0,
        sale_date=date(2026, 1, 11),
    )
    assert device.daily_net_cost(today) == pytest.approx(200.0)


# --- 售出状态判定 ---------------------------------------------------------


def test_is_sold_false_when_both_sale_fields_are_none(held_device):
    assert held_device.is_sold is False


def test_is_sold_true_when_sale_date_present(sold_device):
    assert sold_device.is_sold is True


def test_zero_sale_price_without_sale_date_is_still_held():
    """关键边界：用 sale_price 判定就会在这里出错。"""
    device = make_device(sale_price=0.0, sale_date=None)
    assert device.is_sold is False
    assert device.status_text == "持有中"


def test_sale_date_without_price_is_sold():
    """白送出去也算售出，天数应当冻结。"""
    device = make_device(sale_price=None, sale_date=date(2026, 3, 1))
    assert device.is_sold is True
    assert device.status_text == "已售出"


# --- 汇总 -----------------------------------------------------------------


def test_summary_of_empty_list_is_all_zero(today):
    summary = summarize([], today)
    assert summary.count == 0
    assert summary.held_count == 0
    assert summary.sold_count == 0
    assert summary.total_invested == 0.0
    assert summary.total_recovered == 0.0
    assert summary.total_daily_purchase == 0.0
    assert summary.total_daily_net == 0.0
    assert summary.net_spend == 0.0


def test_summary_totals_and_counts(held_device, sold_device, today):
    summary = summarize([held_device, sold_device], today)

    assert summary.count == 2
    assert summary.held_count == 1
    assert summary.sold_count == 1
    assert summary.total_invested == pytest.approx(8999.0 + 9499.0)
    assert summary.total_recovered == pytest.approx(6500.0)
    assert summary.net_spend == pytest.approx(8999.0 + 9499.0 - 6500.0)
    assert summary.total_daily_purchase == pytest.approx(8999.0 / 10 + 9499.0 / 100)
    assert summary.total_daily_net == pytest.approx(
        8999.0 / 10 + (9499.0 - 6500.0) / 100
    )


def test_summary_net_spend_goes_negative_when_overall_profitable(today):
    device = make_device(
        purchase_price=1000.0,
        purchase_date=date(2026, 1, 1),
        sale_price=1500.0,
        sale_date=date(2026, 1, 11),
    )
    summary = summarize([device], today)
    assert summary.net_spend == pytest.approx(-500.0)


# --- 筛选 -----------------------------------------------------------------


def test_empty_query_matches_everything(held_device):
    assert matches(held_device, query="") is True


def test_whitespace_only_query_matches_everything(held_device):
    assert matches(held_device, query="   ") is True


def test_query_matches_name_case_insensitively(held_device):
    assert matches(held_device, query="iphone") is True
    assert matches(held_device, query="IPHONE") is True


def test_query_matches_category(held_device):
    assert matches(held_device, query="手机") is True


def test_query_matches_note():
    device = make_device(note="闲鱼出手，成色九成新")
    assert matches(device, query="闲鱼") is True


def test_query_with_no_hit_is_rejected(held_device):
    assert matches(held_device, query="不存在的关键词") is False


def test_category_filter_requires_exact_match(held_device):
    assert matches(held_device, category="手机") is True
    assert matches(held_device, category="电脑") is False


def test_none_category_filter_matches_everything(held_device, sold_device):
    assert matches(held_device, category=None) is True
    assert matches(sold_device, category=None) is True


def test_status_filter_held(held_device, sold_device):
    assert matches(held_device, status=STATUS_HELD) is True
    assert matches(sold_device, status=STATUS_HELD) is False


def test_status_filter_sold(held_device, sold_device):
    assert matches(held_device, status=STATUS_SOLD) is False
    assert matches(sold_device, status=STATUS_SOLD) is True


def test_status_filter_all_accepts_both(held_device, sold_device):
    assert matches(held_device, status=STATUS_ALL) is True
    assert matches(sold_device, status=STATUS_ALL) is True


def test_filters_combine_with_and_semantics(held_device, sold_device):
    """关键词、分类、状态三者是与的关系。"""
    assert matches(held_device, query="iphone", category="手机", status=STATUS_HELD)
    # 关键词命中但状态不符 -> 整体不通过
    assert not matches(
        held_device, query="iphone", category="手机", status=STATUS_SOLD
    )
