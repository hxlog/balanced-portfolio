# -*- coding: utf-8 -*-
"""幂等 seed「A 股核心资产 12 只（示例）」篮子 -> bp_basket.is_demo = TRUE。

需求（2026-11-27 全站整改 P2）：/dashboard 一篮子模式需要一个所有人（含匿名）可读、
登录用户可复制、仅管理员可编辑的示例篮子。数据源统一为 bp_etl 的 A 股全量行情
（source=etl_a_stock，回测主口径 hfq 后复权，2020-11 起有数据）。

- 方法/参数：risk_parity + 默认参数（lookback_days=156 / rebalance_band=0.05 / risk_free=0）；
- latest_result 由服务端重算生成（复用 bp_api.basket.build_latest_result，与
  POST /api/baskets/{id}/recompute 同一实现）——默认执行，--no-recompute 可跳过，
  绝不会写入伪造指标；
- 幂等：按 (is_demo=TRUE, name) 查找，存在则更新定义（可重复执行，不产生重复行）。

前置：先执行 ddl/78_basket_demo.sql（脚本会检测 is_demo 列，缺失时给出明确报错）。

用法：
    python scripts/seed_demo_basket.py                     # seed + 服务端重算 latest_result
    python scripts/seed_demo_basket.py --no-recompute      # 只 seed（稍后 admin 调 recompute）
    python scripts/seed_demo_basket.py --dry-run           # 只打印定义/现状，不写库
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bp_ingest.config import load_config  # noqa: E402  （import 时加载 .env）
from bp_ingest.db import connect  # noqa: E402

try:  # 重定向 stdout 时 reconfigure 可能不可用
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DEMO_BASKET_NAME = "A股核心资产 12 只（示例）"
DEMO_BASKET_DESCRIPTION = (
    "12 只 A 股核心资产（后复权），风险平价默认参数；示例只读，登录后可复制为自己的篮子编辑。"
)
DEMO_BASKET_METHOD = "risk_parity"
DEMO_BASKET_DISPLAY_ORDER = 0
DEMO_BASKET_PARAMS: dict[str, Any] = {
    "lookback_days": 156,
    "rebalance_band": 0.05,
    "risk_free": 0.0,
}
# (symbol, source, display_name)；source 固定 etl_a_stock（bp_etl A 股全量，回测口径 hfq）
DEMO_BASKET_ASSETS: tuple[tuple[str, str, str], ...] = (
    ("600519", "etl_a_stock", "贵州茅台"),
    ("300750", "etl_a_stock", "宁德时代"),
    ("600036", "etl_a_stock", "招商银行"),
    ("601318", "etl_a_stock", "中国平安"),
    ("000858", "etl_a_stock", "五粮液"),
    ("000333", "etl_a_stock", "美的集团"),
    ("600900", "etl_a_stock", "长江电力"),
    ("601899", "etl_a_stock", "紫金矿业"),
    ("002594", "etl_a_stock", "比亚迪"),
    ("600276", "etl_a_stock", "恒瑞医药"),
    ("601012", "etl_a_stock", "隆基绿能"),
    ("603288", "etl_a_stock", "海天味业"),
)

_ASSET_SQL = (
    "INSERT INTO bp_basket (owner_user_id, name, description, method, assets, params,"
    " latest_result, is_demo, display_order)"
    " VALUES (NULL, %(name)s, %(description)s, %(method)s, %(assets)s::jsonb,"
    " %(params)s::jsonb, NULL, TRUE, %(display_order)s)"
    " RETURNING basket_id"
)
_UPDATE_SQL = (
    "UPDATE bp_basket SET description = %(description)s, method = %(method)s,"
    " assets = %(assets)s::jsonb, params = %(params)s::jsonb,"
    " display_order = %(display_order)s, updated_at = now()"
    " WHERE basket_id = %(basket_id)s"
)


def demo_definition() -> dict[str, Any]:
    """示例篮子定义（纯常量，便于测试与人工核对）。"""
    return {
        "name": DEMO_BASKET_NAME,
        "description": DEMO_BASKET_DESCRIPTION,
        "method": DEMO_BASKET_METHOD,
        "display_order": DEMO_BASKET_DISPLAY_ORDER,
        "params": dict(DEMO_BASKET_PARAMS),
        "assets": [
            {"symbol": symbol, "source": source, "name": name}
            for symbol, source, name in DEMO_BASKET_ASSETS
        ],
    }


def _has_demo_columns(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'bp_basket' AND column_name IN ('is_demo', 'display_order')"
        )
        return len(cur.fetchall()) >= 2


def verify_demo_assets(conn) -> list[str]:
    """校验 12 只资产都在 bp_index_config（source=etl_a_stock，未软删）；返回缺失列表。"""
    symbols = [symbol for symbol, _source, _name in DEMO_BASKET_ASSETS]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM bp_index_config"
            " WHERE source = 'etl_a_stock' AND is_deleted = 0 AND symbol = ANY(%s)",
            (symbols,),
        )
        found = {row[0] for row in cur.fetchall()}
    return [symbol for symbol in symbols if symbol not in found]


def ensure_demo_basket(conn) -> dict[str, Any]:
    """幂等写入示例篮子（先查后插/更新）；调用方负责 commit。返回 {basket_id, created}。"""
    if not _has_demo_columns(conn):
        raise RuntimeError(
            "bp_basket 缺少 is_demo/display_order 列，请先执行 ddl/78_basket_demo.sql"
        )
    missing = verify_demo_assets(conn)
    if missing:
        raise RuntimeError(
            "示例资产未在 bp_index_config(etl_a_stock) 中找到: " + ", ".join(missing)
        )
    definition = demo_definition()
    assets = [
        {"symbol": item["symbol"], "source": item["source"]}
        for item in definition["assets"]
    ]
    payload = {
        "name": definition["name"],
        "description": definition["description"],
        "method": definition["method"],
        "display_order": definition["display_order"],
        "assets": json.dumps(assets, ensure_ascii=False),
        "params": json.dumps(definition["params"], ensure_ascii=False),
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT basket_id FROM bp_basket"
            " WHERE is_demo = TRUE AND name = %s ORDER BY basket_id LIMIT 1",
            (definition["name"],),
        )
        row = cur.fetchone()
        if row is not None:
            payload["basket_id"] = int(row[0])
            cur.execute(_UPDATE_SQL, payload)
            return {"basket_id": int(row[0]), "created": False}
        cur.execute(_ASSET_SQL, payload)
        new_id = int(cur.fetchone()[0])
    return {"basket_id": new_id, "created": True}


def recompute_demo_basket(conn, basket_id: int) -> dict[str, Any]:
    """服务端重算 latest_result（复用 API 同一实现；失败抛异常、不写库）。"""
    # 延迟导入：--no-recompute 场景不需要加载 bp_api 依赖（BP_JWT_SECRET 等）
    from psycopg.types.json import Jsonb  # noqa: PLC0415

    from bp_api.basket import build_latest_result  # noqa: PLC0415
    from bp_api.repositories import _json_safe, load_price_panel  # noqa: PLC0415

    with conn.cursor() as cur:
        cur.execute(
            "SELECT method, assets, params FROM bp_basket WHERE basket_id = %s",
            (basket_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"篮子不存在: {basket_id}")
    method, raw_assets, raw_params = row
    pairs = [
        (str(item["symbol"]), str(item["source"]))
        for item in (raw_assets or [])
        if isinstance(item, dict) and item.get("symbol") and item.get("source")
    ]
    if not pairs:
        raise RuntimeError("篮子没有有效资产")
    params = raw_params if isinstance(raw_params, dict) else {}

    def _int(key: str, default: int) -> int:
        try:
            return max(2, int(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default

    try:
        from bp_api.settings import load_settings  # noqa: PLC0415

        settings = load_settings()
        trading_days = settings.trading_days
        min_window = settings.min_window
    except Exception:  # noqa: BLE001 - 无 JWT 配置的纯 seed 环境退回默认口径
        trading_days, min_window = 244, 60

    panel = load_price_panel(conn, pairs)
    summary = build_latest_result(
        panel,
        method=str(method),
        lookback_days=_int("lookback_days", 156),
        rebalance_band=min(1.0, max(0.0, _float("rebalance_band", 0.05))),
        risk_free=_float("risk_free", 0.0),
        risk_budget=params.get("risk_budget") if isinstance(params.get("risk_budget"), dict) else None,
        trading_days=trading_days,
        min_window=min_window,
    )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_basket SET latest_result = %s::jsonb, updated_at = now()"
            " WHERE basket_id = %s",
            (Jsonb(_json_safe(summary)), basket_id),
        )
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-recompute", action="store_true", help="只 seed，不生成 latest_result")
    parser.add_argument("--dry-run", action="store_true", help="只打印定义/现状，不写库")
    args = parser.parse_args(argv)

    definition = demo_definition()
    print(
        "demo basket: {name} assets={n} method={method} params={params}".format(
            name=definition["name"],
            n=len(definition["assets"]),
            method=definition["method"],
            params=definition["params"],
        ),
        flush=True,
    )
    cfg = load_config()
    with connect(cfg.db) as conn:
        if args.dry_run:
            if not _has_demo_columns(conn):
                print("dry-run: bp_basket 缺少 is_demo/display_order 列（需先跑 ddl/78）", flush=True)
                return 2
            missing = verify_demo_assets(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT basket_id, name FROM bp_basket WHERE is_demo = TRUE ORDER BY display_order NULLS LAST, basket_id"
                )
                existing = cur.fetchall()
            print(f"dry-run: missing_assets={missing} existing_demo={existing}", flush=True)
            return 0
        result = ensure_demo_basket(conn)
        conn.commit()
        print(
            "seed {state}: basket_id={bid}".format(
                state="created" if result["created"] else "updated",
                bid=result["basket_id"],
            ),
            flush=True,
        )
        if args.no_recompute:
            print(
                "latest_result skipped (--no-recompute)；稍后可让管理员调用"
                " POST /api/baskets/{bid}/recompute".format(bid=result["basket_id"]),
                flush=True,
            )
            return 0
        summary = recompute_demo_basket(conn, result["basket_id"])
        conn.commit()
        print(
            "recomputed: as_of={as_of} effective_start={start} ann_return={ar} "
            "vol={vol} mdd={mdd} sharpe={sharpe} obs={n}".format(
                as_of=summary.get("as_of"),
                start=summary.get("effective_start"),
                ar=summary.get("annualized_return"),
                vol=summary.get("annualized_vol"),
                mdd=summary.get("max_drawdown"),
                sharpe=summary.get("sharpe"),
                n=summary.get("n_obs"),
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
