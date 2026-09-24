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
from datetime import date, timedelta
from typing import Callable, NoReturn, Optional

import akshare as ak
import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)


class UnreachableSourceError(RuntimeError):
    """主源与整条降级链都拿不到数据 —— 与「未知数据源 / 代码不存在」区分开。

    这一类的共同特征是**重试有意义**: 反爬掐断、限频(429)、超时、上游抽风。
    保存资产的门禁靠它放行(见 classify_probe_error), 所以必须与
    「代码写错了」这种真实错误区分, 不能混用一个 RuntimeError。
    """


class SymbolNotFoundError(RuntimeError):
    """每个源都**正常应答**却一致返回空表 —— 代码不存在, 重试没有任何意义。

    与 UnreachableSourceError 的分界是「有没有源抛过连接级异常」:
      - 东财对未知 secid 返回 HTTP 200 + rc=100 + data=null(空表), 不是报错;
      - 真被反爬时会抛连接级异常(curl_cffi http:000 / RemoteDisconnected / 429)。
    两者若共用 UnreachableSourceError, 一个写错的代码就会被当成限频而放行落库。
    """

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
    # 腾讯/新浪对 930xxx 等中证系小众指数无等价代码, akshare 内部在「无数据/非法 symbol」时
    # 会抛 `list indices must be integers or slices, not str`(把 data 当 dict 取 [symbol]);
    # 这里兜底返回空表, 让降级链静默跳过, 而非把噪声当 WARNING 打出来。
    try:
        raw = ak.stock_zh_index_daily_tx(
            symbol=sym, start_date=_fmt(start), end_date=_fmt(end)
        )
    except Exception:  # noqa: BLE001 - 非法/缺失 symbol, 视为无数据
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
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
# 腾讯 web.ifzq.gtimg.cn fqkline (ETF/指数通用; 支持 qfq/hfq/不复权)
# ---------------------------------------------------------------------
_TX_KLINE_COLS = ["date", "open", "close", "high", "low", "volume"]

# 腾讯 fqkline 每页最大条数(实测 >800 会 param error 或异常截断; 800 安全)
_TX_PAGE_SIZE = 800


def _tx_market_prefix(symbol: str) -> str:
    """腾讯 fqkline 需 sh/sz 市场前缀; 纯代码按交易所自动补。"""
    s = symbol.strip().lower()
    if s.startswith(("sh", "sz")):
        return s
    if s.startswith(("5", "6", "9")):  # 510xxx/56xxxx/58xxxx/9xxxxx 上交所 ETF/基金
        return f"sh{s}"
    if s.startswith(("1", "0", "3")):  # 159xxx/16xxxx/18xxxx 深交所; 000300/399xxx 指数
        return f"sz{s}" if s.startswith(("1", "3")) else f"sh{s}"
    return f"sh{s}"  # 兜底沪市


def _fetch_tx_kline(
    symbol: str, start: date, end: date, adjust: str
) -> pd.DataFrame:
    """直连腾讯 fqkline 拉取日 K(ETF/指数通用), 按 800/页向前分页拼全历史。

    端点 https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
    param 格式: {code},day,{start},{end},{count},{fq}  (fq: qfq / hfq / 空=不复权)
    日线行: [date, open, close, high, low, volume] (无 amount/换手率)。

    复权口径注意: 腾讯 hfq 为「单位累计净值」口径(每份 1.0 起步), 与东财 hfq 的
    「后复权价格」口径绝对值不同; 但两口径日收益率一致。因此腾讯只在东财失败时
    作降级源, 由 ingest 层按「收益率对齐」重锚到东财口径(绝不混用绝对价)。
    """
    import requests as _requests

    fq = {"qfq": "qfq", "hfq": "hfq", "": ""}.get(adjust, "")
    code = _tx_market_prefix(symbol)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    frames: list[pd.DataFrame] = []
    page_end = end
    for _ in range(40):  # 防御上限(40×800=32000 日, 远超任何品种历史)
        param = f"{code},day,{start:%Y-%m-%d},{page_end:%Y-%m-%d},{_TX_PAGE_SIZE},{fq}"
        try:
            r = _requests.get(url, params={"param": param}, timeout=20)
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            if _is_conn_error(exc):
                raise
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        node = (data.get("data") or {}).get(code)
        if not isinstance(node, dict):
            break
        key = {"qfq": "qfqday", "hfq": "hfqday", "": "day"}.get(fq, "day")
        arr = node.get(key) or node.get("day") or []
        if not arr:
            break
        df = pd.DataFrame(arr, columns=_TX_KLINE_COLS)
        frames.append(df)
        if len(arr) < _TX_PAGE_SIZE:
            break  # 已到 start 边界
        # 下一页: 以本页最早日期再往前翻(去重靠 _finalize 排序去重)
        page_end = date.fromisoformat(str(df["date"].iloc[0])) - timedelta(days=1)
        if page_end < start:
            break

    if not frames:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    raw = pd.concat(frames, ignore_index=True)
    raw = raw.drop_duplicates(subset=["date"], keep="last")
    return _finalize(_rename(raw, {"date": "trade_date"}), start, end)


def _fetch_etf_tx(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """腾讯 ETF 日 K; adjust 从 extra 取(qfq/hfq/空), 默认不复权。"""
    adjust = extra.get("adjust", "") or ""
    return _fetch_tx_kline(symbol, start, end, adjust)


def _fetch_index_tx(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """腾讯指数日 K(指数不分复权, 恒为不复权口径)。"""
    return _fetch_tx_kline(symbol, start, end, "")


# ---------------------------------------------------------------------
# Yahoo Finance (crypto / forex / commodity) — 走 yfinance
# ---------------------------------------------------------------------
def _fetch_crypto_yfinance(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """使用 yfinance 下载加密/外汇/商品历史日线，归一化为标准 schema。

    yfinance 内部走 requests——项目的 install_hardened_session() 已将
    requests.get/post 和 Session.request 全部 monkeypatch 为 curl_cffi
    Chrome120 指纹，因此自动继承反爬能力。
    """
    from datetime import timedelta

    ticker = yf.Ticker(symbol)
    # yfinance 的 start/end 走 Yahoo chart 端点, 批延迟 1-3 天 (实测 period='10d' 返回到 07-28,
    # 而 start/end 只到 07-26, 缺 07-27/28); period 走 query1 端点更及时。增量窗口短(≤180 天)
    # → 用 period="3mo" 覆盖 revision_days 且数据新鲜; 首次全量(窗口>180 天, 新库才遇到)才用
    # start/end (历史数据无实时性要求)。end+1d: yfinance history end 是 exclusive。
    if (end - start).days <= 180:
        df = ticker.history(period="3mo", auto_adjust=True)
    else:
        df = ticker.history(start=start, end=end + timedelta(days=1), auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    df = df.reset_index()
    rename_map: dict[str, str] = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower == "date":
            rename_map[col] = "trade_date"
        elif col_lower == "open":
            rename_map[col] = "open"
        elif col_lower == "high":
            rename_map[col] = "high"
        elif col_lower == "low":
            rename_map[col] = "low"
        elif col_lower == "close":
            rename_map[col] = "close"
        elif col_lower == "volume":
            rename_map[col] = "volume"
    df = df.rename(columns=rename_map)
    return _finalize(df, start, end)


# ---------------------------------------------------------------------
# 东方财富直连: DXY 美元指数(secid=100.UDI) + COMEX 黄金(akshare futures_foreign_hist)
# 替代 yfinance 的 DX-Y.NYB / GC=F —— prod IP 被 Yahoo 429 限流, 切东方财富后 prod 自日更。
# BTC-USD 主源仍走 yfinance (用户选择, 由 atomicity hold-back 兜底), 降级走 CME 期货
# (btc_cme_sina, 见 AGGREGATE_CHAINS["crypto_yfinance"])。
# ---------------------------------------------------------------------
_DXY_KLINE_COLS = ["trade_date", "open", "close", "high", "low", "volume", "amount"]


def _fetch_dxy_em(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """直连 push2his 拉美元指数(DXY)日 K, secid=100.UDI (东方财富「美元指数」)。

    替代 yfinance DX-Y.NYB。单资产源: symbol 参数忽略, secid 固定 100.UDI。
    f51..f57 = date, open, close, high, low, volume, amount。
    """
    kl = _push2his_klines(
        "100.UDI",
        ut="7eea3edcaed734bea9cbfc24409ed989",
        fields2="f51,f52,f53,f54,f55,f56,f57",
        fqt="0",
        beg=_fmt(start),
        end=_fmt(end),
    )
    if not kl:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    rows = [item.split(",") for item in kl]
    rows = [r + [""] * (7 - len(r)) for r in rows]  # 防御: 补齐不足 7 列
    df = pd.DataFrame(rows, columns=_DXY_KLINE_COLS)
    return _finalize(df, start, end)


def _fetch_gold_comex_em(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """akshare futures_foreign_hist 拉 COMEX 黄金(GC)日线。

    替代 yfinance GC=F。单资产源: symbol 参数忽略, akshare symbol 固定 "GC"。
    akshare 全量返回(cols: date/open/high/low/close/volume/...), _finalize 按 [start,end] 过滤。
    """
    raw = ak.futures_foreign_hist(symbol="GC")
    if raw is None or raw.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    df = _rename(raw, {"date": "trade_date"})
    return _finalize(df, start, end)


def _fetch_btc_cme_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """akshare futures_foreign_hist 拉 CME 比特币期货(BTC 主力)日线。

    yfinance BTC-USD 的境内降级源(prod IP 被 Yahoo 429 时接管)。单资产源: symbol 参数
    忽略, akshare symbol 固定 "BTC"。期货价与现货有基差但收益率高度相关, 经
    AGGREGATE_CHAINS 重锚到现货口径后拼接(有重叠日用重叠收盘比值; 主源整段失败时用
    库中锚点 anchor_close@anchor_date), 对下游清洗/相关性透明。
    """
    raw = ak.futures_foreign_hist(symbol="BTC")
    if raw is None or raw.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    df = _rename(raw, {"date": "trade_date"})
    return _finalize(df, start, end)


# ---------------------------------------------------------------------
# 新浪外汇即期(人民币汇率中间价口径) — 清洗期 CNY 折算的唯一汇率来源
#
# 【实测事实 2026-09-18】akshare 无对应封装函数: `currency_boc_sina` 走的是
# biz.finance.sina.com.cn 的**中国银行牌价**页(汇买价/钞买价/中行折算价), 与新浪
# 「人民币汇率」口径是**两套不同口径**(用户已实测: USD 日变动相关仅 0.149, ±2 日移位
# 检验亦排除日期错位)。本适配器直连新浪自己的日 K 端点(与 dxy_em 直连 push2his 同一
# 思路, 走 http_session 的 curl_cffi Chrome 指纹):
#
#   https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_{sina_sym}=
#       /NewForexService.getDayKLine?symbol={sina_sym}
#
# 例: symbol=USDCNY → sina_sym=fx_susdcny → 返回
#   var _fx_susdcny=("1994-08-30,8.5616,8.5616,8.5616,8.5616,|...|2026-09-18,6.7067,...");
# 每行 `日期,开,低,高,收,`(末位空串 —— 行尾逗号需按此剥掉空字段)。
#
# 【列序实测 2026-09-18】全量 8021 行做不变式检验(共 5210 行 low≠high 可区分两种候选):
#   候选 (日期,开,高,低,收): 满足 低 ≤ 开,收 ≤ 高 的仅 2811/8021 → **否**
#   候选 (日期,开,低,高,收): 满足 低 ≤ 开,收 ≤ 高 的有 8020/8021 → **是**
# (唯一例外 2011-10-03 开=6.3340 < 低=6.3745, 是新浪自身的脏行。)
# 注意: close 恒为第 4 个数值字段, 两种候选一致, 故折算结果不受列序误解影响;
# 但 high/low 语义必须按实测写对(前端 K 线取用)。
#
# 【不注册 AGGREGATE_CHAINS】用户已确认: 新浪口径不可与中行/其他源聚合, 该源为单一事实源。
# 【无成交量】新浪外汇端点不返回 volume/amount, has_volume=False。
# ---------------------------------------------------------------------
_FX_SINA_KLINE_COLS = ["trade_date", "open", "low", "high", "close", "_pad"]

# 新浪外汇代码表里的人民币对, 币种三字母小写(实测可用: usd/hkd/jpy/eur/gbp/aud/cad/chf/
# nzd/sgd/krw/inr/rub/brl/vnd/thb/myr/php/mop/sek/nok/dkk/try/zar/mxn/twd)。
_FX_SINA_URL = (
    "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/"
    "var%20_{sina_sym}=/NewForexService.getDayKLine"
)


def fx_sina_symbol(symbol: str) -> Optional[str]:
    """`{币种}CNY`(如 USDCNY) → 新浪外汇代码(如 fx_susdcny); 非 {币种}CNY 形态返回 None。"""
    s = symbol.strip().upper()
    if not s.endswith("CNY") or len(s) != 6:
        return None
    return f"fx_s{s[:-3].lower()}cny"


def _fetch_fx_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """直连新浪外汇日 K(全量返回, 由 _finalize 按 [start, end] 过滤)。

    连接级错误(掐断/超时)**向上抛**: 汇率无降级源(用户已确认新浪口径不可聚合),
    由 ingest 层的重试/退避处理, 绝不静默返回空表冒充「无数据」。
    """
    import requests as _requests

    sina_sym = fx_sina_symbol(symbol)
    if sina_sym is None:
        raise ValueError(f"fx_sina: 非法汇率标的 {symbol!r}, 期望形如 USDCNY / HKDCNY")
    url = _FX_SINA_URL.format(sina_sym=sina_sym)
    r = _requests.get(url, params={"symbol": sina_sym}, timeout=20)
    text = r.text or ""
    if '("' not in text or '")' not in text:
        logger.warning("fx_sina: %s(%s) 响应非 JSONP, 前 200 字符: %r", symbol, sina_sym, text[:200])
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    body = text[text.index('("') + 2 : text.rindex('")')]
    rows = [item.split(",") for item in body.split("|") if item]
    if not rows:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    rows = [r + [""] * (len(_FX_SINA_KLINE_COLS) - len(r)) for r in rows]
    df = pd.DataFrame([r[: len(_FX_SINA_KLINE_COLS)] for r in rows], columns=_FX_SINA_KLINE_COLS)
    return _finalize(df, start, end)


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
    "etf_tx": SourceAdapter(
        "etf_tx", "tencent_fqkline", True, True, False, _fetch_etf_tx
    ),
    "index_tx": SourceAdapter(
        "index_tx", "tencent_fqkline", True, True, False, _fetch_index_tx
    ),
    "crypto_yfinance": SourceAdapter(
        "crypto_yfinance", "yfinance.download", True, True, False, _fetch_crypto_yfinance
    ),
    "btc_cme_sina": SourceAdapter(
        "btc_cme_sina", "futures_foreign_hist", True, True, False, _fetch_btc_cme_sina
    ),
    "dxy_em": SourceAdapter(
        "dxy_em", "em_push2his_kline", True, False, False, _fetch_dxy_em
    ),
    "gold_comex_em": SourceAdapter(
        "gold_comex_em", "futures_foreign_hist", True, True, False, _fetch_gold_comex_em
    ),
    # 汇率(新浪「人民币汇率」口径, 直连 jsonp 日 K; 无成交量)。symbol 形如 USDCNY。
    "fx_sina": SourceAdapter(
        "fx_sina", "NewForexService.getDayKLine", False, False, False, _fetch_fx_sina
    ),
}


def get_adapter(source: str) -> SourceAdapter:
    if source not in SOURCES:
        raise KeyError(f"未知 source: {source}; 可用: {sorted(SOURCES)}")
    return SOURCES[source]


# 多源聚合降级链(主源 → 降级源)。仅聚合「收益率一致」的源:
# 同复权口径(qfq↔qfq / hfq↔hfq / 指数不复权)下, 各源绝对价仅差一个常数倍(累计收益率相同),
# 因此可用「重叠日收盘比值」把降级源重锚到主源口径, 绝不混用原始绝对价。
# 只有东财/腾讯提供真正后复权(hfq); 新浪 ETF 仅原始价(不复权), 不纳入 hfq/qfq 聚合链。
#
# 指数(不复权): 东财 → 新浪 → 腾讯(三者同值, 比值恒 1)。
# ETF: 东财 → 腾讯, adjust 由资产 extra_params.adjust 驱动(hfq 为回测口径; qfq 仅 probe/展示)。
# 加密: BTC-USD 现货(yfinance) → CME 期货(新浪), 期货/现货基差经重锚吸收
# (有重叠日用重叠收盘比值; 主源整段失败/被 429 时用库中锚点, 周末锚点取期货帧
# ≤锚点日最近一根, 容差 7 天)。
# 汇率(fx_sina): **刻意不注册** — 新浪人民币汇率与中行牌价是不同口径(实测 USD 日变动
# 相关 0.149), 不可按「同口径常数倍」重锚, 故汇率只有单一事实源, 无降级链。
AGGREGATE_CHAINS: dict[str, list[str]] = {
    "cn_index_em": ["cn_index_sina", "cn_index_tx", "index_tx"],
    "cn_index_em_px": ["cn_index_tx", "index_tx"],
    "hk_index_em": ["hk_index_sina"],
    "global_index_em": ["global_index_sina"],
    "etf_em": ["etf_tx"],
    "crypto_yfinance": ["btc_cme_sina"],
}


def _frame_covers_end(df: pd.DataFrame, end: date) -> bool:
    if df is None or df.empty or "trade_date" not in df.columns:
        return False
    return end in set(df["trade_date"].tolist())


def _align_fallback_to_base(
    base_df: pd.DataFrame | None,
    fb_df: pd.DataFrame,
    anchor_close: float | None = None,
    anchor_date: date | None = None,
) -> pd.DataFrame:
    """把降级源按「重叠日收盘比值」重锚到主源口径。

    同复权口径下两源日收益率一致 → 绝对价仅差一个常数倍, 故在任一重叠交易日取
    base_close / fb_close 作为缩放因子, 把降级源 ohlc 整体缩放, 与主源价格连续可比。
    无重叠时(base_df 空/无交集)退而求其次用库中锚点(anchor_close@anchor_date)对齐;
    锚点日在降级帧无精确行时(如 BTC 周末锚点 vs CME 工作日帧), 取 ≤锚点日最近一根
    (容差 7 天)重锚; 仍无锚点则原样返回, 由调用方视为新资产整段降级。
    """
    if fb_df is None or fb_df.empty:
        return fb_df
    # 1) 与主源本窗口结果的交集对齐
    if base_df is not None and not base_df.empty:
        base_dates = set(base_df["trade_date"].tolist())
        overlap = fb_df[fb_df["trade_date"].isin(base_dates)]
        if not overlap.empty:
            anchor = overlap.sort_values("trade_date").iloc[-1]
            b_rows = base_df[base_df["trade_date"] == anchor["trade_date"]]
            if not b_rows.empty:
                b_close = b_rows["close"].iloc[0]
                f_close = anchor["close"]
                if b_close and not pd.isna(b_close) and f_close and not pd.isna(f_close):
                    ratio = float(b_close) / float(f_close)
                    if ratio and ratio != 1.0:
                        out = fb_df.copy()
                        for col in ("open", "high", "low", "close"):
                            out[col] = out[col] * ratio
                        return out
    # 2) 库中锚点对齐(主源整段失败、仅底层已有历史时)
    if anchor_close and anchor_date is not None:
        anchor_rows = fb_df[fb_df["trade_date"] == anchor_date]
        if anchor_rows.empty:
            # BTC 现货 7 天周 vs CME 期货 5 天周: 周末锚点在期货帧无精确日期,
            # 取 ≤anchor_date 最近一根(容差 7 天)重锚, 避免未缩放期货价混入现货序列。
            prior = fb_df[fb_df["trade_date"] <= anchor_date]
            if not prior.empty:
                cand = prior.sort_values("trade_date").iloc[-1]
                if (anchor_date - cand["trade_date"]).days <= 7:
                    anchor_rows = fb_df[fb_df["trade_date"] == cand["trade_date"]]
        if not anchor_rows.empty:
            f_close = anchor_rows["close"].iloc[0]
            if f_close and not pd.isna(f_close):
                ratio = float(anchor_close) / float(f_close)
                if ratio and ratio != 1.0:
                    out = fb_df.copy()
                    for col in ("open", "high", "low", "close"):
                        out[col] = out[col] * ratio
                    return out
    return fb_df


def fetch_with_fallback(
    source: str,
    symbol: str,
    start: date,
    end: date,
    extra: dict | None = None,
    *,
    anchor_close: float | None = None,
    anchor_date: date | None = None,
) -> pd.DataFrame:
    """优先用主源拉取; 若主源被反爬掐断或未覆盖 end, 沿聚合链降级并按收益率对齐重锚。

    - 主源/降级源同复权口径, 绝对价仅差常数倍 → 缩放对齐后合并(主源优先, 降级源补尾部缺口)。
    - 主源整段失败时, 用库中锚点 close(anchor_close@anchor_date, 主源口径)把降级源重锚,
      避免混入降级源不同基数的绝对价(如腾讯 hfq 的单位净值口径)污染收益序列。
    - 降级源未发布当日收盘时, 继续尝试链上下一源(收盘后强制重拉能拿到正式 close)。
    - 返回的 DataFrame 仍是主源口径价格, 对回测/清洗透明。
    """
    import requests as _requests

    # curl_cffi 抛自己的 ConnectionError(非 requests 子类), 一并纳入降级触发条件;
    # HTTPError 保留为通用 4xx/5xx 连接级触发(_is_conn_error 亦按连接级处理)。
    _conn_exc = (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout,
                 _requests.exceptions.HTTPError)
    try:
        import curl_cffi.requests.exceptions as _cc_exc  # type: ignore
        _conn_exc = (*_conn_exc, _cc_exc.ConnectionError, _cc_exc.Timeout)
    except Exception:  # noqa: BLE001
        pass
    # yfinance 对 Yahoo 429 抛自家 YFRateLimitError(非 requests 系), 必须显式纳入,
    # 否则 crypto 降级链在头号场景(prod IP 被限流)下不触发。
    try:
        from yfinance.exceptions import YFRateLimitError as _yf_rate_exc  # type: ignore
        _conn_exc = (*_conn_exc, _yf_rate_exc)
    except Exception:  # noqa: BLE001
        pass

    extra = extra or {}
    adapter = get_adapter(source)
    chain = AGGREGATE_CHAINS.get(source, [])
    last_df: pd.DataFrame | None = None
    # 只要**任一个源**抛出过连接级异常, 「全链拿不到数据」就归因于可达性(可重试);
    # 反之若每个源都正常应答却一致为空, 那是代码不存在 —— 见 SymbolNotFoundError。
    saw_conn_error = False

    try:
        last_df = adapter.fetch(symbol, start, end, extra)
        if _frame_covers_end(last_df, end) or not chain:
            return last_df
        logger.info(
            "源 %s 拉取 %s 缺 end=%s, 尝试降级链补全日 K",
            source, symbol, end,
        )
    except _conn_exc as exc:
        if not chain:
            raise
        saw_conn_error = True
        logger.warning(
            "源 %s 拉取 %s 被掐断(%s), 降级链 %s",
            source, symbol, type(exc).__name__, chain,
        )

    for fb in chain:
        try:
            df = get_adapter(fb).fetch(symbol, start, end, extra)
        except Exception as exc:  # noqa: BLE001
            # 判据与 probe 端点同源(classify_probe_error), 避免两处各写一份而分叉:
            # 429/5xx/超时/掐断都算「重试有意义」, 上游 4xx 与未知异常不算。
            if classify_probe_error(exc) == "unreachable":
                saw_conn_error = True
            logger.warning("降级源 %s 拉取 %s 失败: %s", fb, symbol, exc)
            continue
        if df is None or df.empty:
            continue
        aligned = _align_fallback_to_base(last_df, df, anchor_close, anchor_date)
        if _frame_covers_end(aligned, end):
            if last_df is not None and not last_df.empty:
                merged = pd.concat([last_df, aligned], ignore_index=True)
                merged = merged.drop_duplicates(subset=["trade_date"], keep="first")
                merged = merged.sort_values("trade_date").reset_index(drop=True)
                logger.info("降级源 %s 补齐 %s 的 end=%s", fb, symbol, end)
                return merged
            return aligned
        if last_df is None or last_df.empty or (
            not aligned.empty
            and aligned["trade_date"].max() > last_df["trade_date"].max()
        ):
            last_df = aligned

    if last_df is not None and not last_df.empty:
        return last_df
    if not saw_conn_error:
        # 所有源都好好应答了, 只是都没有这个代码的数据 —— 重试无意义, 别放行落库。
        raise SymbolNotFoundError(f"源 {source} 及降级链均无 {symbol} 的行情数据")
    raise UnreachableSourceError(f"源 {source} 及降级链均无法拉取 {symbol}")


def classify_probe_error(exc: BaseException) -> str:
    """把一次测试读取的异常归类成 probe 结论 —— 「接口可达但本次取不到」vs「真实错误」。

    调用点: bp_api.main.probe_admin_asset(写入 bp_asset_data_status.last_probe_kind)。
    保存资产的门禁据此放行: unreachable 允许保存(由后台 ingest 补拉), invalid 拦截。

    判据是**错误形状**而非「哪个源」, 因为限频/反爬的形态在不同源下是一样的:
      - 'invalid'     未知数据源(KeyError: get_adapter)、代码不存在(SymbolNotFoundError)
                      或上游 4xx —— 这些重试一万次也不会变, 必须让用户改输入。
      - 'unreachable' 连接被掐断/超时/RemoteDisconnected/SSL/429 限流/整条降级链全灭。
                      接口本身没问题, 换个时间或换出口 IP 就能拉到, 因此不能卡住交互。
    """
    if isinstance(exc, KeyError):
        # get_adapter: "未知 source: <x>" —— 数据源在注册表里不存在, 属配置错误。
        return "invalid"
    if isinstance(exc, SymbolNotFoundError):
        # 每个源都正常应答却一致为空 —— 代码不存在, 放行只会落一个永远没数据的死标的。
        return "invalid"
    if isinstance(exc, UnreachableSourceError):
        return "unreachable"
    if isinstance(exc, requests.exceptions.HTTPError):
        # 上游明确返回的状态码: 4xx(除 408/429)说明请求本身不对(代码不存在/参数非法);
        # 429 与 5xx 是服务端侧限频/抽风, 归入可重试。
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None and 400 <= status < 500 and status not in (408, 429):
            return "invalid"
        return "unreachable"
    if type(exc).__name__ == "YFRateLimitError":
        return "unreachable"
    if _is_conn_error(exc):
        return "unreachable"
    # 未知异常: 保守判为 invalid —— 宁可让用户看到错误信息, 也不放行一个真写错的代码。
    return "invalid"



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
