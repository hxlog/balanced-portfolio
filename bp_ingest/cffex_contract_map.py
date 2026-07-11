"""中金所股指期货合约映射逻辑。

CFFEX 股指期货挂牌规则:
  - 当月合约: 最近月份的合约
  - 次月合约: 次近月份的合约
  - 当季合约: 最近的季月合约 (3/6/9/12 月中的最近一个)
  - 次季合约: 次近的季月合约

合约代码解析: 'IF2603' → variety='IF', year=2026, month=3
交割日: 合约到期月的第三个星期五

共享于 bp_ingest 和 bp_api 之间。
"""

from __future__ import annotations

import re
from calendar import FRIDAY, monthcalendar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# 品种与指数映射
# ---------------------------------------------------------------------------
CFFEX_VARIETIES = ["IF", "IH", "IC", "IM"]

# 挂钩指数: 品种 → 指数代码 (用于 bp_index_quote_daily 查询)
INDEX_SYMBOL_MAP: dict[str, str] = {
    "IF": "000300",   # 沪深300
    "IH": "000016",   # 上证50
    "IC": "000905",   # 中证500
    "IM": "000852",   # 中证1000
}

# 实时行情用 Sina 代码前缀
INDEX_SINA_MAP: dict[str, str] = {
    "IF": "sh000300",
    "IH": "sh000016",
    "IC": "sh000905",
    "IM": "sh000852",
}

# 品种中文名
VARIETY_NAMES: dict[str, str] = {
    "IF": "沪深300",
    "IH": "上证50",
    "IC": "中证500",
    "IM": "中证1000",
}

# 合约类型排序权重 (用于排序)
CONTRACT_TYPE_ORDER: dict[str, int] = {
    "当月": 0,
    "次月": 1,
    "当季": 2,
    "次季": 3,
}

# 季月
QUARTERLY_MONTHS = {3, 6, 9, 12}


# ---------------------------------------------------------------------------
# 合约解析
# ---------------------------------------------------------------------------

_CONTRACT_RE = re.compile(r"^(IF|IH|IC|IM)(\d{2})(\d{2})$", re.IGNORECASE)


@dataclass(frozen=True)
class Contract:
    symbol: str       # e.g. "IF2603"
    variety: str      # "IF"
    year: int         # 2026
    month: int        # 3
    expiry_date: date  # 第三个星期五

    @classmethod
    def parse(cls, symbol: str) -> Optional["Contract"]:
        """解析合约代码, 返回 Contract 或 None(非股指期货品种)。"""
        m = _CONTRACT_RE.match(symbol.strip().upper())
        if not m:
            return None
        variety = m.group(1)
        y = 2000 + int(m.group(2))
        mo = int(m.group(3))
        if mo < 1 or mo > 12:
            return None
        expiry = _third_friday(y, mo)
        return cls(symbol=symbol.strip().upper(), variety=variety,
                    year=y, month=mo, expiry_date=expiry)

    @property
    def is_quarterly(self) -> bool:
        return self.month in QUARTERLY_MONTHS


def _third_friday(year: int, month: int) -> date:
    """给定年月的第三个星期五。"""
    cal = monthcalendar(year, month)
    # 第三个星期五: 检查第3行或第4行的星期五(取决于月初是星期几)
    fridays = []
    for week in cal:
        if week[FRIDAY] != 0:
            fridays.append(week[FRIDAY])
    if len(fridays) < 3:
        return date(year, month, fridays[-1])
    return date(year, month, fridays[2])


# ---------------------------------------------------------------------------
# 合约到类型的映射
# ---------------------------------------------------------------------------

def map_contracts(
    contracts: list[Contract], trade_date: date
) -> dict[str, str]:
    """将合约列表映射为 {symbol: contract_type} 的字典。

    CFFEX 规则:
    - 按交割日排序(同品种内)
    - 当月: 交割日 >= trade_date 的最早合约 (即尚未到期的最近月合约)
    - 次月: 第二早合约
    - 当季: 季月中最接近的合约 (可能等于当月或次月)
    - 次季: 第二近的季月合约

    注意: 当季和次季可能与当月/次月重叠 (如3月: 当月=IF2603, 当季也可=IF2603)。
    实践中四个类型各取不同合约: 当月(today后第1个), 次月(today后第2个),
    当季(季月中第1个), 次季(季月中第2个)。
    当重复时, 次月或次季选取下一个非重复合约。
    """
    if not contracts:
        return {}

    # 仅保留交割日 >= trade_date 的合约
    active = [c for c in contracts if c.expiry_date >= trade_date]
    if not active:
        # 全部已到期: 退化为按交割日降序选取4个
        active = sorted(contracts, key=lambda c: c.expiry_date, reverse=True)[:4]

    # 按交割日升序排序
    active.sort(key=lambda c: c.expiry_date)

    # 季月合约 (按交割日排序)
    quarterly = [c for c in active if c.is_quarterly]

    result: dict[str, str] = {}
    used: set[str] = set()

    # 当月: 第0个
    if len(active) >= 1:
        result[active[0].symbol] = "当月"
        used.add(active[0].symbol)

    # 次月: 第1个 (如果未用)
    for c in active:
        if c.symbol not in used:
            result[c.symbol] = "次月"
            used.add(c.symbol)
            break

    # 当季: 季度合约中交割日最早的 (如果未用)
    for c in quarterly:
        if c.symbol not in used:
            result[c.symbol] = "当季"
            used.add(c.symbol)
            break

    # 次季: 季度合约中第二早的 (如果未用)
    for c in quarterly:
        if c.symbol not in used:
            result[c.symbol] = "次季"
            used.add(c.symbol)
            break

    return result


def map_contracts_from_symbols(
    symbol_list: list[str], trade_date: date
) -> dict[str, str]:
    """从合约代码字符串列表映射类型。非股指期货的 symbol 会被忽略。"""
    contracts: list[Contract] = []
    for s in symbol_list:
        c = Contract.parse(s)
        if c is not None:
            contracts.append(c)
    return map_contracts(contracts, trade_date)


# ---------------------------------------------------------------------------
# 合成年化升贴水率
# ---------------------------------------------------------------------------

def compute_composite(
    premiums: dict[str, float | None]
) -> float | None:
    """合成年化升贴水率 = 0.6×次月 + 0.4×当季。

    去除当月权重以避免交割日异常波动。
    premiums 为 {contract_type: ann_premium_rate} 字典。
    若任一必需值为 None 则返回 None。
    """
    m2 = premiums.get("次月")
    q1 = premiums.get("当季")
    if m2 is None or q1 is None:
        return None
    return 0.6 * m2 + 0.4 * q1


# ---------------------------------------------------------------------------
# 距离交割天数
# ---------------------------------------------------------------------------

def days_to_expiry(symbol: str, trade_date: date) -> int | None:
    """计算合约距离交割的天数 (交易日至第三个星期五)。"""
    c = Contract.parse(symbol)
    if c is None:
        return None
    return (c.expiry_date - trade_date).days


# ---------------------------------------------------------------------------
# 基差与升贴水率
# ---------------------------------------------------------------------------

def compute_basis(spot_price: float, futures_price: float) -> float:
    """基差 = 现货指数 - 期货价格。"""
    return spot_price - futures_price


def compute_premium_rate(basis: float, spot_price: float) -> float | None:
    """升贴水率 = -基差 / 现货指数 = (期货 - 现货) / 现货。

    正值 = 升水(期货 > 现货), 负值 = 贴水(期货 < 现货)。
    spot_price 为 0 时返回 None。
    """
    if spot_price == 0:
        return None
    return -basis / spot_price * 100


def compute_ann_premium_rate(
    premium_rate: float, days: int
) -> float | None:
    """年化升贴水率 = 升贴水率 × 365 / 距离交割天数。days 为 0 时返回 None。"""
    if days <= 0:
        return None
    return premium_rate * 365 / days

