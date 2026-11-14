"""股票行业映射：申万一级行业成分 -> bp_stock_master.industry_l1。

为什么不用东财 push2：连续请求后东财会 abruptly close（curl 56），而 akshare 的
`index_component_sw(symbol=801xxx)` 稳定可用（每个行业 1 次请求，31 个行业）。
"""
from __future__ import annotations

import logging
import time

import psycopg

logger = logging.getLogger(__name__)

# 申万一级行业（2021 版），代码 -> 名称
SW_L1: dict[str, str] = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}


def _market(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("8", "4", "9")):
        return "BJ"
    return "SZ"


def sync_industries(conn: psycopg.Connection, sleep_seconds: float = 0.5) -> dict:
    """遍历 31 个申万一级行业，把成分股行业写进 bp_stock_master。"""
    import akshare as ak

    payload: dict[str, dict] = {}
    failures: list[str] = []
    for code, name in SW_L1.items():
        try:
            frame = ak.index_component_sw(symbol=code)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{code}: {type(exc).__name__}")
            continue
        for _, row in frame.iterrows():
            stock_code = str(row.get("证券代码") or "").strip()
            stock_name = str(row.get("证券名称") or "").strip()
            if len(stock_code) != 6 or not stock_name:
                continue
            payload[stock_code] = {
                "stock_code": stock_code,
                "market": _market(stock_code),
                "name": stock_name,
                "industry_l1": name,
            }
        time.sleep(sleep_seconds)

    rows = list(payload.values())
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bp_stock_master (stock_code, market, name, industry_l1)
            VALUES (%(stock_code)s, %(market)s, %(name)s, %(industry_l1)s)
            ON CONFLICT (stock_code) DO UPDATE SET
                name = EXCLUDED.name,
                industry_l1 = EXCLUDED.industry_l1,
                updated_at = now()
            """,
            rows,
        )
    conn.commit()
    return {"stocks": len(rows), "industries": len(SW_L1) - len(failures), "failures": failures}
