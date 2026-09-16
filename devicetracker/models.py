"""领域模型与纯计算逻辑。

本模块刻意不引入任何 Qt 组件。所有派生值都是
``(purchase_date, sale_date, today)`` 的纯函数，``today`` 一律由调用方注入，
因此整套业务规则可以在没有 QApplication 的环境下直接测试。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

# 状态筛选的取值。用字符串常量而不是裸字面量，避免 UI 和模型对不上。
STATUS_ALL = "all"
STATUS_HELD = "held"
STATUS_SOLD = "sold"

STATUS_LABELS: dict[str, str] = {
    STATUS_ALL: "全部状态",
    STATUS_HELD: "持有中",
    STATUS_SOLD: "已售出",
}


@dataclass
class Device:
    """一台设备的持有记录。

    只保存事实：购入价、购入日期、售出价、售出日期。持有天数和日均价格都是
    读的时候现算 —— 它们每天都在变，一旦落库就会立刻产生陈旧数据。
    """

    name: str
    purchase_price: float
    purchase_date: date
    category: str = ""
    sale_price: float | None = None
    sale_date: date | None = None
    note: str = ""
    id: int | None = None

    # --- 派生值 -----------------------------------------------------------

    @property
    def is_sold(self) -> bool:
        """是否已售出。

        判定依据是 ``sale_date`` 而不是 ``sale_price``：售价为 0（送人、丢失）
        是完全合法的输入，用价格判定会把它误当成「持有中」。
        """
        return self.sale_date is not None

    @property
    def status_text(self) -> str:
        """状态下拉和导出共用的显示文案。"""
        return STATUS_LABELS[STATUS_SOLD if self.is_sold else STATUS_HELD]

    def days_held(self, today: date) -> int:
        """持有天数。已售出算到售出日，未售出算到今天。

        钳到 0 以上，这样购入日期误填成未来日期时不会出现负天数。
        """
        end = self.sale_date or today
        return max(0, (end - self.purchase_date).days)

    def billing_days(self, today: date) -> int:
        """摊销用的分母：不足一天按一天计。

        当天买当天卖会让持有天数为 0，直接做除数会炸。约定持有 1 天的日均
        就等于全价，语义自洽，也让「今天刚买」这一行有数字可看而不是空白。
        """
        return max(self.days_held(today), 1)

    def daily_purchase_cost(self, today: date) -> float:
        """购入成本日均 = 购入价 ÷ 持有天数。"""
        return self.purchase_price / self.billing_days(today)

    def daily_net_cost(self, today: date) -> float:
        """净成本日均 = (购入价 − 售出价) ÷ 持有天数。

        未售出时售出价按 0 计。售出价高于购入价时结果为负 —— 表示这件设备
        不但没花钱还赚了，不钳制到 0，这个数字本身就是有信息量的。
        """
        recovered = self.sale_price or 0.0
        return (self.purchase_price - recovered) / self.billing_days(today)


@dataclass
class Summary:
    """一批设备的汇总口径。"""

    count: int = 0
    held_count: int = 0
    sold_count: int = 0
    total_invested: float = 0.0  # 总投入 = Σ 购入价
    total_recovered: float = 0.0  # 已回血 = Σ 售出价
    total_daily_purchase: float = 0.0  # Σ 购入成本日均
    total_daily_net: float = 0.0  # Σ 净成本日均

    @property
    def net_spend(self) -> float:
        """净支出 = 总投入 − 已回血。为负表示整体是净收益。"""
        return self.total_invested - self.total_recovered


def summarize(devices: Iterable[Device], today: date) -> Summary:
    """汇总一批设备。空列表返回全 0，不抛异常。"""
    summary = Summary()
    for device in devices:
        summary.count += 1
        if device.is_sold:
            summary.sold_count += 1
        else:
            summary.held_count += 1
        summary.total_invested += device.purchase_price
        summary.total_recovered += device.sale_price or 0.0
        summary.total_daily_purchase += device.daily_purchase_cost(today)
        summary.total_daily_net += device.daily_net_cost(today)
    return summary


def matches(
    device: Device,
    *,
    query: str = "",
    category: str | None = None,
    status: str = STATUS_ALL,
) -> bool:
    """筛选谓词。

    放在这里而不是写进 Qt 的 proxy 里，是为了让筛选规则能脱离 Qt 测试；
    proxy 那边只剩一行委托。
    """
    if query:
        needle = query.strip().casefold()
        if needle:
            haystack = "\n".join((device.name, device.category, device.note)).casefold()
            if needle not in haystack:
                return False

    if category and device.category != category:
        return False

    if status == STATUS_HELD and device.is_sold:
        return False
    if status == STATUS_SOLD and not device.is_sold:
        return False

    return True
