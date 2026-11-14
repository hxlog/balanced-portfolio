"""股票行业映射：东财 push2 clist 的 f100（行业名称）→ bp_stock_master.industry_l1。

成分股的行业字段平安不提供，只能用东财行业分类补齐；东财行业是单层名称（如「医药制造」），
与申万一级不同，因此只填 industry_l1 并保留来源前缀注释。
"""
from __future__ import annotations

import logging
import time

import psycopg
import requests

from .http_session import install_hardened_session

logger = logging.getLogger(__name__)

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
BOARD_FILTERS = ("m:1+t:2", "m:0+t:6", "m:0+t:80", "m:1+t:23", "m:0+t:81+s:2048")
FIELDS = "f12,f14,f100"


def _market(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("8", "4", "9")):
        return "BJ"
    return "SZ"


def _fetch(fs_filter: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    total = None
    while page <= 80:
        params = {
            "pn": str(page), "pz": "100", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": fs_filter, "fields": FIELDS,
        }
        response = requests.get(CLIST_URL, params=params, timeout=25)
        response.raise_for_status()
        data = (response.json().get("data") or {})
        diff = data.get("diff") or []
        if total is None:
            total = int(data.get("total") or 0)
        if not diff:
            break
        rows.extend(row for row in diff if isinstance(row, dict))
        if total is not None and len(rows) >= total:
            break
        page += 1
        time.sleep(0.35)
    return rows


def sync_industries(conn: psycopg.Connection) -> dict:
    install_hardened_session()
    payload: list[dict] = []
    seen: set[str] = set()
    for fs_filter in BOARD_FILTERS:
        for row in _fetch(fs_filter):
            code = str(row.get("f12") or "")
            name = str(row.get("f14") or "")
            industry = row.get("f100")
            if len(code) != 6 or not name or code in seen:
                continue
            seen.add(code)
            payload.append({
                "stock_code": code,
                "market": _market(code),
                "name": name,
                "industry_l1": industry if isinstance(industry, str) and industry else None,
            })
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bp_stock_master (stock_code, market, name, industry_l1)
            VALUES (%(stock_code)s, %(market)s, %(name)s, %(industry_l1)s)
            ON CONFLICT (stock_code) DO UPDATE SET
                name = EXCLUDED.name,
                industry_l1 = COALESCE(EXCLUDED.industry_l1, bp_stock_master.industry_l1),
                updated_at = now()
            """,
            payload,
        )
    conn.commit()
    filled = sum(1 for item in payload if item["industry_l1"])
    return {"stocks": len(payload), "with_industry": filled}
