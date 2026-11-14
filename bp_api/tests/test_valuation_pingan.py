"""平安估值采集器 — 解析/归一化/抓取编排测试 (全部离线, 不联网).

夹具来自 docs/_recon 的实测响应裁剪:
  - index_data.json               pingan-vault.json INDEX_DATA 前 3 行
  - index_data_v2_930641.json     req_10664.185 INDEX_DATA_V2 单行 (长序列已裁剪)
  - bond10_trend.json             req_10664.186 BOND10_TREND 前 3 行
  - index_description_930641.json req_10664.163 A_INDEX_DESCRIPTION
  - index_valuation_930641.json   req_10664.164 A_INDEX_VALUATION
  - index_performance.json        req_10664.165 S_INDEX_PERFORMANCE
  - tracker_funds.json            req_10664.176 queryOnsiteFundInfoList

运行: python -m pytest bp_api/tests/test_valuation_pingan.py -q
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pingan"


def _body(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _row(name: str) -> dict:
    return _body(name)["rows"][0]


class TestParseSeries:
    def test_parses_date_value_pairs(self):
        from bp_ingest.valuation_pingan import parse_series

        assert parse_series("20211119,31.9|20211126,32.1") == [
            (date(2021, 11, 19), 31.9),
            (date(2021, 11, 26), 32.1),
        ]

    def test_empty_and_none_return_empty_list(self):
        from bp_ingest.valuation_pingan import parse_series

        assert parse_series("") == []
        assert parse_series(None) == []
        assert parse_series("   ") == []

    def test_skips_malformed_pairs(self):
        from bp_ingest.valuation_pingan import parse_series

        raw = "20211119,31.9|bad-date,12|20211126,abc|20211203|20211210,3.68%"
        assert parse_series(raw) == [
            (date(2021, 11, 19), 31.9),
            (date(2021, 12, 10), 3.68),
        ]


class TestParseStockList:
    def test_parses_vendor_code_name_weight(self):
        from bp_ingest.valuation_pingan import parse_stock_list

        assert parse_stock_list("SZ000538,云南白药,10.76%|SH600436,片仔癀,10.71%") == [
            {
                "vendor_code": "SZ000538",
                "stock_code": "000538",
                "market": "SZ",
                "name": "云南白药",
                "weight": 10.76,
            },
            {
                "vendor_code": "SH600436",
                "stock_code": "600436",
                "market": "SH",
                "name": "片仔癀",
                "weight": 10.71,
            },
        ]

    def test_empty_and_none_return_empty_list(self):
        from bp_ingest.valuation_pingan import parse_stock_list

        assert parse_stock_list("") == []
        assert parse_stock_list(None) == []

    def test_skips_invalid_and_keeps_missing_weight_as_none(self):
        from bp_ingest.valuation_pingan import parse_stock_list

        raw = "SZ000538,云南白药,|,缺代码,1.0%|SH600436,片仔癀,abc|SH600519,贵州茅台,10.5%"
        assert parse_stock_list(raw) == [
            {
                "vendor_code": "SZ000538",
                "stock_code": "000538",
                "market": "SZ",
                "name": "云南白药",
                "weight": None,
            },
            {
                "vendor_code": "SH600436",
                "stock_code": "600436",
                "market": "SH",
                "name": "片仔癀",
                "weight": None,
            },
            {
                "vendor_code": "SH600519",
                "stock_code": "600519",
                "market": "SH",
                "name": "贵州茅台",
                "weight": 10.5,
            },
        ]


class TestParseTrace:
    def test_parses_year_a_b(self):
        from bp_ingest.valuation_pingan import parse_trace

        assert parse_trace("2021,10.77,6.99|2026Q3,8.63,5.52") == [
            {"year": "2021", "a": 10.77, "b": 6.99},
            {"year": "2026Q3", "a": 8.63, "b": 5.52},
        ]

    def test_empty_and_none_return_empty_list(self):
        from bp_ingest.valuation_pingan import parse_trace

        assert parse_trace("") == []
        assert parse_trace(None) == []

    def test_skips_missing_year_and_keeps_invalid_numbers_as_none(self):
        from bp_ingest.valuation_pingan import parse_trace

        assert parse_trace("2021,10.77,6.99|,1,2|2022,abc,def") == [
            {"year": "2021", "a": 10.77, "b": 6.99},
            {"year": "2022", "a": None, "b": None},
        ]


class TestNormalizeIndexRow:
    def test_normalizes_930641_full_row(self):
        from bp_ingest.valuation_pingan import normalize_index_row

        raw = _row("index_data_v2_930641.json")
        row = normalize_index_row(raw)

        assert row["vendor_code"] == "ZI930641"
        assert row["index_code"] == "930641"
        assert row["market"] == "CSI"
        assert row["name"] == "中证中药"
        assert row["index_type"] == "主题"

        assert row["pe_ratio"] == pytest.approx(23.27)
        assert row["pe_percentile"] == pytest.approx(13.68)
        assert row["pe_level"] == "较低"
        assert row["pb_ratio"] == pytest.approx(2.02)
        assert row["pb_percentile"] == pytest.approx(2.72)
        assert row["is_pb"] == 0
        assert row["dividend_rate"] == pytest.approx(3.68)
        assert row["dividend_percentile"] == pytest.approx(4.98)
        assert row["bond10"] == pytest.approx(1.6123)
        assert row["update_date"] == date(2026, 11, 14)

        assert len(row["pe_bar"]) == 5
        assert row["pe_bar"][0] == (date(2021, 11, 19), 31.9)
        assert len(row["dividend_history"]) == 5
        assert row["dividend_history"][0] == (date(2021, 11, 19), 1.54)

        assert len(row["stock_list"]) == 30
        assert row["stock_list"][0] == {
            "vendor_code": "SZ000538",
            "stock_code": "000538",
            "market": "SZ",
            "name": "云南白药",
            "weight": 10.76,
        }
        assert row["etf_fund"] == ["SH560080", "SZ159647", "SH561510"]
        assert len(row["etf_fund"]) == 3
        assert row["otc_fund"] == ["501012", "501011", "016892", "016891"]

        assert len(row["roe_trace"]) == 6
        assert row["roe_trace"][-1] == {"year": "2026Q3", "a": 8.63, "b": 5.52}
        assert len(row["profit_trace"]) == 6
        assert row["profit_trace"][0] == {"year": "2021", "a": 44.8, "b": 10.56}

    def test_missing_fields_become_none_or_empty(self):
        from bp_ingest.valuation_pingan import normalize_index_row

        row = normalize_index_row({"code": "ZI930641"})

        assert row["index_code"] == "930641"
        assert row["market"] == "CSI"
        assert row["pe_ratio"] is None
        assert row["dividend_rate"] is None
        assert row["update_date"] is None
        assert row["pe_bar"] == []
        assert row["pb_bar"] == []
        assert row["stock_list"] == []
        assert row["etf_fund"] == []
        assert row["otc_fund"] == []
        assert row["roe_trace"] == []

    def test_invalid_values_are_dropped(self):
        from bp_ingest.valuation_pingan import normalize_index_row

        row = normalize_index_row(
            {
                "code": "ZI000300",
                "peRatio": "--",
                "dividendRate": "",
                "roe": "NaN",
                "isPb": "x",
                "peBar": "not-a-series",
                "stockList": None,
                "etfFund": "",
                "updateDate": "not-a-date",
            }
        )

        assert row["index_code"] == "000300"
        assert row["market"] == "CSI"
        assert row["pe_ratio"] is None
        assert row["dividend_rate"] is None
        assert row["roe"] is None
        assert row["is_pb"] is None
        assert row["pe_bar"] == []
        assert row["stock_list"] == []
        assert row["etf_fund"] == []
        assert row["update_date"] is None

    @pytest.mark.parametrize(
        ("vendor_code", "expected_code", "expected_market"),
        [
            ("ZI930641", "930641", "CSI"),
            ("SH000300", "000300", "SH"),
            ("SZ399997", "399997", "SZ"),
            ("HKHSI", "HSI", "HK"),
            ("IXSPX", "SPX", "US"),
            ("930641", "930641", None),
        ],
    )
    def test_vendor_code_split(self, vendor_code, expected_code, expected_market):
        from bp_ingest.valuation_pingan import normalize_index_row

        row = normalize_index_row({"code": vendor_code})
        assert row["index_code"] == expected_code
        assert row["market"] == expected_market


class TestFetchOrchestration:
    def test_fetch_index_detail_batches_codes_by_ten(self, monkeypatch):
        from bp_ingest import valuation_pingan as vp

        calls: list[dict] = []

        def fake_post(url: str, payload: dict) -> dict:
            calls.append(dict(payload))
            codes = payload["codes"].split(",")
            return {
                "responseCode": "0",
                "total": len(codes),
                "rows": [{"code": code} for code in codes],
            }

        monkeypatch.setattr(vp, "_post_form", fake_post)
        codes = [f"ZI{i:06d}" for i in range(25)]

        rows = vp.fetch_index_detail(codes)

        assert len(rows) == 25
        assert [len(c["codes"].split(",")) for c in calls] == [10, 10, 5]
        assert all(c["key"] == "INDEX_DATA_V2" for c in calls)

    def test_fetch_bond10_history_paginates_until_total(self, monkeypatch):
        from bp_ingest import valuation_pingan as vp

        all_rows = [
            {"tradeDt": "20261113", "bAnalyield": "1.6123"},
            {"tradeDt": "20261112", "bAnalyield": "1.6032"},
            {"tradeDt": "20261111", "bAnalyield": "1.6039"},
        ]
        pages: list[int] = []

        def fake_post(url: str, payload: dict) -> dict:
            page = int(payload["curPage"])
            size = int(payload["pageSize"])
            pages.append(page)
            start = (page - 1) * size
            return {
                "responseCode": "0",
                "total": len(all_rows),
                "rows": all_rows[start : start + size],
            }

        monkeypatch.setattr(vp, "PAGE_SIZE", 2)
        monkeypatch.setattr(vp, "_post_form", fake_post)

        assert vp.fetch_bond10_history() == all_rows
        assert pages == [1, 2]

    def test_fetch_tracker_funds_uses_code_list_and_flattens_data(self, monkeypatch):
        from bp_ingest import valuation_pingan as vp

        body = _body("tracker_funds.json")
        calls: list[tuple[str, dict]] = []

        def fake_post(url: str, payload: dict) -> dict:
            calls.append((url, dict(payload)))
            return body

        monkeypatch.setattr(vp, "_post_form", fake_post)

        rows = vp.fetch_tracker_funds(["SH560080", "SZ159647"])

        assert rows == body["data"]
        assert calls == [(vp.TRACKER_FUND_URL, {"codeList": "SH560080,SZ159647"})]

    def test_fetch_index_universe_uses_index_data_fixture(self, monkeypatch):
        from bp_ingest import valuation_pingan as vp

        body = _body("index_data.json")
        calls: list[dict] = []

        def fake_post(url: str, payload: dict) -> dict:
            calls.append(dict(payload))
            return body

        monkeypatch.setattr(vp, "_post_form", fake_post)

        assert vp.fetch_index_universe() == body["rows"]
        assert calls[0]["key"] == "INDEX_DATA"
        assert calls[0]["pageSize"] == 999

    def test_fetch_auxiliary_views_uses_fixture_rows(self, monkeypatch):
        from bp_ingest import valuation_pingan as vp

        fixtures = {
            "A_INDEX_DESCRIPTION": _body("index_description_930641.json"),
            "A_INDEX_VALUATION": _body("index_valuation_930641.json"),
            "S_INDEX_PERFORMANCE": _body("index_performance.json"),
            "BOND10_TREND": _body("bond10_trend.json"),
        }

        monkeypatch.setattr(
            vp,
            "_post_form",
            lambda url, payload: fixtures[payload["key"]],
        )

        assert vp.fetch_index_description() == fixtures["A_INDEX_DESCRIPTION"]["rows"]
        assert vp.fetch_index_valuation_meta() == fixtures["A_INDEX_VALUATION"]["rows"]
        assert vp.fetch_index_performance() == fixtures["S_INDEX_PERFORMANCE"]["rows"]
        assert vp.fetch_bond10_history() == fixtures["BOND10_TREND"]["rows"]

    def test_post_form_retries_transient_http_errors_with_backoff(self, monkeypatch):
        from bp_ingest import valuation_pingan as vp

        sleeps: list[float] = []
        responses = [500, 503, 200]

        class FakeResponse:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

            def json(self) -> dict:
                return {"responseCode": "0", "total": 1, "rows": [{"code": "ZI930641"}]}

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

        attempts: list[int] = []

        def fake_post(url: str, **kwargs):
            attempts.append(1)
            return FakeResponse(responses[len(attempts) - 1])

        monkeypatch.setattr(vp, "_ensure_hardened_session", lambda: None)
        monkeypatch.setattr(vp, "_GLOBAL_LIMITER", type("L", (), {"acquire": lambda self: None})())
        monkeypatch.setattr(vp.time, "sleep", lambda seconds: sleeps.append(seconds))
        monkeypatch.setattr(vp.requests, "post", fake_post)

        body = vp._post_form(vp.BASE, {"key": "INDEX_DATA_V2", "codes": "ZI930641"})

        assert body["rows"] == [{"code": "ZI930641"}]
        assert len(attempts) == 3
        assert sleeps == [1.0, 2.0]
