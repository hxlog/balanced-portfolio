"""回填基金全字段：
1) 平安 queryOnsiteFundInfoList 全字段 → bp_fund_master(manager/fund_type/fund_scale) + bp_fund_performance(规模/各期收益)
2) 天天基金 f10 → bp_fund_master(management_fee/custody_fee/established_date)

用法：
    .venv/bin/python scripts/backfill_fund_data.py --pingan
    .venv/bin/python scripts/backfill_fund_data.py --fees
    .venv/bin/python scripts/backfill_fund_data.py --all
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

import requests

from bp_api.repositories_valuation import upsert_fund_master, upsert_fund_performance
from bp_ingest.config import load_config, setup_logging
from bp_ingest.crypto_futures import _ensure_session  # 复用硬化会话
from bp_ingest.db import connect
from bp_ingest.http_session import install_hardened_session
from bp_ingest.valuation_pingan import fetch_tracker_funds

PINGAN_BATCH = 60


def _float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _nav(raw):
    position = raw.get("positionDTO")
    if not isinstance(position, dict):
        return {}
    nav = position.get("newFundDrFundnv")
    return nav if isinstance(nav, dict) else {}


def _manager(raw):
    position = raw.get("positionDTO")
    if not isinstance(position, dict):
        return None
    sessions = position.get("drFmpfmanceDTOS")
    if isinstance(sessions, list) and sessions:
        first = sessions[0]
        if isinstance(first, dict):
            return first.get("manager")
    return None


def backfill_pingan() -> int:
    app = load_config()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fund_code FROM bp_index_tracker_fund ORDER BY fund_code")
        codes = [row[0] for row in cur.fetchall()]
    print("fund codes:", len(codes), flush=True)

    today = date.today()
    master_rows: list[dict] = []
    perf_rows: list[dict] = []
    for start in range(0, len(codes), PINGAN_BATCH):
        batch = codes[start:start + PINGAN_BATCH]
        try:
            raw_rows = fetch_tracker_funds(batch)
        except Exception as exc:  # noqa: BLE001
            print("batch fail", batch[0], type(exc).__name__, str(exc)[:120], flush=True)
            time.sleep(1)
            continue
        for raw in raw_rows:
            code = raw.get("fundCode")
            if not code:
                continue
            nav = _nav(raw)
            manager = _manager(raw)
            position = raw.get("positionDTO") if isinstance(raw.get("positionDTO"), dict) else {}
            aum = _float(position.get("fnvsum"))
            master_rows.append({
                "fund_code": code,
                "name": raw.get("ommName") or code,
                "company_name": raw.get("companyName"),
                "risk_grade": raw.get("riskGrade"),
                "manager": manager,
                "fund_type": raw.get("investmentType") or raw.get("fundCSRCType"),
                "management_fee": None,
                "custody_fee": None,
                "established_date": None,
                "fund_scale": aum,
            })
            perf_rows.append({
                "fund_code": code,
                "as_of": today,
                "aum": aum,
                "ret_1m": _float(nav.get("nvgr4w")),
                "ret_3m": _float(nav.get("nvgr13w")),
                "ret_6m": _float(nav.get("nvgr26w")),
                "ret_12m": _float(nav.get("nvgr52w")),
                "ret_2y": _float(nav.get("yield2ya")),
                "ret_3y": _float(nav.get("yield3ya")),
                "ret_5y": _float(nav.get("yield5ya")),
                "ytd": _float(nav.get("nvgrty")) or _float(nav.get("yieldly")),
                "manager": manager,
            })
        print("pingan progress %d/%d" % (min(start + PINGAN_BATCH, len(codes)), len(codes)), flush=True)
        time.sleep(0.2)

    with connect(app.db) as conn:
        conn.autocommit = False
        upsert_fund_master(conn, master_rows)
        upsert_fund_performance(conn, perf_rows)
        conn.commit()
    print("pingan done master=%d perf=%d" % (len(master_rows), len(perf_rows)), flush=True)
    return 0


FUND_F10 = "https://fundf10.eastmoney.com/jbgk_{code}.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _strip_html(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", html)


def _find_pct(text: str, label: str):
    index = text.find(label)
    if index < 0:
        return None
    window = text[index:index + 160]
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", window)
    return float(match.group(1)) if match else None


def _find_scale(text: str):
    index = text.find("净资产规模")
    if index < 0:
        return None
    window = text[index:index + 80]
    match = re.search(r"([0-9][0-9,]*\.?[0-9]*)\s*亿", window)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "")) * 1e8
    except ValueError:
        return None


def _find_date(text: str, label: str):
    index = text.find(label)
    if index < 0:
        return None
    window = text[index:index + 160]
    match = re.search(r"(\d{4}-\d{2}-\d{2})", window)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def backfill_fees() -> int:
    install_hardened_session()
    app = load_config()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT fund_code FROM bp_fund_master"
            " WHERE management_fee IS NULL OR established_date IS NULL"
            " ORDER BY fund_scale DESC NULLS LAST LIMIT 2000",
        )
        codes = [row[0] for row in cur.fetchall()]
    print("fee targets:", len(codes), flush=True)
    ok = 0
    for index, code in enumerate(codes):
        f10_code = re.sub(r"^(SH|SZ|OF|CN)", "", code)
        try:
            response = requests.get(FUND_F10.format(code=f10_code), headers=HEADERS, timeout=20)
            if response.status_code != 200:
                continue
            text = _strip_html(response.text)
            fee = _find_pct(text, "管理费率")
            custody = _find_pct(text, "托管费率")
            established = _find_date(text, "成立日期")
            scale = _find_scale(text)
            if fee is None and custody is None and established is None and scale is None:
                continue
            with connect(app.db) as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE bp_fund_master SET management_fee = COALESCE(%s, management_fee),"
                    " custody_fee = COALESCE(%s, custody_fee),"
                    " established_date = COALESCE(%s, established_date),"
                    " fund_scale = COALESCE(%s, fund_scale),"
                    " updated_at = now() WHERE fund_code = %s",
                    (fee, custody, established, scale, code),
                )
                conn.commit()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print("fee fail", code, type(exc).__name__, str(exc)[:100], flush=True)
        if (index + 1) % 50 == 0:
            print("fees progress %d/%d ok=%d" % (index + 1, len(codes), ok), flush=True)
        time.sleep(0.15)
    print("fees done ok=%d" % ok, flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pingan", action="store_true")
    parser.add_argument("--fees", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    setup_logging()
    if not (args.pingan or args.fees or args.all):
        parser.print_help()
        return 1
    if args.pingan or args.all:
        backfill_pingan()
    if args.fees or args.all:
        backfill_fees()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
