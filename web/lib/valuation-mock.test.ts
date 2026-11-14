import { describe, expect, it } from "vitest";
import {
  BROAD_INDEX_CODES,
  MOCK_BROAD_INDEX_ROWS,
  MOCK_INDEX_ROWS,
  MOCK_MARKET_CARDS,
  changeClass,
  filterIndexRows,
  formatNumber,
  formatPercentile,
  formatPlainPct,
  formatSignedPct,
  levelClass,
  levelFromPercentile,
  percentileClass,
} from "./valuation-mock";

const REQUIRED_NAMES = [
  "沪深300",
  "中证500",
  "中证1000",
  "上证50",
  "创业板指",
  "科创50",
  "中证A500",
  "中证红利",
  "中证中药",
  "中证白酒",
  "中证银行",
  "中证医疗",
] as const;

describe("MOCK_INDEX_ROWS", () => {
  it("包含任务要求的 12 只指数且顺序稳定", () => {
    expect(MOCK_INDEX_ROWS.map((row) => row.name)).toEqual(REQUIRED_NAMES);
    expect(new Set(MOCK_INDEX_ROWS.map((row) => row.index_code)).size).toBe(12);
  });

  it("字段与 IndexQuoteRow 一致；缺失估值用 null 而不是 0", () => {
    for (const row of MOCK_INDEX_ROWS) {
      expect(row.index_code).toMatch(/^[0-9A-Z]+$/);
      expect(["宽基", "行业", "主题", "策略", "其他"]).toContain(row.category);
      expect(typeof row.has_etf).toBe("boolean");
      expect(typeof row.has_valuation).toBe("boolean");
      expect(row.trade_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);

      if (!row.has_valuation) {
        expect(row.pe_ttm).toBeNull();
        expect(row.pb).toBeNull();
        expect(row.pe_percentile).toBeNull();
        expect(row.pb_percentile).toBeNull();
        expect(row.dividend_yield_pct).toBeNull();
        expect(row.risk_premium_pct).toBeNull();
      }

      if (row.pe_percentile != null) {
        expect(row.pe_percentile).toBeGreaterThanOrEqual(0);
        expect(row.pe_percentile).toBeLessThanOrEqual(100);
      }
      if (row.pb_percentile != null) {
        expect(row.pb_percentile).toBeGreaterThanOrEqual(0);
        expect(row.pb_percentile).toBeLessThanOrEqual(100);
      }
    }
  });

  it("宽基表固定 8 行且全部来自 mock 数据", () => {
    expect(BROAD_INDEX_CODES).toHaveLength(8);
    expect(MOCK_BROAD_INDEX_ROWS).toHaveLength(8);
    expect(MOCK_BROAD_INDEX_ROWS.map((row) => row.name)).toEqual([
      "沪深300",
      "中证500",
      "中证1000",
      "上证50",
      "创业板指",
      "科创50",
      "中证A500",
      "中证红利",
    ]);
    for (const code of BROAD_INDEX_CODES) {
      expect(MOCK_INDEX_ROWS.some((row) => row.index_code === code)).toBe(true);
    }
  });

  it("全市场卡片覆盖 4 个板块", () => {
    expect(MOCK_MARKET_CARDS.map((card) => card.board)).toEqual([
      "all",
      "main",
      "chinext",
      "star",
    ]);
    for (const card of MOCK_MARKET_CARDS) {
      expect(card.as_of).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(card.sample_size).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("filterIndexRows", () => {
  it("按名称或代码搜索，忽略大小写与首尾空格", () => {
    expect(filterIndexRows(MOCK_INDEX_ROWS, { query: " 300 " }).map((r) => r.index_code))
      .toEqual(["000300"]);
    expect(filterIndexRows(MOCK_INDEX_ROWS, { query: "000" })).toHaveLength(7);
    expect(filterIndexRows(MOCK_INDEX_ROWS, { query: "930641" }).map((r) => r.name))
      .toEqual(["中证中药"]);
    expect(filterIndexRows(MOCK_INDEX_ROWS, { query: "中证银行" }).map((r) => r.index_code))
      .toEqual(["399986"]);
  });

  it("按类别过滤", () => {
    const broad = filterIndexRows(MOCK_INDEX_ROWS, { category: "宽基" });
    expect(broad.map((r) => r.name)).toEqual([
      "沪深300",
      "中证500",
      "中证1000",
      "上证50",
      "创业板指",
      "科创50",
      "中证A500",
    ]);
    expect(filterIndexRows(MOCK_INDEX_ROWS, { category: "all" })).toHaveLength(12);
  });

  it("有 ETF / 仅估值 两个开关可独立生效", () => {
    const withEtf = filterIndexRows(MOCK_INDEX_ROWS, { hasEtfOnly: true });
    expect(withEtf.length).toBeLessThan(MOCK_INDEX_ROWS.length);
    expect(withEtf.every((r) => r.has_etf)).toBe(true);

    const withValuation = filterIndexRows(MOCK_INDEX_ROWS, { valuationOnly: true });
    expect(withValuation.length).toBeLessThan(MOCK_INDEX_ROWS.length);
    expect(withValuation.every((r) => r.has_valuation)).toBe(true);
  });

  it("组合筛选无匹配时返回空数组", () => {
    expect(
      filterIndexRows(MOCK_INDEX_ROWS, {
        query: "沪深",
        category: "行业",
        hasEtfOnly: true,
        valuationOnly: true,
      }),
    ).toEqual([]);
  });
});

describe("格式化", () => {
  it("小数分位转百分比，缺失显示占位符", () => {
    expect(formatPercentile(12.34)).toBe("12.34%");
    expect(formatPercentile(100)).toBe("100.00%");
    expect(formatPercentile(null)).toBe("—");
    expect(formatPercentile(Number.NaN)).toBe("—");
  });

  it("数字千分位，缺失显示占位符", () => {
    expect(formatNumber(4016.29)).toBe("4,016.29");
    expect(formatNumber(5210, 0)).toBe("5,210");
    expect(formatNumber(null)).toBe("—");
  });

  it("涨跌幅带符号，零值不带正号", () => {
    expect(formatSignedPct(2.07)).toBe("+2.07%");
    expect(formatSignedPct(-0.68)).toBe("-0.68%");
    expect(formatSignedPct(0)).toBe("0.00%");
    expect(formatSignedPct(null)).toBe("—");
  });

  it("股息率等普通百分比不带正号", () => {
    expect(formatPlainPct(3.68)).toBe("3.68%");
    expect(formatPlainPct(null)).toBe("—");
  });
});

describe("语气色使用现有语义 token", () => {
  it("涨跌只用 text-up / text-down，其余走 muted", () => {
    expect(changeClass(1)).toBe("text-up");
    expect(changeClass(-1)).toBe("text-down");
    expect(changeClass(0)).toBe("text-muted-foreground");
    expect(changeClass(null)).toBe("text-muted-foreground");
  });

  it("估值分位低=success、中=warning、高=destructive", () => {
    expect(percentileClass(0.137)).toBe("text-success");
    expect(percentileClass(0.5)).toBe("text-warning");
    expect(percentileClass(0.795)).toBe("text-destructive");
    expect(percentileClass(null)).toBe("text-muted-foreground");
  });

  it("分位到估值等级映射", () => {
    expect(levelFromPercentile(0.1)).toBe("低估");
    expect(levelFromPercentile(0.5)).toBe("中性");
    expect(levelFromPercentile(0.9)).toBe("高估");
    expect(levelFromPercentile(null)).toBeNull();
  });

  it("估值等级文字色走语义 token", () => {
    expect(levelClass("低估")).toBe("text-success");
    expect(levelClass("中性")).toBe("text-warning");
    expect(levelClass("高估")).toBe("text-destructive");
    expect(levelClass(null)).toBe("text-muted-foreground");
  });
});
