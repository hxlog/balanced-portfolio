"""A股预估节假日 (官方日历未公布段): 固定阳历 + 农历主要节日硬编码表。

超出 akshare 官方交易日历范围后, 周末以外再扣除这些日期, confidence=estimated。
"""

from __future__ import annotations

from datetime import date, timedelta


def _range(start: date, days: int) -> set[date]:
    return {start + timedelta(days=i) for i in range(days)}


# 春节 / 清明 / 端午 / 中秋 (国务院安排近似, 2019–2032)
_LUNAR_BLOCKS: dict[int, list[tuple[date, int]]] = {
    2019: [(date(2019, 2, 4), 7), (date(2019, 4, 5), 3), (date(2019, 6, 7), 3), (date(2019, 9, 13), 3)],
    2020: [(date(2020, 1, 24), 7), (date(2020, 4, 4), 3), (date(2020, 6, 25), 3), (date(2020, 10, 1), 8)],
    2021: [(date(2021, 2, 11), 7), (date(2021, 4, 3), 3), (date(2021, 6, 12), 3), (date(2021, 9, 19), 3)],
    2022: [(date(2022, 1, 31), 7), (date(2022, 4, 3), 3), (date(2022, 6, 3), 3), (date(2022, 9, 10), 3)],
    2023: [(date(2023, 1, 21), 7), (date(2023, 4, 5), 3), (date(2023, 6, 22), 3), (date(2023, 9, 29), 8)],
    2024: [(date(2024, 2, 10), 8), (date(2024, 4, 4), 3), (date(2024, 6, 10), 3), (date(2024, 9, 15), 3)],
    2025: [(date(2025, 1, 28), 8), (date(2025, 4, 4), 3), (date(2025, 5, 31), 3), (date(2025, 10, 1), 8)],
    2026: [(date(2026, 2, 16), 7), (date(2026, 4, 5), 3), (date(2026, 6, 19), 3), (date(2026, 9, 25), 3)],
    2027: [(date(2027, 2, 6), 7), (date(2027, 4, 5), 3), (date(2027, 6, 9), 3), (date(2027, 9, 15), 3)],
    2028: [(date(2028, 1, 26), 7), (date(2028, 4, 4), 3), (date(2028, 5, 28), 3), (date(2028, 10, 3), 3)],
    2029: [(date(2029, 2, 13), 7), (date(2029, 4, 4), 3), (date(2029, 6, 16), 3), (date(2029, 9, 22), 3)],
    2030: [(date(2030, 2, 3), 7), (date(2030, 4, 5), 3), (date(2030, 6, 5), 3), (date(2030, 9, 12), 3)],
    2031: [(date(2031, 1, 23), 7), (date(2031, 4, 4), 3), (date(2031, 6, 24), 3), (date(2031, 10, 1), 8)],
    2032: [(date(2032, 2, 11), 7), (date(2032, 4, 4), 3), (date(2032, 6, 12), 3), (date(2032, 9, 18), 3)],
}


def _solar_fixed_holidays(d: date) -> bool:
    md = (d.month, d.day)
    if md == (1, 1):
        return True
    if (5, 1) <= md <= (5, 5):
        return True
    if (10, 1) <= md <= (10, 7):
        return True
    return False


def is_estimated_cn_holiday(d: date) -> bool:
    """是否为预估休市日 (仅用于 estimated 段)。"""
    if _solar_fixed_holidays(d):
        return True
    blocks = _LUNAR_BLOCKS.get(d.year, [])
    for start, n in blocks:
        if start <= d < start + timedelta(days=n):
            return True
    return False
