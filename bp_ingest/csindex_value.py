"""中证指数官网估值源（第二口径，用于与平安主口径交叉校验）。

数据文件：https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls
列：日期 / 指数代码 / 名称 / 市盈率1 / 市盈率2 / 股息率1 / 股息率2（仅滚动 20 个交易日，需日积月累）。

口径（2026-11-27 交叉校验修正）：
- 中证官网两列是「市盈率1（总股本）/市盈率2（计算用股本）」，不是静态/滚动：
  市盈率1 ≈ 平安 peRatio 主口径（000300 实测相对差 4.4%<5%），映射 pe_ttm；
  市盈率2 与主口径差 ~14%，不冒充 pe_static（pe_static 留空，PE2 仅审计保留）。
- 股息率1/2 仍按 LYR/TTM 假设落 bp_data_quality_log 交叉校验。
- 日期列整数日（20261127）必须按 %Y%m%d 解析，禁止 pd.to_datetime 直接吃整数
  （会被当 ns 时间戳产出 1970-01-01 脏行）。
差异 > 20% 时写 bp_data_quality_log（warn），供 UI 角标与人工复核。
"""
from __future__ import annotations

import io
import logging
import time
from datetime import date, datetime
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


def _parse_trade_date(value) -> date | None:
    """中证 indicator.xls 日期列归一化。

    坑（2026-11-27 审查）：Excel 里的整数日（如 20261127）被 pd.to_datetime 当成
    ns 时间戳，产出 1970-01-01 脏行（实测 376 行）。这里先按 YYYYMMDD 整数/字符串
    解析，再回退通用解析；1970 等早于 1990 的伪日期一律丢弃。
    """
    if isinstance(value, datetime):
        return value.date() if value.year >= 1990 else None
    if isinstance(value, date):
        return value if value.year >= 1990 else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(int(value))
        if len(text) == 8:
            try:
                day = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
            except ValueError:
                return None
            return day if day.year >= 1990 else None
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        try:
            day = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
        return day if day.year >= 1990 else None
    try:
        parsed = pd.to_datetime(text, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(parsed):
        return None
    day = parsed.date()
    return day if day.year >= 1990 else None


def _rows(frame: pd.DataFrame, days: int = 20) -> list[dict]:
    out: list[dict] = []
    for _, row in frame.head(days).iterrows():
        trade_date = _parse_trade_date(row.get("date"))
        if trade_date is None:
            continue
        out.append({
            "trade_date": trade_date,
            # 与 valuation_ingest._parse_csindex_indicator 同口径：PE1=总股本（映射
            # pe_ttm，与平安主口径可比），PE2=计算用股本不是静态 PE，仅审计保留。
            "pe_static": None,
            "pe_ttm": _num(row.get("pe1")),
            "pe2_calc_share": _num(row.get("pe2")),
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
