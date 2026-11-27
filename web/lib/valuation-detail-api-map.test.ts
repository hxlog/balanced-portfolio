import { describe, expect, it } from "vitest";
import {
  findPercentile,
  mapPercentileSummary,
  mapValuationDetail,
  mapValuationHistory,
} from "./valuation-detail-api-map";

function detailPayload(overrides: Record<string, unknown> = {}) {
  return {
    index_code: "HSI",
    name: "恒生指数",
    market: "HK",
    index_type: "宽基",
    publisher: "恒生指数公司",
    trade_date: "2026-11-27",
    close_price: 24586.32,
    change_pct: 0.82,
    pe_ttm: 11.2,
    pb: 1.05,
    dividend_yield_ttm: 3.41,
    erp: 4.92,
    roe_ttm: 9.4,
    bond10y: 1.8,
    level_pe: "低估",
    percentiles: [
      { metric: "pe_ttm", window_key: "5y", pct: 35, mean: 11.8, sd: 1.1, p20: 10.2, p50: 11.7, p80: 13.1, min_value: 8.9, max_value: 15.2, sample_size: 260 },
      { metric: "pb", window_key: "5y", pct: 29, mean: 1.1, sd: 0.1, p20: 0.98, p50: 1.08, p80: 1.2, min_value: 0.85, max_value: 1.35, sample_size: 260 },
    ],
    tracker_funds: [
      {
        fund_code: "SH513660",
        name: "华夏恒生ETF",
        company_name: "华夏基金",
        aum: 4.2e10,
        trade_date: "2026-11-23",
        tracking_error_1y: 4.31,
        ann_vol_1y: 18.2,
        risk_as_of: "2026-11-22",
        risk_updated_at: "2026-11-27T21:10:00+08:00",
      },
      {
        fund_code: "SH159920",
        name: "华夏恒生ETF联接",
        aum: 2.1e10,
        trade_date: "2026-11-24",
        tracking_error_1y: 6.82,
      },
    ],
    tracker_funds_meta: {
      data_as_of: "2026-11-23",
      updated_at: "2026-11-27T21:00:00+08:00",
      risk_updated_at: "2026-11-27T21:10:00+08:00",
      fund_count: 2,
    },
    price_series: [
      { trade_date: "2026-11-26", close: 24386.88 },
      { trade_date: "2026-11-27", close: 24586.32 },
      { trade_date: "2026-11-25", close: 0 },
    ],
    risk: {
      "1y": { total_return_pct: 18.2, annualized_return_pct: 18.2, volatility_pct: 20.1, max_drawdown_pct: -12.4, sharpe: 0.91, sample_size: 250 },
    },
    ...overrides,
  };
}

describe("mapValuationDetail", () => {
  it("映射基础字段、分位、收益风险与成分/基金", () => {
    const detail = mapValuationDetail(detailPayload())!;
    expect(detail.index_code).toBe("HSI");
    expect(detail.name).toBe("恒生指数");
    expect(detail.market).toBe("HK");
    expect(detail.close).toBeCloseTo(24586.32);
    expect(detail.change_pct).toBeCloseTo(0.82);
    expect(detail.level_pe).toBe("低估");
    expect(detail.percentiles).toHaveLength(2);
    expect(findPercentile(detail.percentiles, "pe_ttm", "5y")!.pct).toBe(35);
    expect(detail.tracker_funds).toHaveLength(2);
    expect(detail.risk["1y"]!.sharpe).toBeCloseTo(0.91);
  });

  it("跟踪基金 meta：数据截至 = data_as_of，更新于 = risk_updated_at", () => {
    const detail = mapValuationDetail(detailPayload())!;
    expect(detail.tracker_funds_as_of).toBe("2026-11-23");
    expect(detail.tracker_funds_updated_at).toBe("2026-11-27T21:10:00+08:00");
  });

  it("tracker_funds_meta 缺失时回退为 max(基金 trade_date)，不伪造成今天", () => {
    const payload = detailPayload();
    delete (payload as Record<string, unknown>).tracker_funds_meta;
    const detail = mapValuationDetail(payload)!;
    expect(detail.tracker_funds_as_of).toBe("2026-11-24");
    expect(detail.tracker_funds_updated_at).toBeNull();
  });

  it("每只基金只映射后端真实返回的风险更新时间，不再产出 risk_as_of 死字段", () => {
    const detail = mapValuationDetail(detailPayload())!;
    expect(detail.tracker_funds[0].risk_updated_at).toBe("2026-11-27T21:10:00+08:00");
    expect(detail.tracker_funds[1].risk_updated_at).toBeNull();
    // 后端 get_index_tracker_funds 不返回 per-fund risk_as_of；即使旧 payload 带了这个 key
    // 也不应再映射成前端字段（死映射已删除）。
    expect("risk_as_of" in detail.tracker_funds[0]).toBe(false);
  });

  it("点位历史按日期升序、剔除非法/非正价格；缺字段为空数组", () => {
    const detail = mapValuationDetail(detailPayload())!;
    expect(detail.price_series.map((point) => point.trade_date)).toEqual(["2026-11-26", "2026-11-27"]);
    expect(detail.price_series[1].close).toBeCloseTo(24586.32);

    const noPrice = detailPayload();
    delete (noPrice as Record<string, unknown>).price_series;
    expect(mapValuationDetail(noPrice)!.price_series).toEqual([]);
  });

  it("缺少 index_code 时返回 null（按错误态处理）", () => {
    expect(mapValuationDetail({})).toBeNull();
    expect(mapValuationDetail(null)).toBeNull();
  });
});

describe("mapPercentileSummary / mapValuationHistory", () => {
  it("兼容 min/max 与 min_value/max_value 两种列名", () => {
    const summary = mapPercentileSummary({ pct: 42.1, sample_size: "200", min_value: 10, max_value: 14 })!;
    expect(summary.min).toBe(10);
    expect(summary.max).toBe(14);
    expect(summary.sample_size).toBe(200);
    expect(mapPercentileSummary({ pct: 1, min: 2, max: 3 })!.max).toBe(3);
  });

  it("history 映射为按日期升序的 series + stats", () => {
    const history = mapValuationHistory({
      series: [
        { trade_date: "2026-01-09", value: 12.3 },
        { trade_date: "2026-01-02", value: 12.1 },
        { trade_date: "bad", value: 1 },
      ],
      stats: { pct: 35, sample_size: 260, min_value: 8.9, max_value: 15.2 },
    });
    expect(history.series.map((point) => point.trade_date)).toEqual(["2026-01-02", "2026-01-09"]);
    expect(history.stats!.pct).toBe(35);
    expect(history.stats!.min).toBeCloseTo(8.9);
  });

  it("findPercentile 精确按 metric+window 取用", () => {
    const percentiles = [
      { metric: "pe_ttm", window_key: "5y", pct: 35, mean: null, sd: null, p20: null, p50: null, p80: null, min: null, max: null, sample_size: 260 },
      { metric: "pe_ttm", window_key: "10y", pct: 40, mean: null, sd: null, p20: null, p50: null, p80: null, min: null, max: null, sample_size: 500 },
    ];
    expect(findPercentile(percentiles, "pe_ttm", "10y")!.pct).toBe(40);
    expect(findPercentile(percentiles, "pb", "5y")).toBeNull();
  });
});
