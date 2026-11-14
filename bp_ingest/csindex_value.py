"""中证指数官网估值源（第二口径，用于与平安主口径交叉校验）。

数据文件：https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls
列：日期 / 指数代码 / 名称 / 市盈率1 / 市盈率2 / 股息率1 / 股息率2（仅滚动 20 个交易日，需日积月累）。

口径假设（写库时以 pe_basis 标注）：
- 市盈率1 -> pe_static（静态），市盈率2 -> pe_ttm（滚动）
- 股息率1 -> dividend_yield_lyr，股息率2 -> dividend_yield_ttm
差异 > 20% 时写 bp_data_quality_log（warn），供 UI 角标与人工复核。
"""
from __future__ import annotations

import io
import logging
import time
from datetime import date
from typing import Iterable

import pandas as pd
import psycopg
import requests

from .http_session import install_hardened_session

logger = logging.getLogger(__name__)

CALC_SRC = "csindex_value"
BASE_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
    "autofile/indicator/{code}indicator.xls"
)
COLUMNS = ["date", "code", "name_full", "name", "en_full", "en", "pe1", "pe2", "div1", "div2"]
DIFF_THRESHOLD = 20.0


def fetch_indicator(code: str, session: requests.Session | None = None) -> pd.DataFrame:
    getter = (session or requests).get
    response = getter(BASE_URL.format(code=code), timeout=20)
    response.raise_for_status()
    frame = pd.read_excel(io.BytesIO(response.content))
    frame.columns = COLUMNS[: len(frame.columns)]
    return frame


def _rows(frame: pd.DataFrame, days: int = 20) -> list[dict]:
    out: list[dict] = []
    for _, row in frame.head(days).iterrows():
        raw = row.get("date")
        try:
            trade_date = pd.to_datetime(raw, errors="coerce")
        except (ValueError, TypeError):
            continue
        if pd.isna(trade_date):
            continue
        out.append({
            "trade_date": trade_date.date(),
            "pe_static": _num(row.get("pe1")),
            "pe_ttm": _num(row.get("pe2")),
            "dividend_yield_lyr": _num(row.get("div1")),
            "dividend_yield_ttm": _num(row.get("div2")),
        })
    return out


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN 过滤


def run(conn: psycopg.Connection, limit: int | None = None, sleep_seconds: float = 1.0) -> dict:
    """抓取中证官网估值并落库（第二口径，非主口径）。"""
    install_hardened_session()
    session = requests.Session()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT index_code FROM bp_index_master
               WHERE market IN ('CSI','SH','SZ','CNI') AND is_tracked
               ORDER BY index_code""",
        )
        codes = [row[0] for row in cur.fetchall()]
    if limit:
        codes = codes[:limit]

    stored = 0
    diffs = 0
    failures: list[str] = []
    with conn.cursor() as cur:
        for index_code in codes:
            try:
                frame = fetch_indicator(index_code, session)
                rows = _rows(frame)
            except Exception as exc:  # noqa: BLE001 - 单指数失败不中断
                failures.append(f"{index_code}: {type(exc).__name__}")
                continue
            cur.execute(
                "DELETE FROM bp_index_valuation_series WHERE index_code = %s AND calc_src = %s",
                (index_code, CALC_SRC),
            )
            payload = []
            for row in rows:
                for metric, key in (
                    ("pe_ttm", "pe_ttm"),
                    ("pe_static", "pe_static"),
                    ("dividend_yield_ttm", "dividend_yield_ttm"),
                    ("dividend_yield_lyr", "dividend_yield_lyr"),
                ):
                    value = row.get(key)
                    if value is None:
                        continue
                    payload.append({
                        "index_code": index_code,
                        "trade_date": row["trade_date"],
                        "metric": metric,
                        "value": value,
                    })
            if payload:
                cur.executemany(
                    """
                    INSERT INTO bp_index_valuation_series
                        (index_code, trade_date, metric, calc_src, value, is_weekly)
                    VALUES (%(index_code)s, %(trade_date)s, %(metric)s, %(calc_src)s, %(value)s, FALSE)
                    ON CONFLICT (index_code, trade_date, metric, calc_src) DO UPDATE
                        SET value = EXCLUDED.value, captured_at = now()
                    """,
                    [dict(item, calc_src=CALC_SRC) for item in payload],
                )
                stored += len(payload)
            diffs += _log_diff(cur, index_code)
            time.sleep(sleep_seconds)
    conn.commit()
    return {"codes": len(codes), "series_rows": stored, "diff_rows": diffs, "failures": failures[:10], "failure_count": len(failures)}


def _log_diff(cur: psycopg.Cursor, index_code: str) -> int:
    """同日与平安主口径序列比较 PE(TTM)，相对差 > 阈值时写质量日志。"""
    cur.execute(
        """
        SELECT s.trade_date, p.value, s.value
        FROM bp_index_valuation_series s
        JOIN bp_index_valuation_series p
          ON p.index_code = s.index_code
         AND p.trade_date = s.trade_date
         AND p.metric = %s
         AND p.calc_src = %s
        WHERE s.index_code = %s
          AND s.metric = %s
          AND s.calc_src = %s
          AND p.value IS NOT NULL AND p.value > 0
        """,
        ("pe_ttm", "pingan_index", index_code, "pe_ttm", CALC_SRC),
    )
    count = 0
    for trade_date, primary_value, check_value in cur.fetchall():
        if not check_value:
            continue
        rel = abs(float(primary_value) - float(check_value)) / float(primary_value) * 100
        if rel < DIFF_THRESHOLD:
            continue
        cur.execute(
            """
            INSERT INTO bp_data_quality_log
                (index_code, trade_date, metric, primary_src, check_src,
                 primary_value, check_value, rel_diff, level)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (index_code, trade_date, "pe_ttm", "pingan_index", CALC_SRC,
             primary_value, check_value, rel, "warn"),
        )
        count += 1
    return count
