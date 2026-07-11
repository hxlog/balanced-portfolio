"""反爬 cookie 与连通性自检: 实测东财/新浪请求是否被掐 + 打印按 host 注入的 cookie。

用法:
  python scripts/check_cookies.py

退出码 0 = 两路均通; 非 0 = 至少一路被掐/出错。直接回答"我的 cookie 是否生效"。
"""
from __future__ import annotations

import os
import sys

# 允许 `python scripts/check_cookies.py` 直接运行: 把仓库根加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK, ✓/✗ 等 Unicode 会编码失败; 强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

from bp_ingest.http_session import install_hardened_session, _cookie_for_host


def _short(s: str, n: int = 120) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def _test_em() -> tuple[bool, str]:
    """东财 push2his kline 端点: 200 且 body 含 klines 数据 → 通。"""
    from bp_ingest import http_session as hs
    sess = hs._GLOBAL
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        "?secid=1.000001&fields1=f1&fields2=f51&klt=101&fqt=0&beg=20250101&end=20250110"
    )
    try:
        resp = sess.get(url, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return False, f"请求异常(被掐?): {type(exc).__name__}: {exc}"
    sc = getattr(resp, "status_code", 0) or 0
    body = getattr(resp, "text", "") or ""
    ok = sc == 200 and "klines" in body
    return ok, f"HTTP {sc}; body[:120]={_short(body)!r}"


def _test_sina() -> tuple[bool, str]:
    """新浪 hq.sinajs.cn 行情端点: 200 且 body 含 hq_str_sh000300 且有逗号(真实数据) → 通。"""
    from bp_ingest import http_session as hs
    sess = hs._GLOBAL
    url = "https://hq.sinajs.cn/list=sh000300"
    try:
        resp = sess.get(url, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return False, f"请求异常(被掐?): {type(exc).__name__}: {exc}"
    sc = getattr(resp, "status_code", 0) or 0
    body = getattr(resp, "text", "") or ""
    # 空数据为 `var hq_str_sh000300="";` 无逗号; 真实行情为逗号分隔的多字段
    ok = sc == 200 and "hq_str_sh000300" in body and "," in body
    return ok, f"HTTP {sc}; body[:120]={_short(body)!r}"


def main() -> int:
    install_hardened_session()
    from bp_ingest import http_session as hs
    sess = hs._GLOBAL
    if sess is None:
        print("会话未初始化", file=sys.stderr)
        return 1

    print(f"engine: {sess.engine}  (本机 IP 直连, 无代理)")
    em = os.getenv("BP_EM_COOKIE", "").strip()
    sina = os.getenv("BP_SINA_COOKIE", "").strip()
    print(f"BP_EM_COOKIE:   {'已设置 (len=%d)' % len(em) if em else '(未设置, 靠 TLS 指纹+预热)'}")
    print(f"BP_SINA_COOKIE: {'已设置 (len=%d)' % len(sina) if sina else '(未设置, 靠 TLS 指纹+预热)'}")

    print("\n按 host 将注入的手动 cookie (确认东财 cookie 不会发到新浪):")
    for host in ("push2his.eastmoney.com", "hq.sinajs.cn"):
        c = _cookie_for_host(host)
        print(f"  {host:32} {'(无)' if not c else f'已设置 (len={len(c)})'}")

    print("\ncookie jar (预热种入):")
    jar = sess.cookies
    any_cookie = False
    try:
        for c in jar:
            name = getattr(c, "name", None) or str(c)
            domain = getattr(c, "domain", "") or ""
            print(f"  {domain:30} {name}=<redacted>")
            any_cookie = True
    except TypeError:
        for name in dict(jar):
            print(f"  {name}=<redacted>")
            any_cookie = True
    if not any_cookie:
        print("  (空)")

    print("\n连通性实测:")
    em_ok, em_msg = _test_em()
    print(f"  东财 push2his : {'✓ 通' if em_ok else '✗ 被掐/失败'}  {em_msg}")
    sina_ok, sina_msg = _test_sina()
    print(f"  新浪 hq.sinajs: {'✓ 通' if sina_ok else '✗ 被掐/失败'}  {sina_msg}")

    print("\n结论:")
    if em_ok and sina_ok:
        print("  两路均通, cookie/指纹有效。")
        return 0
    if not em_ok and not sina_ok:
        print("  两路均被掐: 多为 IP 信誉限速或云服务器外网不通; 调大 BP_REQUEST_INTERVAL, 确认可访问外网。")
    elif not em_ok:
        print("  仅东财被掐: 若 BP_EM_COOKIE 已设置仍失败, 多为 ct 令牌 IP 绑定(跨 IP 复制失效);")
        print("    尝试从云服务器本机浏览器重新获取 cookie, 或留空 BP_EM_COOKIE 单靠 chrome120 TLS 指纹 + 预热。")
    else:
        print("  仅新浪被掐: 确认 BP_SINA_COOKIE 取自 finance.sina.com.cn 且双引号包裹; 或留空靠预热。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
