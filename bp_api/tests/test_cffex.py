"""CFFEX 模块测试。

测试纯逻辑函数 (无外部 DB/Redis 依赖):
  - 合约映射 (map_contracts_from_symbols)
  - 基差/升贴水率/年化升贴水率计算
  - 合成升贴水率 (compute_composite)

运行: python -m pytest bp_api/tests/test_cffex.py -q
"""

from datetime import date


# ---------------------------------------------------------------------------
# 合约解析测试
# ---------------------------------------------------------------------------

class TestContractParse:
    def test_parse_valid_if(self):
        from bp_ingest.cffex_contract_map import Contract
        c = Contract.parse("IF2603")
        assert c is not None
        assert c.variety == "IF"
        assert c.year == 2026
        assert c.month == 3
        # Third Friday of March 2026
        assert c.expiry_date == date(2026, 3, 20)

    def test_parse_valid_ih(self):
        from bp_ingest.cffex_contract_map import Contract
        c = Contract.parse("IH2706")
        assert c is not None
        assert c.variety == "IH"
        assert c.year == 2027
        assert c.month == 6

    def test_parse_invalid(self):
        from bp_ingest.cffex_contract_map import Contract
        assert Contract.parse("XYZ999") is None
        assert Contract.parse("") is None
        assert Contract.parse("IF99") is None  # missing month
        assert Contract.parse("IF2613") is None  # month 13

    def test_is_quarterly(self):
        from bp_ingest.cffex_contract_map import Contract
        assert Contract.parse("IF2603").is_quarterly is True
        assert Contract.parse("IF2606").is_quarterly is True
        assert Contract.parse("IF2609").is_quarterly is True
        assert Contract.parse("IF2612").is_quarterly is True
        assert Contract.parse("IF2604").is_quarterly is False

    def test_expiry_dates(self):
        from bp_ingest.cffex_contract_map import Contract
        # Known third Fridays
        assert Contract.parse("IF2603").expiry_date == date(2026, 3, 20)
        assert Contract.parse("IF2606").expiry_date == date(2026, 6, 19)
        assert Contract.parse("IH2601").expiry_date == date(2026, 1, 16)


# ---------------------------------------------------------------------------
# 合约类型映射测试
# ---------------------------------------------------------------------------

class TestContractMapping:
    def test_map_contracts_basic(self):
        from bp_ingest.cffex_contract_map import map_contracts_from_symbols
        symbols = ["IF2603", "IF2604", "IF2606", "IF2609"]
        ctypes = map_contracts_from_symbols(symbols, date(2026, 3, 7))
        assert ctypes.get("IF2603") == "当月", f"Got: {ctypes}"
        assert ctypes.get("IF2604") == "次月", f"Got: {ctypes}"
        assert ctypes.get("IF2606") == "当季", f"Got: {ctypes}"
        assert ctypes.get("IF2609") == "次季", f"Got: {ctypes}"

    def test_map_post_expiry(self):
        from bp_ingest.cffex_contract_map import map_contracts_from_symbols
        symbols = ["IF2603", "IF2604", "IF2606", "IF2609"]
        ctypes = map_contracts_from_symbols(symbols, date(2026, 3, 21))
        assert "IF2603" not in ctypes, f"Expired still present: {ctypes}"

    def test_map_partial_contracts(self):
        from bp_ingest.cffex_contract_map import map_contracts_from_symbols
        symbols = ["IF2604", "IF2606", "IF2612"]
        ctypes = map_contracts_from_symbols(symbols, date(2026, 5, 1))
        assert len(ctypes) > 0, f"Partial map empty"
        # At minimum, all symbols should be assigned types

    def test_map_all_expired(self):
        from bp_ingest.cffex_contract_map import map_contracts_from_symbols
        symbols = ["IF2603", "IF2604"]
        ctypes = map_contracts_from_symbols(symbols, date(2026, 7, 1))
        # All expired → fallback: uses last 4 sorted by expiry desc
        assert len(ctypes) > 0

    def test_map_empty(self):
        from bp_ingest.cffex_contract_map import map_contracts_from_symbols
        assert map_contracts_from_symbols([], date(2026, 3, 7)) == {}


# ---------------------------------------------------------------------------
# 金融计算测试
# ---------------------------------------------------------------------------

class TestFinancialCalcs:
    def test_composite_rate(self):
        from bp_ingest.cffex_contract_map import compute_composite
        # 0.6*3 + 0.4*10 = 1.8 + 4.0 = 5.8
        comp = compute_composite({"当月": 5.0, "次月": 3.0, "当季": 10.0})
        assert abs(comp - 5.8) < 0.001, f"Expected 5.8, got {comp}"

    def test_composite_missing(self):
        from bp_ingest.cffex_contract_map import compute_composite
        assert compute_composite({"当月": 5.0, "次月": 3.0}) is None
        assert compute_composite({}) is None

    def test_basis(self):
        from bp_ingest.cffex_contract_map import compute_basis
        assert compute_basis(5000, 5100) == -100  # 贴水
        assert compute_basis(5000, 4900) == 100   # 升水
        assert compute_basis(5000, 5000) == 0

    def test_premium_rate(self):
        from bp_ingest.cffex_contract_map import compute_premium_rate
        # basis=-100 (现货<期货, 升水) → premium = 100/5000*100 = 2.0% (正值=升水)
        assert abs(compute_premium_rate(-100, 5000) - 2.0) < 0.001
        # basis=100 (现货>期货, 贴水) → premium = -100/5000*100 = -2.0% (负值=贴水)
        assert abs(compute_premium_rate(100, 5000) - (-2.0)) < 0.001
        assert compute_premium_rate(0, 0) is None

    def test_ann_premium_rate(self):
        from bp_ingest.cffex_contract_map import compute_ann_premium_rate
        apr = compute_ann_premium_rate(2.0, 5)
        assert abs(apr - 146.0) < 0.1
        assert compute_ann_premium_rate(10.0, 0) is None

    def test_days_to_expiry(self):
        from bp_ingest.cffex_contract_map import days_to_expiry
        assert days_to_expiry("IF2603", date(2026, 3, 7)) == 13
        assert days_to_expiry("INVALID", date(2026, 3, 7)) is None


# ---------------------------------------------------------------------------
# 品种常量测试
# ---------------------------------------------------------------------------

class TestConstants:
    def test_varieties(self):
        from bp_ingest.cffex_contract_map import CFFEX_VARIETIES
        assert CFFEX_VARIETIES == ["IF", "IH", "IC", "IM"]

    def test_index_maps(self):
        from bp_ingest.cffex_contract_map import INDEX_SYMBOL_MAP, INDEX_SINA_MAP
        assert INDEX_SYMBOL_MAP["IF"] == "000300"
        assert INDEX_SINA_MAP["IF"] == "sh000300"
        assert INDEX_SYMBOL_MAP["IC"] == "000905"


# ---------------------------------------------------------------------------
# 同日对齐 effective_td
# ---------------------------------------------------------------------------

class TestPickEffectiveTradeDate:
    def test_futures_ahead_of_spot_rolls_back(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 9)
        t1 = date(2026, 7, 8)
        vars_all = {"IF", "IH", "IC", "IM"}
        spots_all = {"000300", "000016", "000905", "000852"}
        futures = {t: vars_all, t1: vars_all}
        spots = {t1: spots_all}  # T 日现货尚未入库
        picked = pick_effective_trade_date([t, t1], futures, spots)
        assert picked == t1

    def test_same_day_synced(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 9)
        vars_all = {"IF", "IH", "IC", "IM"}
        spots_all = {"000300", "000016", "000905", "000852"}
        picked = pick_effective_trade_date(
            [t], {t: vars_all}, {t: spots_all},
        )
        assert picked == t

    def test_missing_variety_skips(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 9)
        t1 = date(2026, 7, 8)
        spots_all = {"000300", "000016", "000905", "000852"}
        futures = {
            t: {"IF", "IH", "IC"},  # 缺 IM
            t1: {"IF", "IH", "IC", "IM"},
        }
        spots = {t: spots_all, t1: spots_all}
        picked = pick_effective_trade_date([t, t1], futures, spots)
        assert picked == t1

    def test_none_when_no_overlap(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 9)
        vars_all = {"IF", "IH", "IC", "IM"}
        picked = pick_effective_trade_date(
            [t], {t: vars_all}, {t: {"000300"}},  # 缺其余指数
        )
        assert picked is None

    def test_max_confirmed_excludes_today(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 17)
        t1 = date(2026, 7, 16)
        vars_all = {"IF", "IH", "IC", "IM"}
        spots_all = {"000300", "000016", "000905", "000852"}
        picked = pick_effective_trade_date(
            [t, t1],
            {t: vars_all, t1: vars_all},
            {t: spots_all, t1: spots_all},
            max_confirmed_date=t1,
        )
        assert picked == t1
