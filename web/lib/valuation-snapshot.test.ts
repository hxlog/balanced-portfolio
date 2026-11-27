import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BAND_INDEX_OPTIONS,
  DEFAULT_BAND_INDEX,
  DEFAULT_MVI_OVERLAY_INDEX,
  MVI_OVERLAY_INDEX_OPTIONS,
  PROXY_CODES,
  deriveProxyCards,
  fetchBandHistories,
  fetchIndexHistory,
  fetchIndexSnapshot,
  fetchMvi,
  fetchMviOverlay,
  mapIndexSnapshot,
  mapMviOverlay,
  mapMviPayload,
} from "./valuation-snapshot";

interface MockResponse {
  status: number;
  body: unknown;
}

function stubFetch(handler: (url: string) => MockResponse | null) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const result = handler(url);
    if (!result) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(result.body), {
      status: result.status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function rawRow(code: string, overrides: Record<string, unknown> = {}) {
  return {
    index_code: code,
    name: "指数" + code,
    index_type: "宽基",
    publisher: "中证指数",
    market: "CSI",
    has_etf: true,
    has_valuation: true,
    trade_date: "2026-11-27",
    close_price: 4016.29,
    change_pct: -0.68,
    change_52w_pct: -14.58,
    position_52w_pct: 62.5,
    pe_ttm: 13.4,
    pe_percentile: 42.1,
    pb: 1.38,
    pb_percentile: 38.2,
    dividend_yield_ttm: 3.2,
    dividend_percentile: 61.0,
    erp: 5.1,
    erp_percentile: 55.0,
    roe_ttm: 10.3,
    fund_aum: 1.2e11,
    fund_count: 24,
    quote_status: "ok",
    quote_lag_days: 0,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("mapIndexSnapshot", () => {
  it("映射新快照接口的 rows/meta（复用 mapIndexRow 口径）", () => {
    const snapshot = mapIndexSnapshot({
      data: [rawRow("000300"), rawRow("000985", { pe_percentile: null })],
      meta: { as_of: "2026-11-27", rows: 2, updated_at: "2026-11-27T21:10:00+08:00" },
    });
    expect(snapshot).not.toBeNull();
    expect(snapshot!.source).toBe("v1");
    expect(snapshot!.rows).toHaveLength(2);
    const row = snapshot!.rows[0];
    expect(row.index_code).toBe("000300");
    expect(row.close).toBeCloseTo(4016.29);
    expect(row.category).toBe("宽基");
    expect(row.pe_percentile).toBeCloseTo(42.1);
    expect(row.dividend_percentile).toBeCloseTo(61);
    expect(snapshot!.asOf).toBe("2026-11-27");
    expect(snapshot!.updatedAt).toBe("2026-11-27T21:10:00+08:00");
    expect(snapshot!.rows[1].pe_percentile).toBeNull();
  });

  it("旧接口（legacy）同样映射并标记来源", () => {
    const snapshot = mapIndexSnapshot({ data: [rawRow("000300")] }, "legacy");
    expect(snapshot!.source).toBe("legacy");
    expect(snapshot!.rows[0].name).toBe("指数000300");
  });

  it("非法/空响应返回 null", () => {
    expect(mapIndexSnapshot(null)).toBeNull();
    expect(mapIndexSnapshot({ data: [] })).toBeNull();
    expect(mapIndexSnapshot({ data: "oops" })).toBeNull();
  });
});

describe("fetchIndexSnapshot", () => {
  it("新接口可用时只请求一次（4 指标一次取全）", async () => {
    const fetchMock = stubFetch((url) =>
      url.startsWith("/api/v1/valuation/indices")
        ? { status: 200, body: { data: [rawRow("000300")], meta: { as_of: "2026-11-27" } } }
        : null,
    );
    const snapshot = await fetchIndexSnapshot({ window: "5y", metric: "pe_ttm" });
    expect(snapshot!.source).toBe("v1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("新接口不可用时降级旧接口", async () => {
    const fetchMock = stubFetch((url) =>
      url.startsWith("/api/valuation/indices")
        ? { status: 200, body: { data: [rawRow("000300")] } }
        : null,
    );
    const snapshot = await fetchIndexSnapshot({ window: "5y", metric: "pb" });
    expect(snapshot!.source).toBe("legacy");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain("metric=pb");
  });

  it("两个接口都失败返回 null（UI 显示占位）", async () => {
    const fetchMock = stubFetch(() => null);
    await expect(fetchIndexSnapshot({ window: "5y", metric: "pe_ttm" })).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("fetchIndexHistory / fetchBandHistories", () => {
  const historyBody = {
    data: {
      series: [
        { trade_date: "2026-01-02", value: 12.1 },
        { trade_date: "2026-01-09", value: 12.3 },
      ],
      stats: { pct: 42.1, mean: 12.2, sd: 0.1, p20: 11, p50: 12, p80: 13, min_value: 10, max_value: 14, sample_size: 200 },
    },
  };

  it("现网历史接口优先", async () => {
    const fetchMock = stubFetch((url) =>
      url.startsWith("/api/valuation/000300/history") ? { status: 200, body: historyBody } : null,
    );
    const history = await fetchIndexHistory("000300", "pb", "5y");
    expect(history!.series).toHaveLength(2);
    expect(history!.stats!.pct).toBeCloseTo(42.1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("现网失败后尝试 v1 历史接口", async () => {
    const fetchMock = stubFetch((url) =>
      url.startsWith("/api/v1/valuation/000300/history") ? { status: 200, body: historyBody } : null,
    );
    const history = await fetchIndexHistory("000300", "pe_ttm", "5y");
    expect(history).not.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("一次拉取 4 个指标的历史（指标 tab 本地切换的数据基础）", async () => {
    stubFetch((url) => (url.includes("/history") ? { status: 200, body: historyBody } : null));
    const histories = await fetchBandHistories("000300", "5y");
    expect(Object.keys(histories).sort()).toEqual(["dividend_yield_ttm", "erp", "pb", "pe_ttm"]);
    expect(histories.pe_ttm!.series).toHaveLength(2);
  });

  it("全部失败时返回空对象，不抛错", async () => {
    stubFetch(() => null);
    await expect(fetchBandHistories("000300", "5y")).resolves.toEqual({});
  });
});

describe("mapMviPayload / fetchMvi", () => {
  const latest = {
    as_of: "2026-11-27",
    mvi: 31.29,
    cheap_score: 68.71,
    risk_score: 66.92,
    zone: "低估",
    factors: { "PE 分位（反向）": 70.1 },
    weights: { "PE 分位（反向）": 0.1686 },
    contributions: { "PE 分位（反向）": 11.8 },
    risk_factors: { 波动率分位: 70.2 },
  };
  const history = [
    { as_of: "2026-11-13", mvi: 30.1, risk: 60.2 },
    { as_of: "2026-11-20", mvi: 30.8, risk: 62.5 },
    { as_of: "2026-11-27", mvi: 31.29, risk: 66.92 },
  ];

  it("解析 {data:{latest,history}} 新接口形态", () => {
    const mvi = mapMviPayload({ data: { latest, history } })!;
    expect(mvi.latest!.mvi).toBeCloseTo(31.29);
    expect(mvi.latest!.cheap_score).toBeCloseTo(68.71);
    expect(mvi.latest!.zone).toBe("低估");
    expect(mvi.history).toHaveLength(3);
    expect(mvi.history.at(-1)!.as_of).toBe("2026-11-27");
  });

  it("兼容纯序列数组（仅 history）", () => {
    const mvi = mapMviPayload({ data: history })!;
    expect(mvi.latest!.mvi).toBeCloseTo(31.29);
    expect(mvi.history).toHaveLength(3);
  });

  it("兼容旧 overview.meta.mvi 形态", () => {
    const mvi = mapMviPayload({ latest, history })!;
    expect(mvi.latest!.mvi).toBeCloseTo(31.29);
  });

  it("字段别名（date/value/risk_score）也能解析", () => {
    const mvi = mapMviPayload({
      data: [{ date: "2026-11-27", value: 31.29, risk_score: 66.92 }],
    })!;
    expect(mvi.history[0].as_of).toBe("2026-11-27");
    expect(mvi.history[0].mvi).toBeCloseTo(31.29);
    expect(mvi.history[0].risk).toBeCloseTo(66.92);
  });

  it("空响应返回 null", () => {
    expect(mapMviPayload(null)).toBeNull();
    expect(mapMviPayload({ data: {} })).toBeNull();
  });

  it("fetchMvi 新接口优先，失败降级 overview.meta.mvi", async () => {
    const first = stubFetch((url) =>
      url.startsWith("/api/v1/market/mvi?") ? { status: 200, body: { data: { latest, history } } } : null,
    );
    const mvi = await fetchMvi("5y");
    expect(mvi!.latest!.mvi).toBeCloseTo(31.29);
    expect(first).toHaveBeenCalledTimes(1);

    stubFetch((url) =>
      url.startsWith("/api/valuation/overview")
        ? { status: 200, body: { data: [], meta: { mvi: { latest, history } } } }
        : null,
    );
    const fallback = await fetchMvi("5y");
    expect(fallback!.latest!.mvi).toBeCloseTo(31.29);
  });
});

describe("mapMviOverlay / fetchMviOverlay", () => {
  it("解析指数收盘序列与 MVI 序列，兼容字段别名", () => {
    const overlay = mapMviOverlay({
      data: {
        index_code: "000985",
        index_name: "中证全指",
        series: [
          { trade_date: "2024-01-02", close: 4200.1 },
          { date: "2024-01-03", value: 4210.5 },
          { date: "2024-01-04", price: 0 },
        ],
        mvi_series: [{ as_of: "2024-01-05", value: 30.2 }],
      },
    })!;
    expect(overlay.code).toBe("000985");
    expect(overlay.name).toBe("中证全指");
    expect(overlay.series.map((point) => point.date)).toEqual(["2024-01-02", "2024-01-03"]);
    expect(overlay.mvi).toHaveLength(1);
    expect(overlay.mvi[0].mvi).toBeCloseTo(30.2);
    expect(overlay.missing).toBe(false);
  });

  it("后端标注 missing 时保留 MVI 序列（不视为失败）", () => {
    const overlay = mapMviOverlay({
      data: {
        index_code: "000985",
        name: "中证全指",
        series: [],
        mvi: [{ as_of: "2024-01-05", mvi: 30.2, risk_score: 60.1 }],
        missing: true,
      },
    })!;
    expect(overlay.missing).toBe(true);
    expect(overlay.series).toEqual([]);
    expect(overlay.mvi).toHaveLength(1);
    expect(overlay.mvi[0].risk).toBeCloseTo(60.1);
  });

  it("无有效序列时返回 null", () => {
    expect(mapMviOverlay({ data: { series: [] } })).toBeNull();
    expect(mapMviOverlay(null)).toBeNull();
  });

  it("fetchMviOverlay 附带 index 参数", async () => {
    const fetchMock = stubFetch((url) =>
      url.startsWith("/api/v1/market/mvi/overlay")
        ? { status: 200, body: { data: { index_code: "000985", series: [{ date: "2024-01-02", close: 4200 }] } } }
        : null,
    );
    const overlay = await fetchMviOverlay("000985");
    expect(overlay!.series).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("index=000985");
  });
});

describe("deriveProxyCards", () => {
  it("按固定顺序从快照行推导 5 张宽基卡，缺行自动跳过", () => {
    const rows = [
      mapRow("000300"),
      mapRow("000905"),
      mapRow("000016"),
      mapRow("000510"),
      mapRow("000852"),
    ];
    const cards = deriveProxyCards(rows, "5y");
    expect(cards.map((card) => card.index_code)).toEqual([...PROXY_CODES]);
    expect(cards[0].window).toBe("5y");
    expect(cards[0].pe).toBeCloseTo(13.4);
  });

  it("指标选择器常量符合产品定义", () => {
    expect(BAND_INDEX_OPTIONS.map((item) => item.code)).toEqual(["000300", "000510", "000016", "000985"]);
    expect(DEFAULT_BAND_INDEX).toBe("000300");
    // 默认 000300：000985 无可用点位历史，默认打开会命中「数据建设中」。
    expect(MVI_OVERLAY_INDEX_OPTIONS.map((item) => item.code)).toEqual(["000300", "000510", "000016", "000985"]);
    expect(DEFAULT_MVI_OVERLAY_INDEX).toBe("000300");
  });
});

function mapRow(code: string) {
  return mapIndexSnapshot({ data: [rawRow(code)] })!.rows[0];
}
