import { describe, expect, it } from "vitest";
import { getChartTheme } from "./chart-theme";
import {
  DIVIDEND_QUADRANTS,
  alignPriceToDates,
  buildMviOverlayOption,
  buildValuationPriceOption,
  buildMviTrendOption,
  dividendPoints,
  dividendQuadrant,
  isoWeekKey,
  isDividendRow,
  isWeekendDate,
  linearFit,
  logFit,
  medianOf,
  positiveLogRange,
  sampleLogLine,
  weeklyLast,
  zoneOfMvi,
} from "./valuation-chart-model";
import type { IndexQuoteRow, MviPoint } from "./valuation-types";

const theme = getChartTheme(false);

function row(overrides: Partial<IndexQuoteRow> & { index_code: string; name: string }): IndexQuoteRow {
  return {
    category: "策略",
    publisher: null,
    has_etf: true,
    has_valuation: true,
    trade_date: "2026-11-27",
    close: 5000,
    change_pct: 0.5,
    change_52w_pct: 3.2,
    distance_from_high_pct: -2.1,
    pe_ttm: 8,
    pe_percentile: 30,
    pb: 1.2,
    pb_percentile: 20,
    dividend_yield_pct: 4.5,
    risk_premium_pct: 3.1,
    dividend_percentile: 80,
    fund_aum: 1e10,
    fund_count: 4,
    ...overrides,
  };
}

describe("红利指数取点", () => {
  it("只取名称含红利/股息且有完整字段的指数", () => {
    const rows = [
      row({ index_code: "000922", name: "中证红利" }),
      row({ index_code: "000300", name: "沪深300" }),
      row({ index_code: "930000", name: "红利低波", pb: null }),
      row({ index_code: "930001", name: "股息龙头", dividend_yield_pct: null }),
      row({ index_code: "930002", name: "红利质量", pb: 0 }),
    ];
    const points = dividendPoints(rows, "absolute");
    expect(points.map((point) => point.code)).toEqual(["000922"]);
    expect(isDividendRow(rows[1])).toBe(false);
  });

  it("绝对模式用 PB/股息率当前值，按基金规模降序", () => {
    const points = dividendPoints(
      [
        row({ index_code: "A", name: "红利A", pb: 0.9, dividend_yield_pct: 5.1, fund_aum: 2e9 }),
        row({ index_code: "B", name: "红利B", pb: 1.4, dividend_yield_pct: 4.2, fund_aum: 8e9 }),
      ],
      "absolute",
    );
    expect(points.map((point) => point.code)).toEqual(["B", "A"]);
    expect(points[0].x).toBeCloseTo(1.4);
    expect(points[0].y).toBeCloseTo(4.2);
  });

  it("相对模式用 PB / 股息率 5y 分位，缺分位或分位为 null 的不入图", () => {
    const points = dividendPoints(
      [
        row({ index_code: "A", name: "红利A", pb_percentile: 18.2, dividend_percentile: 82.1 }),
        row({ index_code: "B", name: "红利B", pb_percentile: null, dividend_percentile: 70 }),
        row({ index_code: "C", name: "红利C", pb_percentile: 12, dividend_percentile: null }),
      ],
      "relative",
    );
    expect(points).toHaveLength(1);
    expect(points[0].x).toBeCloseTo(18.2);
    expect(points[0].y).toBeCloseTo(82.1);
  });

  it("无规模时 size 记 0（不产生 NaN 气泡）", () => {
    const points = dividendPoints([row({ index_code: "A", name: "红利A", fund_aum: null })], "absolute");
    expect(points[0].size).toBe(0);
  });
});

describe("中位数与回归", () => {
  it("medianOf 处理奇偶与空数组", () => {
    expect(medianOf([3, 1, 2])).toBe(2);
    expect(medianOf([1, 2, 3, 4])).toBe(2.5);
    expect(medianOf([])).toBeNull();
  });

  it("linearFit 还原 y = 2x + 1 且 R²=1", () => {
    const fit = linearFit([
      { x: 1, y: 3 },
      { x: 2, y: 5 },
      { x: 3, y: 7 },
      { x: 4, y: 9 },
    ])!;
    expect(fit.slope).toBeCloseTo(2);
    expect(fit.intercept).toBeCloseTo(1);
    expect(fit.r2).toBeCloseTo(1);
    expect(fit.equation).toContain("y = 2.000x + 1.000");
  });

  it("logFit 还原 y = 2·ln(x) + 1（对数轴口径）", () => {
    const fit = logFit(
      [1, 2, 3, 4, 5].map((x) => ({ x, y: 2 * Math.log(x) + 1 })),
    )!;
    expect(fit.slope).toBeCloseTo(2);
    expect(fit.intercept).toBeCloseTo(1);
    expect(fit.r2).toBeCloseTo(1);
    expect(fit.equation).toContain("ln(x)");
    expect(logFit([{ x: 0, y: 1 }, { x: 1, y: 2 }, { x: 2, y: 3 }])).toBeNull();
  });

  it("logFit 可用业务字段名替换方程里的 x/y（ROE = a·ln(PE) + b）", () => {
    const fit = logFit(
      [8, 10, 12, 15].map((x) => ({ x, y: 1.5 * Math.log(x) + 0.4 })),
      { xName: "PE", yName: "ROE" },
    )!;
    expect(fit.equation).toContain("ROE =");
    expect(fit.equation).toContain("ln(PE)");
    expect(fit.equation).not.toContain("ln(x)");
  });

  it("sampleLogLine 在对数尺度均匀采样且落在回归线上", () => {
    const fit = logFit([1, 10, 100].map((x) => ({ x, y: 2 * Math.log(x) + 1 })))!;
    const samples = sampleLogLine([{ x: 1 }, { x: 100 }], fit, 5);
    expect(samples).toHaveLength(5);
    expect(samples[0][0]).toBeCloseTo(1);
    expect(samples.at(-1)![0]).toBeCloseTo(100);
    for (const [x, y] of samples) {
      expect(y).toBeCloseTo(2 * Math.log(x) + 1);
    }
  });

  it("positiveLogRange 恒为正数并留 padding", () => {
    const [low, high] = positiveLogRange([1.2, 2.4]);
    expect(low).toBeGreaterThan(0);
    expect(low).toBeLessThan(1.2);
    expect(high).toBeGreaterThan(2.4);
    expect(positiveLogRange([])[0]).toBeGreaterThan(0);
  });
});

describe("四象限与分位", () => {
  it("四象限定义覆盖 0~100 且互不重叠", () => {
    expect(DIVIDEND_QUADRANTS).toHaveLength(4);
    const area = DIVIDEND_QUADRANTS.reduce(
      (sum, quadrant) => sum + (quadrant.xMax - quadrant.xMin) * (quadrant.yMax - quadrant.yMin),
      0,
    );
    expect(area).toBe(100 * 100);
  });

  it("象限归类：低 PB 分位 + 高股息分位 = 最具吸引力", () => {
    expect(dividendQuadrant(18, 82)).toBe("cheap_high_yield");
    expect(dividendQuadrant(82, 18)).toBe("rich_low_yield");
    expect(dividendQuadrant(80, 80)).toBe("rich_high_yield");
    expect(dividendQuadrant(20, 20)).toBe("cheap_low_yield");
    // 边界 50 归入「高」侧
    expect(dividendQuadrant(50, 50)).toBe("rich_high_yield");
  });

  it("zoneOfMvi 与后端 compute_mvi.py 阈值一致", () => {
    expect(zoneOfMvi(19.99)).toBe("极度低估");
    expect(zoneOfMvi(20)).toBe("低估");
    expect(zoneOfMvi(40)).toBe("合理");
    expect(zoneOfMvi(60)).toBe("高估");
    expect(zoneOfMvi(80)).toBe("极度高估");
    expect(zoneOfMvi(Number.NaN)).toBe("—");
  });
});

describe("MVI 周频平滑", () => {
  it("isoWeekKey 按 ISO 周归属（跨年边界）", () => {
    expect(isoWeekKey("2024-01-01")).toBe("2024-W01");
    expect(isoWeekKey("2024-01-07")).toBe("2024-W01");
    expect(isoWeekKey("2024-01-08")).toBe("2024-W02");
    expect(isoWeekKey("2023-12-31")).toBe("2023-W52");
    expect(isoWeekKey("bad-date")).toBeNull();
  });

  it("同周只保留最后一个交易日，周末点直接丢弃", () => {
    const points: MviPoint[] = [
      { as_of: "2024-01-01", mvi: 30, risk: 60 },
      { as_of: "2024-01-05", mvi: 32, risk: 61 },
      { as_of: "2024-01-06", mvi: 99, risk: 99 }, // 周六脏点
      { as_of: "2024-01-08", mvi: 33, risk: 62 },
    ];
    const weekly = weeklyLast(points);
    expect(weekly.map((point) => point.as_of)).toEqual(["2024-01-05", "2024-01-08"]);
    expect(weekly[0].mvi).toBe(32);
    expect(isWeekendDate("2024-01-06")).toBe(true);
    expect(isWeekendDate("2024-01-05")).toBe(false);
  });
});

describe("ECharts option 构造", () => {
  const mviPoints: MviPoint[] = [
    { as_of: "2024-01-01", mvi: 20, risk: 50 },
    { as_of: "2024-01-05", mvi: 35, risk: 55 },
    { as_of: "2024-01-06", mvi: null, risk: 55 },
    { as_of: "2024-01-10", mvi: 42, risk: 60 },
  ];

  it("MVI 小走势图：0~100 固定轴、5 段分位带背景、hover 带 zone", () => {
    const option = buildMviTrendOption(mviPoints, theme);
    const series = (option.series as Array<Record<string, unknown>>)[0];
    expect((option.yAxis as Record<string, unknown>).min).toBe(0);
    expect((option.yAxis as Record<string, unknown>).max).toBe(100);
    expect((series.data as number[]).length).toBe(2); // 周末点丢弃
    expect((series.markArea as Record<string, unknown[]>).data).toHaveLength(5);
    const formatter = (option.tooltip as Record<string, unknown>).formatter as (
      params: Array<{ dataIndex: number }>,
    ) => string;
    const text = formatter([{ dataIndex: 1 }]);
    expect(text).toContain("2024-01-10");
    expect(text).toContain("MVI 42.00");
    expect(text).toContain("合理");
  });

  it("MVI 双轴 overlay：time 轴 + 两个 y 轴 + sky/amber 两色", () => {
    const option = buildMviOverlayOption({
      mvi: mviPoints,
      indexPoints: [
        { date: "2024-01-02", close: 4200 },
        { date: "2024-01-10", close: 4350 },
      ],
      indexName: "中证全指",
      theme,
    });
    expect((option.xAxis as Record<string, unknown>).type).toBe("time");
    expect(option.yAxis as unknown[]).toHaveLength(2);
    const series = option.series as Array<Record<string, unknown>>;
    expect(series).toHaveLength(2);
    expect(series[0].yAxisIndex).toBe(0);
    expect(series[1].yAxisIndex).toBe(1);
    expect(series[0].data).toHaveLength(2);
    expect(series[1].data).toHaveLength(2);
    expect((series[0].lineStyle as Record<string, unknown>).color).toBe(theme.palette[0]);
    expect((series[1].lineStyle as Record<string, unknown>).color).toBe(theme.palette[2]);
    expect(((option.legend as Record<string, unknown>).data as string[])).toEqual(["MVI", "中证全指"]);
  });
});

describe("估值 × 点位双轴图", () => {
  it("alignPriceToDates 取「≤目标日」的最后一个收盘价（周频估值对齐日频行情）", () => {
    const prices = [
      { trade_date: "2024-01-01", close: 100 },
      { trade_date: "2024-01-02", close: 101 },
      { trade_date: "2024-01-05", close: 105 },
      { trade_date: "2024-01-08", close: 108 },
    ];
    expect(
      alignPriceToDates(["2024-01-01", "2024-01-04", "2024-01-05", "2024-01-09"], prices),
    ).toEqual([100, 101, 105, 108]);
    // 估值首日早于行情首日 -> null（不向前填充未来价格）
    expect(alignPriceToDates(["2023-12-31", "2024-01-02"], prices)).toEqual([null, 101]);
  });

  it("双轴 option：两个 y 轴、估值+点位两条线、P20/P50/P80 参考线", () => {
    const option = buildValuationPriceOption({
      series: [
        { trade_date: "2024-01-01", value: 11.2 },
        { trade_date: "2024-01-08", value: 11.6 },
      ],
      priceSeries: [
        { trade_date: "2024-01-01", close: 24000 },
        { trade_date: "2024-01-08", close: 24500 },
      ],
      stats: { p20: 10.2, p50: 11.7, p80: 13.1, mean: 11.8, sd: 1.1, sample_size: 260 },
      metricLabel: "PE",
      unit: "x",
      mode: "pct",
      sigma: 1,
      showBandArea: true,
      theme,
    });
    expect(option.yAxis as unknown[]).toHaveLength(2);
    const series = option.series as Array<Record<string, unknown>>;
    expect(series).toHaveLength(2);
    expect(series[0].yAxisIndex).toBe(0);
    expect(series[1].yAxisIndex).toBe(1);
    const markLine = series[0].markLine as Record<string, unknown>;
    expect(markLine.data as unknown[]).toHaveLength(3);
    expect((series[0].markArea as Record<string, unknown[]>).data).toHaveLength(1);
  });

  it("分位带底色开关关闭时无 markArea；无点位数据时只留估值线", () => {
    const base = {
      series: [{ trade_date: "2024-01-01", value: 11.2 }],
      stats: { p20: 10.2, p50: 11.7, p80: 13.1, mean: 11.8, sd: 1.1, sample_size: 260 },
      metricLabel: "PE",
      unit: "x",
      mode: "pct" as const,
      sigma: 1,
      theme,
    };
    const noBand = buildValuationPriceOption({ ...base, priceSeries: [], showBandArea: false });
    const series = noBand.series as Array<Record<string, unknown>>;
    expect(series).toHaveLength(1);
    expect(series[0].markArea).toBeUndefined();

    const withPrice = buildValuationPriceOption({
      ...base,
      priceSeries: [{ trade_date: "2024-01-01", close: 24000 }],
      showBandArea: false,
    });
    expect((withPrice.series as unknown[])).toHaveLength(2);
  });
});
