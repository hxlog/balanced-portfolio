import { describe, expect, it } from "vitest";
import type { Asset } from "./api";
import {
  basketFormFromRecord,
  basketItemFromRecordAsset,
  basketItemsFromRecord,
  findPoolAsset,
} from "./basket-load";
import type { BasketRecord } from "./basket-types";

function asset(overrides: Partial<Asset> & { symbol: string; source: string }): Asset {
  return {
    name: overrides.symbol,
    category: "etf",
    asset_class: "equity",
    adjust: "hfq",
    currency: "CNY",
    vendor: "em",
    logical_source: "etf",
    last_clean_date: "2026-11-26",
    ...overrides,
  } as Asset;
}

const POOL: Asset[] = [
  asset({ symbol: "510300", source: "etf_em", name: "沪深300ETF" }),
  asset({
    symbol: "600036",
    source: "stock_sina",
    name: "招商银行",
    category: "stock",
    asset_class: "stock",
    adjust: "hfq",
    logical_source: "stock",
  }),
  asset({ symbol: "AU9999", source: "gold_sge", name: "黄金", category: "commodity" }),
];

function basketRecord(overrides: Partial<BasketRecord> = {}): BasketRecord {
  return {
    basket_id: 1,
    owner_user_id: 7,
    name: "测试篮子",
    description: null,
    method: "risk_parity",
    assets: [
      { symbol: "510300", source: "etf_em" },
      { symbol: "600036", source: "stock_sina" },
      { symbol: "MISSING", source: "etf_em" },
    ],
    params: {},
    latest_result: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-20T00:00:00Z",
    ...overrides,
  };
}

describe("findPoolAsset / basketItemFromRecordAsset", () => {
  it("maps pool assets to display names and keeps pool flags", () => {
    const item = basketItemFromRecordAsset(
      { symbol: "510300", source: "etf_em" },
      POOL,
    );
    expect(item.key).toBe("510300@etf_em");
    expect(item.name).toBe("沪深300ETF");
    expect(item.category).toBe("etf");
    expect(item.inPool).toBe(true);
    expect(item.hasData).toBe(true);
    expect(findPoolAsset(POOL, { symbol: "510300", source: "etf_em" })).toBe(POOL[0]);
  });

  it("falls back to symbol + 未接入 for assets missing from the pool", () => {
    const item = basketItemFromRecordAsset(
      { symbol: "MISSING", source: "etf_em" },
      POOL,
    );
    expect(item.name).toBe("MISSING");
    expect(item.inPool).toBe(false);
    expect(item.hasData).toBe(false);
  });

  it("defaults stock sources to hfq display adjust", () => {
    const item = basketItemFromRecordAsset(
      { symbol: "600036", source: "stock_sina" },
      POOL,
    );
    expect(item.name).toBe("招商银行");
    expect(item.source).toBe("stock_sina");
    expect(item.category).toBe("stock");
  });
});

describe("basketItemsFromRecord", () => {
  it("preserves record order and maps every asset", () => {
    const items = basketItemsFromRecord(basketRecord(), POOL);
    expect(items.map((item) => item.symbol)).toEqual(["510300", "600036", "MISSING"]);
    expect(items.map((item) => item.name)).toEqual([
      "沪深300ETF",
      "招商银行",
      "MISSING",
    ]);
  });

  it("still maps when the pool failed to load (empty pool)", () => {
    const items = basketItemsFromRecord(basketRecord(), []);
    expect(items.every((item) => item.inPool === false)).toBe(true);
    expect(items.map((item) => item.name)).toEqual(["510300", "600036", "MISSING"]);
  });
});

describe("basketFormFromRecord", () => {
  it("converts stored decimals back to percent form values", () => {
    const form = basketFormFromRecord(
      basketRecord({
        params: {
          lookback_days: 252,
          rebalance_band: 0.075,
          risk_free: 0.021,
          start: "2022-01-04",
          end: "2026-11-27",
        },
      }),
    );
    expect(form).toEqual({
      lookbackDays: 252,
      bandPct: 7.5,
      riskFreePct: 2.1,
      start: "2022-01-04",
      end: "2026-11-27",
    });
  });

  it("falls back to defaults for missing/invalid params", () => {
    const form = basketFormFromRecord(
      basketRecord({
        params: {
          lookback_days: Number.NaN,
          rebalance_band: "oops",
          risk_free: Number.POSITIVE_INFINITY,
          start: "",
          end: 42,
        },
      }),
    );
    expect(form.lookbackDays).toBe(156);
    expect(form.bandPct).toBe(5);
    expect(form.riskFreePct).toBe(0);
    expect(form.start).toBeNull();
    expect(form.end).toBeNull();
  });

  it("clamps lookback to at least 2 trading days", () => {
    expect(
      basketFormFromRecord(basketRecord({ params: { lookback_days: 1 } })).lookbackDays,
    ).toBe(2);
    expect(
      basketFormFromRecord(basketRecord({ params: { lookback_days: 0.4 } })).lookbackDays,
    ).toBe(2);
  });
});
