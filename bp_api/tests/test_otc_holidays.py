"""A股预估节假日单测。"""

from datetime import date

from bp_api.quant.otc.holidays import is_estimated_cn_holiday


def test_solar_holidays():
    assert is_estimated_cn_holiday(date(2026, 1, 1))
    assert is_estimated_cn_holiday(date(2026, 5, 3))
    assert is_estimated_cn_holiday(date(2026, 10, 5))
    assert not is_estimated_cn_holiday(date(2026, 3, 15))


def test_spring_festival_block():
    assert is_estimated_cn_holiday(date(2026, 2, 17))
    assert not is_estimated_cn_holiday(date(2026, 2, 25))
