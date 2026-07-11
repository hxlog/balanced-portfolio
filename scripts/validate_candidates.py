"""akshare 枚举校验: 过滤候选品种, 输出 validated_candidates.json。

用法:
  python scripts/validate_candidates.py candidates.json > validated_candidates.json

校验策略:
  - ETF (etf_em): etf_code ∈ fund_etf_spot_em() 代码集
  - A股指数 (cn_index_em): underlying_index_code ∈ index_stock_info() 中证目录;
    不在目录的(上证/深证交易所代码)用 index_zh_a_hist 直探非空
  - 港股指数 (hk_index_em): stock_hk_index_daily_em 直探非空
  - 全球指数 (global_index_em): 名称 ∈ index_global_spot_em() 名称集; 不在则直探
  - 商品主力 (cmdty_main_sina): 代码 ∈ futures_display_main_sina() symbol 集
  - 国债期限 (bond_csi_treasury): bond_treasury_index_cbond(indicator='财富', period=X) 直探非空

商品主力与债券期限为确定性枚举(见方案), 不依赖输入 candidates.json, 脚本内置生成。
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import date, timedelta

warnings.filterwarnings("ignore")

from bp_ingest.http_session import install_hardened_session

install_hardened_session()

import akshare as ak
import pandas as pd  # noqa: E402

TODAY = date.today()
PROBE_START = (TODAY - timedelta(days=120)).strftime("%Y%m%d")
PROBE_END = TODAY.strftime("%Y%m%d")


# ----------------------------------------------------------------------
# 成员集(一次性加载)
# ----------------------------------------------------------------------

def _col(df, *names):
    for n in names:
        if n in df.columns:
            return df[n]
    return None


print("加载 akshare 枚举集...", file=sys.stderr)

# ETF 代码集
etf_set: set[str] = set()
etf_name_map: dict[str, str] = {}
try:
    df = ak.fund_etf_spot_em()
    codes = _col(df, "代码")
    names = _col(df, "名称")
    if codes is not None:
        for i, c in enumerate(codes.astype(str)):
            cc = c.strip().zfill(6)
            etf_set.add(cc)
            if names is not None:
                etf_name_map[cc] = str(names.iloc[i])
    print(f"  ETF: {len(etf_set)} 只", file=sys.stderr)
except Exception as e:
    print(f"  fund_etf_spot_em 失败: {str(e)[:80]}", file=sys.stderr)

# 商品主力代码集
cmdty_set: set[str] = set()
cmdty_name_map: dict[str, str] = {}
try:
    df = ak.futures_display_main_sina()
    for _, r in df.iterrows():
        sym = str(r.get("symbol", "")).strip()
        nm = str(r.get("name", "")).strip()
        if sym:
            cmdty_set.add(sym)
            cmdty_name_map[sym] = nm
    print(f"  商品主力: {len(cmdty_set)} 个", file=sys.stderr)
except Exception as e:
    print(f"  futures_display_main_sina 失败: {str(e)[:80]}", file=sys.stderr)

# 中证指数目录
csi_set: set[str] = set()
try:
    df = ak.index_stock_info()
    col = _col(df, "index_code", "display_code")
    if col is not None:
        csi_set = set(str(c).strip() for c in col.astype(str))
    print(f"  中证指数: {len(csi_set)} 个", file=sys.stderr)
except Exception as e:
    print(f"  index_stock_info 失败: {str(e)[:80]}", file=sys.stderr)

# 全球指数名称集
global_set: set[str] = set()
try:
    df = ak.index_global_spot_em()
    names = _col(df, "名称")
    if names is not None:
        global_set = set(str(n).strip() for n in names.astype(str))
    print(f"  全球指数: {len(global_set)} 个", file=sys.stderr)
except Exception as e:
    print(f"  index_global_spot_em 失败: {str(e)[:80]}", file=sys.stderr)


# ----------------------------------------------------------------------
# 逐代码直探(反爬重试)
# ----------------------------------------------------------------------

def _retry(fn, tries=3, delay=2.0):
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(delay)
    print(f"    直探失败: {str(last)[:80]}", file=sys.stderr)
    return None


def probe_cn_index(code: str) -> bool:
    if code in csi_set:
        return True
    # 上证/深证交易所代码: 直探 index_zh_a_hist
    df = _retry(lambda: ak.index_zh_a_hist(symbol=code, period="daily",
                                           start_date=PROBE_START, end_date=PROBE_END))
    if df is None:
        return True  # 连接报错→宽容保留(ingest 阶段再兜底)
    return not df.empty  # 空 df = 代码无效→剔除


def probe_hk_index(code: str) -> bool:
    df = _retry(lambda: ak.stock_hk_index_daily_em(symbol=code))
    if df is None:
        return True  # 连接报错→宽容保留
    return not df.empty


def probe_global(name: str) -> bool:
    if name in global_set:
        return True
    df = _retry(lambda: ak.index_global_hist_em(symbol=name))
    if df is None:
        return True  # 连接报错→宽容保留
    return not df.empty


def probe_bond_tenor(period: str) -> bool:
    df = _retry(lambda: ak.bond_treasury_index_cbond(indicator="财富", period=period))
    if df is None:
        return True  # 连接报错→宽容保留
    return not df.empty


# ----------------------------------------------------------------------
# 候选校验
# ----------------------------------------------------------------------

def validate_candidate(c: dict) -> tuple[bool, str]:
    cat = c.get("category")
    src = c.get("source_suggested", "")
    etf_code = (c.get("etf_code") or "").strip()
    idx_code = (c.get("underlying_index_code") or "").strip()
    idx_name = (c.get("underlying_index_name") or "").strip()

    if cat == "etf":
        if not etf_code:
            return False, "no etf_code"
        cc = etf_code.zfill(6)
        if cc in etf_set:
            return True, etf_name_map.get(cc, "")
        # 直探 ETF 历史(防 listing 漏); 连接报错→宽容保留
        df = _retry(lambda: ak.fund_etf_hist_em(symbol=cc, period="daily",
                                                start_date=PROBE_START, end_date=PROBE_END,
                                                adjust="hfq"))
        if df is None:
            return True, f"etf {cc} probe-error-kept"
        if not df.empty:
            return True, ""
        return False, f"etf {cc} empty (not found)"

    if cat == "index":
        if src == "cn_index_em":
            if not idx_code:
                return False, "no index_code"
            return (probe_cn_index(idx_code), f"cn_index {idx_code}")
        if src == "hk_index_em":
            if not idx_code:
                return False, "no hk code"
            return (probe_hk_index(idx_code), f"hk_index {idx_code}")
        if src == "global_index_em":
            name = idx_name or idx_code
            return (probe_global(name), f"global {name}")
        return False, f"unknown index source {src}"

    # commodity / bond tenor 由内置列表生成, 不从 candidate 校验
    return False, "commodity/bond handled internally"


# ----------------------------------------------------------------------
# 内置确定性列表: 商品主力 + 债券期限
# ----------------------------------------------------------------------

# 商品主力(cmdty_main_sina): 代码 -> 名称
COMMODITY_CODES = {
    "AU0": "沪金主力", "AG0": "沪银主力", "AL0": "沪铝主力", "ZN0": "沪锌主力",
    "PB0": "沪铅主力", "NI0": "沪镍主力", "SN0": "沪锡主力", "RB0": "螺纹钢主力",
    "HC0": "热卷主力", "SS0": "不锈钢主力", "WR0": "线材主力", "FU0": "燃油主力",
    "BU0": "沥青主力", "RU0": "橡胶主力", "I0": "铁矿石主力", "J0": "焦炭主力",
    "JM0": "焦煤主力", "L0": "塑料主力", "PP0": "PP主力", "V0": "PVC主力",
    "A0": "豆一主力", "B0": "豆二主力", "Y0": "豆油主力", "P0": "棕榈油主力",
    "C0": "玉米主力", "CS0": "玉米淀粉主力", "JD0": "鸡蛋主力",
    "CF0": "棉花主力", "SR0": "白糖主力", "TA0": "PTA主力", "FG0": "玻璃主力",
    "SF0": "硅铁主力", "SM0": "锰硅主力", "RI0": "早籼稻主力", "OI0": "菜油主力",
    "CY0": "棉纱主力", "AP0": "苹果主力", "CJ0": "红枣主力", "SP0": "纸浆主力",
    "NR0": "20号胶主力", "LU0": "低硫燃油主力", "BC0": "国际铜主力",
    "SA0": "纯碱主力", "UR0": "尿素主力", "PF0": "短纤主力", "BR0": "丁二烯橡胶主力",
}

# 国债指数期限(bond_csi_treasury): 期限 -> 名称
BOND_TENORS = {
    "1Y": "中债-国债总财富(1年)指数", "2Y": "中债-国债总财富(2年)指数",
    "3Y": "中债-国债总财富(3年)指数", "5Y": "中债-国债总财富(5年)指数",
    "7Y": "中债-国债总财富(7年)指数",
    "0-1Y": "中债-国债总财富(0-1年)指数", "0-5Y": "中债-国债总财富(0-5年)指数",
    "0-7Y": "中债-国债总财富(0-7年)指数", "0-10Y": "中债-国债总财富(0-10年)指数",
    "0-15Y": "中债-国债总财富(0-15年)指数", "0-30Y": "中债-国债总财富(0-30年)指数",
    "1-3Y": "中债-国债总财富(1-3年)指数", "3-5Y": "中债-国债总财富(3-5年)指数",
    "5-7Y": "中债-国债总财富(5-7年)指数", "7-10Y": "中债-国债总财富(7-10年)指数",
}


def main():
    cands = []
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
        # 兼容 {candidates:[...]} 或 [...]
        if isinstance(data, dict):
            cands = data.get("candidates", [])
        else:
            cands = data
    print(f"输入候选: {len(cands)} 个", file=sys.stderr)

    out = []

    # 1) 校验输入候选(ETF + 指数)
    for c in cands:
        cat = c.get("category")
        if cat in ("commodity", "bond"):
            continue  # 内置生成
        ok, info = validate_candidate(c)
        if not ok:
            print(f"  DROP {cat} {c.get('etf_code') or c.get('underlying_index_code')}: {info}", file=sys.stderr)
            continue
        symbol = (c.get("etf_code") or c.get("underlying_index_code") or "").strip()
        if cat == "etf":
            symbol = symbol.zfill(6)
        elif cat == "index" and src == "global_index_em":
            symbol = idx_name or idx_code  # 全球指数 symbol = 中文名
        name = c.get("etf_name") or c.get("underlying_index_name") or info
        extra = {"adjust": "hfq"} if cat == "etf" else {}
        out.append({
            "symbol": symbol,
            "source": c.get("source_suggested"),
            "category": cat,
            "name": name,
            "extra_params": extra,
        })
        print(f"  OK   {cat} {symbol} {name}", file=sys.stderr)
        time.sleep(0.3)

    # 2) 商品主力(内置)
    print("校验商品主力...", file=sys.stderr)
    for code, name in COMMODITY_CODES.items():
        if code in cmdty_set:
            out.append({"symbol": code, "source": "cmdty_main_sina",
                        "category": "commodity", "name": name, "extra_params": {}})
        else:
            print(f"  DROP cmdty {code} ({name}): not in futures_display_main_sina", file=sys.stderr)

    # 3) 债券期限(内置, 直探)
    print("校验国债期限...", file=sys.stderr)
    for tenor, name in BOND_TENORS.items():
        if probe_bond_tenor(tenor):
            out.append({"symbol": tenor, "source": "bond_csi_treasury",
                        "category": "bond", "name": name,
                        "extra_params": {"indicator": "财富"}})
            print(f"  OK   bond {tenor}", file=sys.stderr)
        else:
            print(f"  DROP bond {tenor}: probe empty", file=sys.stderr)
        time.sleep(0.3)

    # 去重(同 symbol+source 只留一行)
    seen = set()
    deduped = []
    for r in out:
        k = (r["symbol"], r["source"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    print(f"\n最终: {len(deduped)} 个有效标的", file=sys.stderr)
    json.dump(deduped, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
