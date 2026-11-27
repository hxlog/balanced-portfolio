"""bp_ingest.csindex_value：日期口径（整数日不得变 1970 脏行）+ PE 映射。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from bp_ingest import csindex_value

COLUMNS = ["date", "code", "name_full", "name", "en_full", "en",
           "pe1", "pe2", "div1", "div2"]


def _frame(rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)


def test_rows_parse_yyyymmdd_int_as_real_date() -> None:
    """审查：整数日 20261127 被 pd.to_datetime 当 ns 时间戳 -> 1970-01-01，必须修正。"""
    frame = _frame(
        [
            [20261127, 985, "中证全指指数", "中证全指", "", "", 17.39, 19.36, 2.38, 2.06],
            [20261126, 985, "中证全指指数", "中证全指", "", "", 17.31, 19.30, 2.39, 2.07],
        ]
    )
    rows = csindex_value._rows(frame)
    assert [row["trade_date"] for row in rows] == [date(2026, 11, 27), date(2026, 11, 26)]
    assert rows[0]["pe_ttm"] == 17.39
    assert rows[0]["pe_static"] is None
    assert rows[0]["pe2_calc_share"] == 19.36


def test_rows_parse_string_and_timestamp_dates() -> None:
    frame = _frame(
        [
            ["20261125", 985, "", "", "", "", 17.2, 19.2, 2.4, 2.1],
            [pd.Timestamp("2026-11-24"), 985, "", "", "", "", 17.1, 19.1, 2.4, 2.1],
        ]
    )
    rows = csindex_value._rows(frame)
    assert [row["trade_date"] for row in rows] == [date(2026, 11, 25), date(2026, 11, 24)]


def test_rows_drops_1970_dirty_rows_and_nan() -> None:
    frame = _frame(
        [
            ["19700101", 985, "", "", "", "", 0.01, 0.02, 0, 0],  # 历史脏行
            [None, 985, "", "", "", "", 1.0, 1.0, 0, 0],
            [20261127, 985, "", "", "", "", 17.39, 19.36, 2.38, 2.06],
        ]
    )
    rows = csindex_value._rows(frame)
    assert [row["trade_date"] for row in rows] == [date(2026, 11, 27)]


def test_parse_trade_date_rejects_pre_1990() -> None:
    assert csindex_value._parse_trade_date(19700101) is None
    assert csindex_value._parse_trade_date("1970-01-01") is None
    assert csindex_value._parse_trade_date("20261127") == date(2026, 11, 27)
    assert csindex_value._parse_trade_date(pd.NaT) is None
