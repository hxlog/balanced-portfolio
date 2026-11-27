import { describe, expect, it } from "vitest";
import {
  FRESHNESS_DATASETS,
  FRESHNESS_REQUEST_TIMEOUT_MS,
  formatUpdatedAt,
  freshnessBadgeText,
  freshnessItemTone,
  freshnessMetaSummary,
  freshnessStatusLabel,
  freshnessTone,
  mapFreshness,
  placeholderFreshness,
} from "./valuation-freshness";

const DATASETS = [
  "a_stock",
  "hk_stock",
  "etf",
  "fund_nav",
  "cffex",
  "index_quotes",
  "index_valuation",
  "mvi",
] as const;

function item(dataset: string, overrides: Record<string, unknown> = {}) {
  return {
    dataset,
    label: dataset,
    as_of: "2026-11-27",
    expected_date: "2026-11-27",
    status: "ok",
    is_stale: false,
    lag_days: 0,
    updated_at: "2026-11-27T21:05:00+08:00",
    source: "bp_etl",
    note: null,
    ...overrides,
  };
}

function envelope(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    data: DATASETS.map((dataset) => item(dataset)),
    meta: {
      latest_complete_date: "2026-11-26",
      all_complete: false,
      expected_date: "2026-11-27",
      missing: ["fund_nav"],
      cached: false,
      generated_at: "2026-11-27T18:52:00+08:00",
    },
    error: null,
    ...overrides,
  };
}

describe("mapFreshness", () => {
  it("解析 /api/v1/market/data-freshness 信封并按固定顺序输出 8 类", () => {
    const mapped = mapFreshness(envelope());
    expect(mapped).not.toBeNull();
    expect(mapped!.items.map((row) => row.dataset)).toEqual([...DATASETS]);
    expect(mapped!.meta).toMatchObject({
      latest_complete_date: "2026-11-26",
      all_complete: false,
      expected_date: "2026-11-27",
      missing: ["fund_nav"],
      cached: false,
    });
    const first = mapped!.items[0];
    expect(first.label).toBe("a_stock");
    expect(first.updated_at).toBe("2026-11-27T21:05:00+08:00");
    expect(first.lag_days).toBe(0);
  });

  it("缺失类补占位（status=missing、as_of=null），不会把缺失伪装成 0", () => {
    const payload = envelope();
    (payload.data as unknown[]).splice(3, 2); // 去掉 fund_nav/cffex
    const mapped = mapFreshness(payload)!;
    const fund = mapped.items.find((row) => row.dataset === "fund_nav")!;
    expect(fund.as_of).toBeNull();
    expect(fund.status).toBe("missing");
    expect(fund.is_stale).toBe(true);
    expect(mapped.items).toHaveLength(8);
  });

  it("后端多出的数据类追加在 8 类之后", () => {
    const payload = envelope();
    (payload.data as unknown[]).push(item("extra_dataset", { label: "新增数据" }));
    const mapped = mapFreshness(payload)!;
    expect(mapped.items).toHaveLength(FRESHNESS_DATASETS.length + 1);
    expect(mapped.items.at(-1)!.dataset).toBe("extra_dataset");
  });

  it("meta 缺失时从前端字段推导 latest_complete_date / missing / all_complete", () => {
    const payload = {
      data: [
        item("a_stock", { as_of: "2026-11-20" }),
        item("hk_stock", { as_of: "2026-11-25" }),
        ...DATASETS.slice(2).map((dataset) => item(dataset, { as_of: null, status: "missing", is_stale: true })),
      ],
    };
    const mapped = mapFreshness(payload)!;
    expect(mapped.meta.latest_complete_date).toBe("2026-11-20");
    expect(mapped.meta.all_complete).toBe(false);
    expect(mapped.meta.missing).toContain("mvi");
  });

  it("裸数组响应也兼容（无信封）", () => {
    const mapped = mapFreshness(DATASETS.map((dataset) => item(dataset)));
    expect(mapped).not.toBeNull();
    expect(mapped!.items).toHaveLength(8);
  });

  it("非法响应返回 null（不伪造数据）", () => {
    expect(mapFreshness(null)).toBeNull();
    expect(mapFreshness({ data: null })).toBeNull();
    expect(mapFreshness({ data: [] })).toBeNull();
  });

  it("status 未知值按 missing 处理，不会漏掉琥珀提醒", () => {
    const payload = envelope();
    (payload.data as Array<Record<string, unknown>>)[0].status = "weird";
    (payload.data as Array<Record<string, unknown>>)[0].is_stale = true;
    const mapped = mapFreshness(payload)!;
    expect(mapped.items[0].status).toBe("missing");
    expect(mapped.items[0].is_stale).toBe(true);
  });
});

describe("徽标语气与文案", () => {
  it("接口未就绪 -> pending + 获取中文案", () => {
    expect(freshnessTone(null)).toBe("pending");
    expect(freshnessBadgeText(null)).toBe("数据状态 获取中…");
  });

  it("接口已返回但 latest_complete_date=null -> 暂无数据（不能再显示获取中）", () => {
    const empty = mapFreshness({
      data: DATASETS.map((dataset) => item(dataset, { as_of: null, status: "missing", is_stale: true })),
      meta: { latest_complete_date: null, all_complete: false, expected_date: "2026-11-27", missing: [...DATASETS] },
    })!;
    expect(empty.meta.latest_complete_date).toBeNull();
    expect(freshnessTone(empty)).toBe("pending");
    expect(freshnessBadgeText(empty)).toBe("数据状态 暂无数据");
  });

  it("全齐套 -> ok（绿点），有落后 -> warning（琥珀）", () => {
    const complete = mapFreshness({
      data: DATASETS.map((dataset) => item(dataset)),
      meta: { latest_complete_date: "2026-11-27", all_complete: true, expected_date: "2026-11-27", missing: [] },
    })!;
    expect(freshnessTone(complete)).toBe("ok");
    expect(freshnessBadgeText(complete)).toBe("数据更新至 2026-11-27");

    const lagging = mapFreshness(envelope())!;
    expect(freshnessTone(lagging)).toBe("warning");
  });

  it("单类语气：ok 绿 / 滞后琥珀 / 缺失灰", () => {
    expect(freshnessItemTone("ok")).toBe("ok");
    expect(freshnessItemTone("lagging")).toBe("warning");
    expect(freshnessItemTone("stale")).toBe("warning");
    expect(freshnessItemTone("missing")).toBe("muted");
    expect(freshnessItemTone("unavailable")).toBe("muted");
    expect(freshnessStatusLabel("lagging")).toBe("滞后");
  });

  it("tooltip 摘要包含最新完整日/应到日/生成时间", () => {
    const summary = freshnessMetaSummary(mapFreshness(envelope())!);
    expect(summary).toContain("最新完整数据日 2026-11-26");
    expect(summary).toContain("应到 2026-11-27");
    expect(summary).toContain("生成于 2026-11-27 18:52");
    expect(freshnessMetaSummary(null)).toContain("重试");
  });

  it("轮询请求超时为 10s（防止挂起请求挤掉下一轮）", () => {
    expect(FRESHNESS_REQUEST_TIMEOUT_MS).toBe(10_000);
  });

  it("ISO 时间截断到分钟且兼容 null", () => {
    expect(formatUpdatedAt("2026-11-27T21:05:00+08:00")).toBe("2026-11-27 21:05");
    expect(formatUpdatedAt(null)).toBe("—");
    expect(formatUpdatedAt("")).toBe("—");
  });

  it("占位明细恒为 8 类且日期为 null", () => {
    const placeholder = placeholderFreshness();
    expect(placeholder.items).toHaveLength(8);
    expect(placeholder.items.every((row) => row.as_of === null)).toBe(true);
    expect(placeholder.meta.latest_complete_date).toBeNull();
  });
});
