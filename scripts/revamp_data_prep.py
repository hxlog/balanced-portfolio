"""重构数据准备：
1) 回填指数简介（bp_index_valuation_daily.raw->>intro → bp_index_master.intro）
2) 回填行业分类（按名称关键词映射申万一级）
3) 重算 4 指标 × 5 窗口分位（1/3/5/10 年 + 全历史）
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_api.quant.valuation import min_sample_for, summarize, window_slice
from bp_api.repositories_valuation import CALC_SRC_PINGAN, fetch_series, upsert_percentiles
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.valuation_ingest import PERCENTILE_METRIC_ORDER, PERCENTILE_WINDOW_ORDER

INDUSTRY_RULES = [
    ("银行", "银行"), ("证券", "非银金融"), ("保险", "非银金融"), ("非银金融", "非银金融"),
    ("医药", "医药生物"), ("医疗", "医药生物"), ("生物", "医药生物"),
    ("食品", "食品饮料"), ("饮料", "食品饮料"), ("白酒", "食品饮料"), ("酒", "食品饮料"),
    ("半导体", "电子"), ("芯片", "电子"), ("消费电子", "电子"), ("电子", "电子"),
    ("计算机", "计算机"), ("软件", "计算机"), ("信创", "计算机"), ("云计算", "计算机"),
    ("通信", "通信"), ("5G", "通信"), ("传媒", "传媒"), ("游戏", "传媒"),
    ("光伏", "电力设备"), ("储能", "电力设备"), ("新能源", "电力设备"), ("电池", "电力设备"),
    ("电力设备", "电力设备"), ("汽车", "汽车"), ("机械", "机械设备"), ("装备", "机械设备"),
    ("化工", "基础化工"), ("化学", "基础化工"), ("有色", "有色金属"), ("黄金", "有色金属"),
    ("煤炭", "煤炭"), ("石油", "石油石化"), ("石化", "石油石化"), ("钢铁", "钢铁"),
    ("建材", "建筑材料"), ("建筑", "建筑装饰"), ("地产", "房地产"), ("房地产", "房地产"),
    ("家电", "家用电器"), ("纺织", "纺织服饰"), ("服装", "纺织服饰"), ("轻工", "轻工制造"),
    ("农业", "农林牧渔"), ("养殖", "农林牧渔"), ("农林牧渔", "农林牧渔"),
    ("商贸", "商贸零售"), ("零售", "商贸零售"), ("旅游", "社会服务"), ("酒店", "社会服务"),
    ("社会服务", "社会服务"), ("交通运输", "交通运输"), ("物流", "交通运输"), ("航运", "交通运输"),
    ("公用事业", "公用事业"), ("环保", "环保"), ("军工", "国防军工"), ("国防", "国防军工"),
]


def classify(name: str) -> str | None:
    for keyword, industry in INDUSTRY_RULES:
        if keyword in name:
            return industry
    return None


def main() -> int:
    setup_logging()
    app = load_config()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bp_index_master m
               SET intro = sub.intro, updated_at = now()
              FROM (
                    SELECT DISTINCT ON (index_code) index_code, raw->>'intro' AS intro
                      FROM bp_index_valuation_daily
                     WHERE is_primary AND raw ? 'intro'
                     ORDER BY index_code, trade_date DESC
                   ) sub
             WHERE m.index_code = sub.index_code
               AND btrim(coalesce(sub.intro, '')) <> ''
               AND (m.intro IS NULL OR btrim(m.intro) = '')
            """
        )
        intro_rows = cur.rowcount
        conn.commit()
        print("intro updated:", intro_rows, flush=True)

        cur.execute("SELECT index_code, name FROM bp_index_master")
        rows = cur.fetchall()
        updated = 0
        for index_code, name in rows:
            industry = classify(name or "")
            if industry is None:
                continue
            cur.execute(
                "UPDATE bp_index_master SET industry = %s, updated_at = now() WHERE index_code = %s",
                (industry, index_code),
            )
            updated += 1
        conn.commit()
        print("industry updated:", updated, "/", len(rows), flush=True)

        cur.execute("SELECT max(trade_date) FROM bp_index_valuation_daily WHERE is_primary")
        as_of = cur.fetchone()[0]
        cur.execute(
            "SELECT DISTINCT index_code FROM bp_index_valuation_series WHERE calc_src = %s",
            (CALC_SRC_PINGAN,),
        )
        codes = [row[0] for row in cur.fetchall()]
        print("as_of:", as_of, "codes:", len(codes), flush=True)

    total = 0
    for position, code in enumerate(sorted(codes)):
        payload: list[dict] = []
        with connect(app.db) as conn:
            series_by_metric = {
                metric: fetch_series(conn, code, metric, CALC_SRC_PINGAN, None, as_of)
                for metric in PERCENTILE_METRIC_ORDER
            }
        for metric, series in series_by_metric.items():
            if not series:
                continue
            for window_key in PERCENTILE_WINDOW_ORDER:
                stats = summarize(window_slice(series, as_of, window_key), min_sample_for(window_key))
                payload.append({
                    "index_code": code,
                    "as_of_date": as_of,
                    "metric": metric,
                    "window_key": window_key,
                    "calc_src": CALC_SRC_PINGAN,
                    "pct": stats["pct"],
                    "mean": stats["mean"],
                    "sd": stats["sd"],
                    "p20": stats["p20"],
                    "p50": stats["p50"],
                    "p80": stats["p80"],
                    "min_value": stats["min"],
                    "max_value": stats["max"],
                    "sample_size": stats["sample_size"],
                })
        if payload:
            with connect(app.db) as conn:
                conn.autocommit = False
                total += upsert_percentiles(conn, payload)
                conn.commit()
        if (position + 1) % 50 == 0:
            print("percentiles %d/%d rows=%d" % (position + 1, len(codes), total), flush=True)
    print("percentiles done rows:", total, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
