# -*- coding: utf-8 -*-
path = "bp_api/valuation.py"
s = open(path, encoding="utf-8").read()
marker = '    @app.get("/api/valuation/{code}")'
assert marker in s
routes = '''    @app.get("/api/valuation/funds/compare")
    def valuation_funds_compare(
        codes: str = Query(..., description="逗号分隔的基金代码（可带 SH/SZ 前缀）"),
        start: str | None = Query(None, description="开始日期 YYYY-MM-DD，默认年初"),
        end: str | None = Query(None, description="结束日期 YYYY-MM-DD，默认今天"),
        benchmark: str = Query("000300", description="基准指数代码"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        fund_codes = [item.strip() for item in codes.split(",") if item.strip()][:10]
        if not fund_codes:
            raise HTTPException(status_code=400, detail="codes 不能为空")
        try:
            start_date = date.fromisoformat(start) if start else None
            end_date = date.fromisoformat(end) if end else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
        key = _cache_key("funds_compare", codes=",".join(fund_codes), start=start, end=end, benchmark=benchmark)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            payload = repositories_valuation.compare_funds(
                conn, fund_codes, start=start_date, end=end_date, benchmark_code=benchmark
            )
        payload["meta"] = {"as_of": date.today().isoformat(), "cached": False}
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/{code}/benchmark-stats")
    def valuation_benchmark_stats(
        code: str,
        benchmark: str = Query("000300", description="基准指数代码"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key("benchmark_stats", code=code, benchmark=benchmark)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            stats = repositories_valuation.get_index_benchmark_stats(conn, code, benchmark)
        payload = _envelope(stats, as_of=stats.get("as_of"), rows=1, benchmark=benchmark, cached=False)
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

'''
s = s.replace(marker, routes + marker, 1)
open(path, "w", encoding="utf-8").write(s)
print("routes inserted")
