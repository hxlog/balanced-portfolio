"""全市场估值快照：东财 push2 clist（板块分页拉取）→ 中位数/等权 PE、PB → 落库 + 分位。

为什么不用 akshare.stock_zh_a_spot_em：该函数在服务器上被东财断连（RemoteDisconnected），
而项目已用 curl_cffi 硬化会话直连 push2 成功（同 dxy_em 的做法）。
"""
from __future__ import annotations

import logging
import time
import statistics
from datetime import date
from typing import Any, Iterable, Mapping

import psycopg
import requests

from .http_session import install_hardened_session

logger = logging.getLogger(__name__)

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
FIELDS = "f12,f14,f2,f9,f23,f20"  # 代码/名称/现价/动态PE/市净率/总市值
PAGE_SIZE = 6000

BOARD_FILTERS: dict[str, tuple[str, ...]] = {
    "main": ("m:1+t:2", "m:0+t:6"),
    "chinext": ("m:0+t:80",),
    "star": ("m:1+t:23",),
    "bse": ("m:0+t:81+s:2048",),
}


def _fetch_board(fs_filter: str) -> list[dict[str, Any]]:
    """分页拉取一个板块的全部个股（push2 单页上限 100）。"""
    rows: list[dict[str, Any]] = []
    page = 1
    total = None
    while page <= 80:
        params = {
            "pn": str(page),
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs_filter,
            "fields": FIELDS,
        }
        response = requests.get(CLIST_URL, params=params, timeout=25)
        response.raise_for_status()
        payload = response.json()
        data = (payload.get("data") or {})
        diff = data.get("diff") or []
        if total is None:
            total = int(data.get("total") or 0)
        if not diff:
            break
        rows.extend(row for row in diff if isinstance(row, dict))
        if total is not None and len(rows) >= total:
            break
        page += 1
        time.sleep(0.25)
    return rows

def _stats(rows: Iterable[Mapping[str, Any]]) -> tuple[float | None, float | None, float | None, float | None, int]:
    pes = [float(r["f9"]) for r in rows if isinstance(r.get("f9"), (int, float)) and r["f9"] > 0]
    pbs = [float(r["f23"]) for r in rows if isinstance(r.get("f23"), (int, float)) and r["f23"] > 0]
    return (
        statistics.median(pes) if pes else None,
        statistics.fmean(pes) if pes else None,
        statistics.median(pbs) if pbs else None,
        statistics.fmean(pbs) if pbs else None,
        len(pes),
    )


def compute(conn: psycopg.Connection, as_of: date | None = None) -> dict:
    """抓取并写入当日各板块估值；返回摘要。"""
    install_hardened_session()
    trade_date = as_of or date.today()
    rows_by_board: dict[str, list[dict]] = {}
    all_rows: list[dict] = []
    for board, filters in BOARD_FILTERS.items():
        board_rows: list[dict] = []
        for fs_filter in filters:
            board_rows.extend(_fetch_board(fs_filter))
        rows_by_board[board] = board_rows
        all_rows.extend(board_rows)
    rows_by_board["all"] = all_rows

    payload = []
    for board, rows in rows_by_board.items():
        pe_med, pe_eq, pb_med, pb_eq, sample = _stats(rows)
        payload.append({
            "board": board,
            "trade_date": trade_date,
            "pe_median": pe_med,
            "pe_equal": pe_eq,
            "pb_median": pb_med,
            "pb_equal": pb_eq,
            "sample_size": sample,
            "calc_src": "eastmoney_snapshot",
        })

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bp_market_valuation_daily
                (board, trade_date, pe_median, pe_equal, pb_median, pb_equal, sample_size, calc_src)
            VALUES (%(board)s, %(trade_date)s, %(pe_median)s, %(pe_equal)s,
                    %(pb_median)s, %(pb_equal)s, %(sample_size)s, %(calc_src)s)
            ON CONFLICT (board, trade_date) DO UPDATE SET
                pe_median = EXCLUDED.pe_median,
                pe_equal = EXCLUDED.pe_equal,
                pb_median = EXCLUDED.pb_median,
                pb_equal = EXCLUDED.pb_equal,
                sample_size = EXCLUDED.sample_size,
                calc_src = EXCLUDED.calc_src,
                captured_at = now()
            """,
            payload,
        )
        # 分位：Python 侧按月算（历史行数很少，直接拉全量）
        from bp_api.quant.valuation import percentile as _pct

        for row in payload:
            cur.execute(
                "SELECT pe_median, pb_median FROM bp_market_valuation_daily WHERE board = %s AND trade_date <= %s",
                (row["board"], trade_date),
            )
            history = cur.fetchall()
            pe_list = [float(v) for v, _ in history if v is not None]
            pb_list = [float(v) for _, v in history if v is not None]
            pe_now = row["pe_median"]
            pb_now = row["pb_median"]
            cur.execute(
                "UPDATE bp_market_valuation_daily SET pct_pe = %s, pct_pb = %s WHERE board = %s AND trade_date = %s",
                (
                    _pct(pe_list, pe_now) if pe_now is not None else None,
                    _pct(pb_list, pb_now) if pb_now is not None else None,
                    row["board"],
                    trade_date,
                ),
            )
    conn.commit()
    return {"as_of": trade_date, "boards": {b: len(r) for b, r in rows_by_board.items()}}
