/**
 * /valuation 首页的 mock 数据与纯函数工具。
 *
 * 用途：P0-T4 页面骨架阶段，在估值 API / 预计算表落地前先锁定前端契约与交互。
 * 数据仅用于展示，不代表真实行情；接入估值 API 后整体替换，
 * 但下方 `filterIndexRows` / 格式化 / 语气色函数保持为唯一入口，避免组件里再写一份。
 */

import type {
  IndexCategory,
  IndexQuoteRow,
  MarketValuationCard,
  ValuationLevel,
} from "./valuation-types";

/** mock 数据的统一截止日，接入 API 后由响应 meta.as_of 提供。 */
export const VALUATION_AS_OF = "2026-11-13";

/**
 * 12 只示例指数：前 8 只用于首页「宽基指数」表，后 4 只用于展示行业/主题分类与筛选。
 *
 * 分类说明：中证红利是策略指数（不是严格意义的宽基），但它在产品首页的核心指数
 * 观察列表里，故 `BROAD_INDEX_CODES` 仍把它算作 8 行之一；类别字段保持真实分类，
 * 这样「类别=策略」筛选能筛出它。
 */
export const MOCK_INDEX_ROWS: readonly IndexQuoteRow[] = [
  {
    index_code: "000300",
    name: "沪深300",
    category: "宽基",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 4016.29,
    change_pct: -0.68,
    change_52w_pct: -14.58,
    distance_from_high_pct: -22.4,
    pe_ttm: 20.47,
    pe_percentile: 15.77,
    pb: 2.1,
    pb_percentile: 13.63,
    dividend_yield_pct: 2.61,
    risk_premium_pct: 1.0,
  },
  {
    index_code: "000905",
    name: "中证500",
    category: "宽基",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 6465.48,
    change_pct: -2.1,
    change_52w_pct: -12.1,
    distance_from_high_pct: -18.7,
    pe_ttm: 30.61,
    pe_percentile: 59.04,
    pb: 2.29,
    pb_percentile: 57.76,
    dividend_yield_pct: 1.47,
    risk_premium_pct: -0.14,
  },
  {
    index_code: "000852",
    name: "中证1000",
    category: "宽基",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 6357.26,
    change_pct: -2.76,
    change_52w_pct: -16.25,
    distance_from_high_pct: -14.2,
    pe_ttm: 38.11,
    pe_percentile: 57.35,
    pb: 2.44,
    pb_percentile: 28.45,
    dividend_yield_pct: 1.18,
    risk_premium_pct: -0.43,
  },
  {
    index_code: "000016",
    name: "上证50",
    category: "宽基",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 2775.02,
    change_pct: 0.11,
    change_52w_pct: -9.72,
    distance_from_high_pct: -20.1,
    pe_ttm: 18.64,
    pe_percentile: 61.05,
    pb: 2.15,
    pb_percentile: 52.08,
    dividend_yield_pct: 2.92,
    risk_premium_pct: 1.31,
  },
  {
    index_code: "399006",
    name: "创业板指",
    category: "宽基",
    publisher: "深证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 2426.08,
    change_pct: -3.32,
    change_52w_pct: -24.23,
    distance_from_high_pct: -38.5,
    pe_ttm: 44.81,
    pe_percentile: 41.50,
    pb: 4.46,
    pb_percentile: 43.93,
    dividend_yield_pct: 1.19,
    risk_premium_pct: -0.42,
  },
  {
    index_code: "000688",
    name: "科创50",
    category: "宽基",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 1279.66,
    change_pct: -2.3,
    change_52w_pct: -8.55,
    distance_from_high_pct: -52.8,
    pe_ttm: 62.3,
    // 科创50 历史较短：有 PE/PB，但分位样本不足 → null（禁止填 0）。
    pe_percentile: null,
    pb: 6.06,
    pb_percentile: null,
    dividend_yield_pct: 0.31,
    risk_premium_pct: -1.3,
  },
  {
    index_code: "000510",
    name: "中证A500",
    category: "宽基",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 5321.44,
    change_pct: -1.02,
    change_52w_pct: -11.22,
    distance_from_high_pct: -12.6,
    pe_ttm: 17.92,
    pe_percentile: 8.31,
    pb: 1.98,
    pb_percentile: 7.42,
    dividend_yield_pct: 2.88,
    risk_premium_pct: 1.27,
  },
  {
    index_code: "000922",
    name: "中证红利",
    category: "策略",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 5210.33,
    change_pct: -0.44,
    change_52w_pct: -3.21,
    distance_from_high_pct: -6.4,
    pe_ttm: 12.44,
    pe_percentile: 22.15,
    pb: 1.52,
    pb_percentile: 31.02,
    dividend_yield_pct: 4.92,
    risk_premium_pct: 3.31,
  },
  {
    index_code: "930641",
    name: "中证中药",
    category: "主题",
    publisher: "中证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 8458.56,
    change_pct: -0.29,
    change_52w_pct: -17.82,
    distance_from_high_pct: -53.0,
    pe_ttm: 23.27,
    pe_percentile: 13.68,
    pb: 2.02,
    pb_percentile: 2.72,
    dividend_yield_pct: 3.68,
    risk_premium_pct: 2.07,
  },
  {
    index_code: "399997",
    name: "中证白酒",
    category: "行业",
    publisher: "深证指数",
    // mock 中刻意给一只无跟踪 ETF，便于验证「有 ETF」筛选；真实数据以接口为准。
    has_etf: false,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 6808.51,
    change_pct: 2.03,
    change_52w_pct: -32.58,
    distance_from_high_pct: -62.3,
    pe_ttm: 44.16,
    pe_percentile: 79.50,
    pb: 2.64,
    pb_percentile: 4.94,
    dividend_yield_pct: 4.47,
    risk_premium_pct: 2.86,
  },
  {
    index_code: "399986",
    name: "中证银行",
    category: "行业",
    publisher: "深证指数",
    has_etf: true,
    has_valuation: true,
    trade_date: VALUATION_AS_OF,
    close: 6120.44,
    change_pct: 0.32,
    change_52w_pct: 8.41,
    distance_from_high_pct: -5.8,
    pe_ttm: 6.92,
    pe_percentile: 71.20,
    pb: 0.68,
    pb_percentile: 44.10,
    dividend_yield_pct: 4.12,
    risk_premium_pct: 2.51,
  },
  {
    index_code: "399989",
    name: "中证医疗",
    category: "行业",
    publisher: "深证指数",
    has_etf: true,
    // mock 中刻意给一只「仅行情」指数，便于验证「仅估值」筛选与 null 占位。
    has_valuation: false,
    trade_date: VALUATION_AS_OF,
    close: 7210.11,
    change_pct: -1.44,
    change_52w_pct: -21.05,
    distance_from_high_pct: -58.1,
    pe_ttm: null,
    pe_percentile: null,
    pb: null,
    pb_percentile: null,
    dividend_yield_pct: null,
    risk_premium_pct: null,
  },
] as const;

/** 首页「宽基指数」表固定 8 行；顺序即产品约定的核心观察顺序。 */
export const BROAD_INDEX_CODES = [
  "000300",
  "000905",
  "000852",
  "000016",
  "399006",
  "000688",
  "000510",
  "000922",
] as const;

/** 由代码查行，保证宽基表与全部指数表使用同一份数据。 */
export const MOCK_BROAD_INDEX_ROWS: readonly IndexQuoteRow[] = BROAD_INDEX_CODES.map(
  (code) => {
    const row = MOCK_INDEX_ROWS.find((item) => item.index_code === code);
    if (!row) throw new Error(`valuation mock 缺少指数 ${code}`);
    return row;
  },
);

/** 全市场 4 张板块卡；科创板历史不足时刻意保留 null 分位。 */
export const MOCK_MARKET_CARDS: readonly MarketValuationCard[] = [
  {
    board: "all",
    label: "全市场",
    pe: 44.43,
    pe_percentile: 68.30,
    pb: 2.61,
    pb_percentile: 38.12,
    level: "中性",
    as_of: VALUATION_AS_OF,
    sample_size: 5210,
    history_days: 2800,
  },
  {
    board: "main",
    label: "主板",
    pe: 34.65,
    pe_percentile: 56.73,
    pb: 2.15,
    pb_percentile: 16.43,
    level: "中性",
    as_of: VALUATION_AS_OF,
    sample_size: 3100,
    history_days: 2800,
  },
  {
    board: "chinext",
    label: "创业板",
    pe: 59.95,
    pe_percentile: 66.78,
    pb: 3.14,
    pb_percentile: 21.98,
    level: "中性",
    as_of: VALUATION_AS_OF,
    sample_size: 1100,
    history_days: 2700,
  },
  {
    board: "star",
    label: "科创板",
    pe: 70.22,
    pe_percentile: null,
    pb: 3.54,
    pb_percentile: null,
    level: null,
    as_of: VALUATION_AS_OF,
    sample_size: 580,
    history_days: 118,
  },
] as const;

/** 类别筛选值：`all` 表示不过滤。 */
export type IndexCategoryFilter = IndexCategory | "all";

/** 全部指数表的筛选条件。 */
export interface IndexRowFilter {
  query?: string;
  category?: IndexCategoryFilter;
  hasEtfOnly?: boolean;
  valuationOnly?: boolean;
}

/**
 * 全部指数表的唯一筛选入口。
 *
 * 搜索同时匹配名称与代码（忽略大小写与首尾空格）；多个条件之间是 AND 关系。
 * 返回新数组，不修改入参，便于 `useMemo` 直接消费。
 */
export function filterIndexRows(
  rows: readonly IndexQuoteRow[],
  filter: IndexRowFilter = {},
): IndexQuoteRow[] {
  const query = filter.query?.trim().toLowerCase() ?? "";
  const category = filter.category ?? "all";

  return rows.filter((row) => {
    if (category !== "all" && row.category !== category) return false;
    if (filter.hasEtfOnly && !row.has_etf) return false;
    if (filter.valuationOnly && !row.has_valuation) return false;
    if (!query) return true;
    return (
      row.name.toLowerCase().includes(query) ||
      row.index_code.toLowerCase().includes(query)
    );
  });
}

/** 缺失值的统一占位符（产品规范：不显示 0 / NaN / null）。 */
export const EMPTY_DISPLAY = "—";

/** 千分位数字；`digits=0` 用于样本数等整数。 */
export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_DISPLAY;
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** 不带正号的百分比，用于股息率等水平值。 */
export function formatPlainPct(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_DISPLAY;
  return `${value.toFixed(digits)}%`;
}

/** 带正负号的百分比，用于涨跌幅 / 风险溢价。 */
export function formatSignedPct(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_DISPLAY;
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/** 0~1 小数分位 → 百分比。 */
export function formatPercentile(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_DISPLAY;
  return `${value.toFixed(digits)}%`;
}

/**
 * 涨跌方向色：仅方向性涨跌使用 `text-up` / `text-down`。
 * 0、缺失、非有限值一律中性，避免把「无变化」误读成涨跌。
 */
export function changeClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) {
    return "text-muted-foreground";
  }
  return value > 0 ? "text-up" : "text-down";
}

/**
 * 估值分位色：低分位=便宜=success，中间=warning，高分位=高估=destructive。
 * 与涨跌色解耦（分位不是当日涨跌），全部走语义 token。
 */
export function percentileClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "text-muted-foreground";
  }
  if (value <= 0.3) return "text-success";
  if (value >= 0.7) return "text-destructive";
  return "text-warning";
}

/** 分位 → 估值等级；样本不足时为 null（展示「样本不足」而非硬造等级）。 */
export function levelFromPercentile(
  value: number | null | undefined,
): ValuationLevel | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (value <= 0.3) return "低估";
  if (value >= 0.7) return "高估";
  return "中性";
}

/** 估值等级的文字色。 */
export function levelClass(level: ValuationLevel | null): string {
  if (level === "低估") return "text-success";
  if (level === "高估") return "text-destructive";
  if (level === "中性") return "text-warning";
  return "text-muted-foreground";
}
