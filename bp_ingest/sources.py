"""akshare 数据源适配器注册表。

每个 source 对应一个 akshare 抓取函数, 负责:
  - 用 config 中存的原生 symbol 调用接口
  - 把返回列归一化为标准 schema
标准 schema 列(归一化后的 DataFrame):
  trade_date(date), open, high, low, close, volume, amount, turnover_rate, pct_change
缺失字段以 NaN/None 表示; close 必须存在。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, NoReturn, Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

STANDARD_COLUMNS = [
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "pct_change",
]


# ---------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------
def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


def _finalize(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """补齐标准列、规整类型、按日期过滤并排序。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[STANDARD_COLUMNS].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date

    for col in ["open", "high", "low", "close", "amount", "turnover_rate", "pct_change"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    df = df.dropna(subset=["trade_date", "close"])
    df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def _rename(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    present = {k: v for k, v in mapping.items() if k in df.columns}
    return df.rename(columns=present)


def _is_conn_error(exc: Exception) -> bool:
    """连接级错误(反爬掐断/超时)——应向上抛以触发 fetch_with_fallback 的 em→sina 降级。"""
    name = type(exc).__name__
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return any(
        s in name
        for s in (
            "ConnectionError", "RemoteDisconnected", "Timeout",
            "ConnectionReset", "Chunked", "SSLError",
        )
    )


def _raise_em_conn(msg: str) -> NoReturn:
    """抛出 requests.ConnectionError, 命中 fetch_with_fallback 的降级分支。"""
    import requests as _requests
    raise _requests.exceptions.ConnectionError(msg)


def _push2his_klines(
    secid: str, *, ut: str, fields2: str, beg: str, end: str,
    fqt: str = "0", klt: str = "101", lmt: str = "50000",
    forcect: bool = False, iscca: bool = False,
) -> list[str]:
    """直连东方财富 push2his K 线端点, 返回 klines 原始字符串列表(每行逗号分隔)。

    经 hardened session 的 monkeypatched requests.get(自动 chrome120 指纹 + 按 host 注入 BP_EM_COOKIE)。
    - 连接级错误(掐断/超时): **向上抛**, 由 fetch_with_fallback 降级 sina。
    - 成功但空 data / 非 JSON: 返回 [](该 secid 无 K 线或响应异常)。
    """
    import requests as _requests
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params: dict[str, str] = {
        "secid": secid, "ut": ut, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": fields2, "klt": klt, "fqt": fqt, "beg": beg, "end": end, "lmt": lmt,
    }
    if forcect:
        params["forcect"] = "1"
    if iscca:
        params["iscca"] = "1"
    try:
        r = _requests.get(url, params=params, timeout=20)
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        if _is_conn_error(exc):
            raise
        return []
    return (data.get("data") or {}).get("klines") or []


# 中文 OHLCV 列(index_zh_a_hist / fund_etf_hist_em)
_CN_OHLCV_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "涨跌幅": "pct_change",
    "换手率": "turnover_rate",
}

# 期货主力连续合约列(futures_main_sina)
_FUT_MAIN_MAP = {
    "日期": "trade_date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "成交量": "volume",
}


# ---------------------------------------------------------------------
# 各 source 的抓取 + 归一化函数
# 签名: (symbol, start, end, extra) -> 标准 DataFrame
# ---------------------------------------------------------------------
_INDEX_SECID_CACHE: dict[str, str] = {}

# cn_index K 线 11 字段(f51..f61): 日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率
_CN_INDEX_KLINE_COLS = [
    "日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额",
    "振幅", "涨跌幅", "涨跌额", "换手率",
]

# 显式覆盖(启发式搞不定的个别代码); 绝大多数走 _static_cn_index_secid 规则。
_CN_INDEX_SECID_STATIC: dict[str, str] = {
    # 例: "XXXXXX": "90.XXXXXX",
}


def _static_cn_index_secid(symbol: str) -> Optional[str]:
    """按代码形态推断 EM secid, 避免前缀探测误命中深市个股(0.000xxx)。

    约定: 1=上证指数, 0=深证指数, 90=中证 CSI, 2=国证等。
    """
    s = symbol.strip().upper()
    if s in _CN_INDEX_SECID_STATIC:
        return _CN_INDEX_SECID_STATIC[s]
    if s.startswith("399"):
        return f"0.{s}"
    if s.startswith(("930", "931", "932")) or s.startswith("H30"):
        return f"90.{s}"
    if s.startswith("98"):  # 国证 980xxx
        return f"2.{s}"
    if s.startswith(("000", "001")):
        return f"1.{s}"
    return None


def _resolve_cn_index_secid(symbol: str) -> Optional[str]:
    """解析 cn_index_em 的 secid。

    顺序: 进程缓存 → 静态规则 → EM 代码映射表(掐断则跳过) → 前缀探测。
    前缀探测遇连接级错误立即上抛(触发 sina 降级); 全部空响应则返回 None。
    """
    cached = _INDEX_SECID_CACHE.get(symbol)
    if cached:
        return cached

    static = _static_cn_index_secid(symbol)
    if static:
        _INDEX_SECID_CACHE[symbol] = static
        return static

    # best-effort 代码映射表(掐断则跳过)
    try:
        cm = ak.index_code_id_map_em()
        if symbol in cm:
            secid = f"{cm[symbol]}.{symbol}"
            _INDEX_SECID_CACHE[symbol] = secid
            return secid
    except Exception:  # noqa: BLE001
        pass

    # 前缀探测(静态未覆盖的冷门代码); 含 90(CSI)。不优先试 0, 降低 000xxx 误命中个股风险。
    for pre in ("1", "90", "2", "47", "0"):
        cand = f"{pre}.{symbol}"
        try:
            kl = _push2his_klines(
                cand, ut="7eea3edcaed734bea9cbfc24409ed989",
                fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                fqt="0", beg="0", end="20500000", lmt="5",
            )
        except Exception as exc:  # noqa: BLE001
            if _is_conn_error(exc):
                raise
            continue
        if kl:
            _INDEX_SECID_CACHE[symbol] = cand
            return cand
    return None


def _fetch_cn_index_em(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """直连 push2his 拉 A 股/中证指数 K 线。

    绕过 akshare index_zh_a_hist 内部依赖的被掐断 clist 端点(index_code_id_map_em),
    secid 由 _resolve_cn_index_secid 解析(静态规则 + 映射表 + 前缀探测)。
    连接掐断 / secid 无法解析时抛 ConnectionError → fetch_with_fallback 降级 cn_index_sina。
    """
    secid = _resolve_cn_index_secid(symbol)
    if secid is None:
        logger.warning(
            "cn_index_em: 无法解析 %s 的 secid(代码映射表掐断且前缀探测无命中), 触发 sina 降级",
            symbol,
        )
        _raise_em_conn(f"cn_index_em: cannot resolve secid for {symbol}")
    kl = _push2his_klines(
        secid, ut="7eea3edcaed734bea9cbfc24409ed989",
        fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        fqt="0", beg=_fmt(start), end=_fmt(end),
    )
    if not kl:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    rows = [item.split(",") for item in kl]
    rows = [r + [""] * (len(_CN_INDEX_KLINE_COLS) - len(r)) for r in rows]  # 防御: 补齐不足 11 列
    df = pd.DataFrame(rows, columns=_CN_INDEX_KLINE_COLS)
    return _finalize(_rename(df, _CN_OHLCV_MAP), start, end)


def _cn_index_prefix(symbol: str) -> str:
    """A 股指数代码自动加市场前缀(sh/sz), 兼容已带前缀。
    stock_zh_index_daily / _tx / _em 要求 sh000300 / sz399552 形式; 管理员只输 000510 时补前缀。
    """
    s = symbol.strip()
    h = s.lower()
    if h.startswith(("sh", "sz", "csi", "bj")):
        return s
    if s.startswith("399") or s.startswith("159") or s.startswith("131"):
        return f"sz{s}"
    if s.startswith("000") or s.startswith("001"):
        return f"sh{s}"
    return s


def _fetch_cn_index_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    try:
        raw = ak.stock_zh_index_daily(symbol=_cn_index_prefix(symbol))  # 全量
    except Exception:  # noqa: BLE001 - 空响应/不支持时 akshare 抛 KeyError: 'date', 降级空表
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    return _finalize(_rename(raw, {"date": "trade_date"}), start, end)


def _fetch_cn_index_tx(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    sym = _cn_index_prefix(symbol)
    raw = ak.stock_zh_index_daily_tx(
        symbol=sym, start_date=_fmt(start), end_date=_fmt(end)
    )
    # tx 返回 date,open,close,high,low,amount(单位手) -> 作为 volume
    df = _rename(raw, {"date": "trade_date", "amount": "volume"})
    return _finalize(df, start, end)


def _fetch_cn_index_em_px(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    try:
        raw = ak.stock_zh_index_daily_em(
            symbol=_cn_index_prefix(symbol), start_date=_fmt(start), end_date=_fmt(end)
        )
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    return _finalize(_rename(raw, {"date": "trade_date"}), start, end)


_HK_SECID_CACHE: dict[str, str] = {}

# HK K 线 14 字段(f51..f64): date/open/latest/high/low + 9 个占位
_HK_INDEX_KLINE_COLS = ["date", "open", "latest", "high", "low"] + [f"_c{i}" for i in range(9)]


def _resolve_hk_index_secid(symbol: str) -> Optional[str]:
    """解析 hk_index_em 的 secid。

    优先 EM 代码映射表(_symbol_code_dict, lru_cached, 调 stock_hk_index_spot_em; 掐断则跳过);
    兜底按 [100, 124, 116] 前缀探测 push2his——100=HSAHP, 124=HSHCI/HSIII/HSISC。
    连接级错误立即上抛以触发 sina 降级。
    """
    cached = _HK_SECID_CACHE.get(symbol)
    if cached:
        return cached
    # 1. best-effort 代码映射表(掐断则跳过)
    try:
        from akshare.index.index_stock_hk import _symbol_code_dict
        d = _symbol_code_dict()
        if symbol in d:
            secid = f"{d[symbol]}.{symbol}"
            _HK_SECID_CACHE[symbol] = secid
            return secid
    except Exception:  # noqa: BLE001
        pass
    # 2. 前缀探测 push2his(lmt=5 轻量)
    for pre in ("100", "124", "116"):
        cand = f"{pre}.{symbol}"
        try:
            kl = _push2his_klines(
                cand, ut="f057cbcbce2a86e2866ab8877db1d059",
                fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64",
                fqt="1", forcect=True, iscca=True, beg="0", end="20500000", lmt="5",
            )
        except Exception as exc:  # noqa: BLE001
            if _is_conn_error(exc):
                raise
            continue
        if kl:
            _HK_SECID_CACHE[symbol] = cand
            return cand
    return None


def _fetch_hk_index_em(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """直连 push2his 拉港股指数 K 线。

    绕过 akshare stock_hk_index_daily_em 内部依赖的被掐断 clist 端点(stock_hk_index_spot_em)。
    连接掐断 / secid 无法解析时抛 ConnectionError → fetch_with_fallback 降级 hk_index_sina。
    """
    secid = _resolve_hk_index_secid(symbol)
    if secid is None:
        logger.warning(
            "hk_index_em: 无法解析 %s 的 secid(代码映射表掐断且前缀探测无命中), 触发 sina 降级",
            symbol,
        )
        _raise_em_conn(f"hk_index_em: cannot resolve secid for {symbol}")
    kl = _push2his_klines(
        secid, ut="f057cbcbce2a86e2866ab8877db1d059",
        fields2="f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64",
        fqt="1", forcect=True, iscca=True, beg=_fmt(start), end=_fmt(end),
    )
    if not kl:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    rows = [item.split(",") for item in kl]
    rows = [r + [""] * (len(_HK_INDEX_KLINE_COLS) - len(r)) for r in rows]
    df = pd.DataFrame(rows, columns=_HK_INDEX_KLINE_COLS)
    df = df[["date", "open", "high", "low", "latest"]]
    return _finalize(_rename(df, {"date": "trade_date", "latest": "close"}), start, end)


def _fetch_hk_index_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    try:
        raw = ak.stock_hk_index_daily_sina(symbol=symbol)  # 全量
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    return _finalize(_rename(raw, {"date": "trade_date"}), start, end)


def _fetch_global_index_em(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    raw = ak.index_global_hist_em(symbol=symbol)  # 全量, 中文列
    df = _rename(
        raw,
        {"日期": "trade_date", "今开": "open", "最新价": "close", "最高": "high", "最低": "low"},
    )
    return _finalize(df, start, end)


def _fetch_global_index_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    try:
        raw = ak.index_global_hist_sina(symbol=symbol)  # 近1000条
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    return _finalize(_rename(raw, {"date": "trade_date"}), start, end)


def _fetch_cmdty_main_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """商品期货主力连续合约(新浪)。symbol 为合约代码, 如 M0/CU0/MA0。"""
    raw = ak.futures_main_sina(symbol=symbol, start_date=_fmt(start), end_date=_fmt(end))
    return _finalize(_rename(raw, _FUT_MAIN_MAP), start, end)


def _normalize_value_series(raw: pd.DataFrame) -> pd.DataFrame:
    """把 [date, value] 形态的指数序列归一化为标准列(value 作 close)。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["trade_date", "close"])
    df = raw.copy()
    date_col = next(
        (c for c in df.columns if c.lower() in ("date", "日期") or "date" in c.lower()),
        df.columns[0],
    )
    value_col = next(
        (c for c in df.columns if c != date_col and pd.api.types.is_numeric_dtype(df[c])),
        None,
    )
    if value_col is None:
        # 退而求其次: 取第一个非日期列
        value_col = next((c for c in df.columns if c != date_col), None)
    df = df.rename(columns={date_col: "trade_date", value_col: "close"})
    return df[["trade_date", "close"]]


def _fetch_bond_csi_treasury(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    indicator = extra.get("indicator", "财富")
    raw = ak.bond_treasury_index_cbond(indicator=indicator, period=symbol)
    return _finalize(_normalize_value_series(raw), start, end)


def _fetch_etf_em(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    adjust = extra.get("adjust", "hfq")
    raw = ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=_fmt(start),
        end_date=_fmt(end),
        adjust=adjust,
    )
    return _finalize(_rename(raw, _CN_OHLCV_MAP), start, end)


def _etf_sina_symbol(symbol: str) -> str:
    """新浪 ETF 接口需带市场前缀; 纯代码按交易所自动加 sh/sz。"""
    s = symbol.strip().lower()
    if s.startswith(("sh", "sz")):
        return s
    if s.startswith("5"):  # 51/56/58... 上交所 ETF
        return f"sh{s}"
    if s.startswith("1"):  # 15/16/18... 深交所 ETF
        return f"sz{s}"
    return f"sh{s}"        # 兜底沪市


def _fetch_etf_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """新浪 ETF 历史行情(全量), 列: date/open/high/low/close/volume。"""
    raw = ak.fund_etf_hist_sina(symbol=_etf_sina_symbol(symbol))
    return _finalize(_rename(raw, {"date": "trade_date"}), start, end)


# ---------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class SourceAdapter:
    code: str
    akshare_func: str
    supports_date_range: bool
    has_volume: bool
    provides_pct: bool  # 接口是否直接返回涨跌幅(否则脚本本地计算)
    fetch: Callable[[str, date, date, dict], pd.DataFrame]


SOURCES: dict[str, SourceAdapter] = {
    "cn_index_em": SourceAdapter(
        "cn_index_em", "index_zh_a_hist", True, True, True, _fetch_cn_index_em
    ),
    "cn_index_sina": SourceAdapter(
        "cn_index_sina", "stock_zh_index_daily", False, True, False, _fetch_cn_index_sina
    ),
    "cn_index_tx": SourceAdapter(
        "cn_index_tx", "stock_zh_index_daily_tx", True, True, False, _fetch_cn_index_tx
    ),
    "cn_index_em_px": SourceAdapter(
        "cn_index_em_px", "stock_zh_index_daily_em", True, True, False, _fetch_cn_index_em_px
    ),
    "hk_index_em": SourceAdapter(
        "hk_index_em", "stock_hk_index_daily_em", False, False, False, _fetch_hk_index_em
    ),
    "hk_index_sina": SourceAdapter(
        "hk_index_sina", "stock_hk_index_daily_sina", False, True, False, _fetch_hk_index_sina
    ),
    "global_index_em": SourceAdapter(
        "global_index_em", "index_global_hist_em", False, False, False, _fetch_global_index_em
    ),
    "global_index_sina": SourceAdapter(
        "global_index_sina", "index_global_hist_sina", False, True, False, _fetch_global_index_sina
    ),
    "cmdty_main_sina": SourceAdapter(
        "cmdty_main_sina", "futures_main_sina", True, True, False, _fetch_cmdty_main_sina
    ),
    "bond_csi_treasury": SourceAdapter(
        "bond_csi_treasury", "bond_treasury_index_cbond", False, False, False, _fetch_bond_csi_treasury
    ),
    "etf_em": SourceAdapter(
        "etf_em", "fund_etf_hist_em", True, True, True, _fetch_etf_em
    ),
    "etf_sina": SourceAdapter(
        "etf_sina", "fund_etf_hist_sina", False, True, False, _fetch_etf_sina
    ),
}


def get_adapter(source: str) -> SourceAdapter:
    if source not in SOURCES:
        raise KeyError(f"未知 source: {source}; 可用: {sorted(SOURCES)}")
    return SOURCES[source]


# 东方财富(em)源被反爬 IP 掐断时的等价降级源(em → sina/tx)。
# 仅在 em 源抛连接级错误(ConnectionError/RemoteDisconnected/Timeout)时降级;
# 降级后数据仍按原 source 落库, 对回测面板透明。
#
# 注意: etf_em 不在此映射中 —— ETF 必须用后复权(hfq)数据, 而 etf_sina 返回未复权价,
# 降级会污染 hfq 系列(混合复权/未复权价, 破坏滚动协方差/ERC 权重)。故 etf_em 拉取
# 失败时直接报错暂空, 由调度器重试, 绝不降级到 etf_sina。指数/HK/全球无复权概念,
# sina 与 em 同值, 降级无害, 保留。
EM_FALLBACK_SOURCE: dict[str, str] = {
    "cn_index_em": "cn_index_sina",
    "cn_index_em_px": "cn_index_tx",
    "hk_index_em": "hk_index_sina",
    "global_index_em": "global_index_sina",
}


def fetch_with_fallback(
    source: str, symbol: str, start: date, end: date, extra: dict | None = None
) -> pd.DataFrame:
    """优先用 source 拉取; 若 em 源被反爬掐断(连接级错误), 自动降级到等价 sina/tx 源。

    em 的 push2his/push2 主机基于 TLS 指纹(JA3)/IP 信誉掐断连接(RemoteDisconnected),
    curl_cffi(Chrome 指纹)可绕过部分端点(ETF), 仍被掐的端点(index_code_id_map 等)降级到 sina/tx。
    数据落库时仍用原 source 键, 回测面板按原 source 读取, 透明。
    """
    import requests as _requests

    # curl_cffi 抛自己的 ConnectionError(非 requests 子类), 一并纳入降级触发条件
    _conn_exc = (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout)
    try:
        import curl_cffi.requests.exceptions as _cc_exc  # type: ignore
        _conn_exc = (*_conn_exc, _cc_exc.ConnectionError, _cc_exc.Timeout)
    except Exception:  # noqa: BLE001
        pass

    extra = extra or {}
    adapter = get_adapter(source)
    try:
        return adapter.fetch(symbol, start, end, extra)
    except _conn_exc as exc:
        fb = EM_FALLBACK_SOURCE.get(source)
        if not fb or fb == source:
            raise
        logger.warning(
            "源 %s 拉取 %s 被掐断(%s), 降级到 %s",
            source, symbol, type(exc).__name__, fb,
        )
        return get_adapter(fb).fetch(symbol, start, end, extra)


def prewarm_em_code_maps() -> None:
    """best-effort 预热 EM 代码映射表(index_code_id_map_em / HK _symbol_code_dict)。

    这两个 clist 端点(80.push2 / push2 qt/clist)易被掐断; 一旦成功, @lru_cache 持有
    整个进程生命周期, 之后 cn_index/hk_index 的 secid 解析即可命中缓存(000309/399709
    及 HK 非 HSAHP 指数依赖此)。失败不阻断(自定义 fetch 走前缀探测兜底)。
    """
    import random as _random
    import time as _time

    tasks: list[tuple[str, Callable[[], object]]] = []
    try:
        tasks.append(("index_code_id_map_em", lambda: ak.index_code_id_map_em()))
    except Exception:  # noqa: BLE001
        pass
    try:
        from akshare.index.index_stock_hk import _symbol_code_dict
        tasks.append(("hk_index_symbol_code_dict", lambda: _symbol_code_dict()))
    except Exception:  # noqa: BLE001
        pass

    for label, fn in tasks:
        for attempt in range(2):
            try:
                fn()
                logger.info("预热 EM 代码映射表 %s 成功", label)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    _time.sleep(_random.uniform(10, 20))
                else:
                    logger.debug("预热 %s 失败(忽略, 走前缀探测): %s", label, type(exc).__name__)
