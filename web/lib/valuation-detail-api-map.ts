/**
 * 后端 `/api/valuation/{code}` 与 `/history` 响应 -> 详情页类型。
 *
 * 与 `valuation-api-map.ts` 同一定位：字段口径在这里收口，组件只消费映射后的
 * 驼峰/语义化结构。所有数值走 `num()`，兼容 DB 原生 Decimal/字符串；NaN/Inf 一律
 * 归一为 null，展示层显示「—」。
 */

import type { IndexCategory, ValuationLevel } from "./valuation-types";
import type {
  DetailConstituent,
  DetailPercentile,
  DetailRiskStats,
  DetailTrackerFund,
  PercentileSummary,
  ValuationDetailData,
  ValuationHistoryData,
  ValuationHistoryPoint,
} from "./valuation-detail-types";

const CATEGORIES: ReadonlySet<string> = new Set(["宽基", "行业", "主题", "策略", "其他"]);
const LEVELS: ReadonlySet<string> = new Set(["低估", "中性", "高估"]);

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (
    typeof value === "string" &&
    value.trim() !== "" &&
    Number.isFinite(Number(value))
  ) {
    return Number(value);
  }
  return null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/** 只保留日期部分，避免后端返回 datetime 时把时间串进页面。 */
function dateStr(value: unknown): string | null {
  const text = str(value);
  return text ? text.slice(0, 10) : null;
}

function asCategory(value: unknown): IndexCategory {
  const text = typeof value === "string" ? value : "";
  return (CATEGORIES.has(text) ? text : "其他") as IndexCategory;
}

function asLevel(value: unknown): ValuationLevel | null {
  const text = typeof value === "string" ? value : "";
  return (LEVELS.has(text) ? text : null) as ValuationLevel | null;
}

function mapConstituent(raw: unknown): DetailConstituent | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const stockCode = str(item.stock_code);
  if (!stockCode) return null;
  return {
    stock_code: stockCode,
    name: str(item.name) ?? stockCode,
    industry_l1: str(item.industry_l1),
    weight: num(item.weight),
    rank: num(item.rank),
    effective_date: dateStr(item.effective_date),
  };
}

function mapTrackerFund(raw: unknown): DetailTrackerFund | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const fundCode = str(item.fund_code);
  if (!fundCode) return null;
  return {
    fund_code: fundCode,
    name: str(item.name) ?? fundCode,
    company_name: str(item.company_name),
    risk_grade: str(item.risk_grade),
    aum: num(item.aum),
    trade_date: dateStr(item.trade_date),
    manager: str(item.manager),
    fund_type: str(item.fund_type),
    management_fee: num(item.management_fee),
    custody_fee: num(item.custody_fee),
    established_date: dateStr(item.established_date),
    fund_scale: num(item.fund_scale),
    ret_1m: num(item.ret_1m),
    ret_3m: num(item.ret_3m),
    ret_6m: num(item.ret_6m),
    ret_12m: num(item.ret_12m),
    ret_2y: num(item.ret_2y),
    ret_3y: num(item.ret_3y),
    ret_5y: num(item.ret_5y),
    ytd: num(item.ytd),
    ann_vol_1y: num(item.ann_vol_1y),
    max_dd_1y: num(item.max_dd_1y),
    tracking_error_1y: num(item.tracking_error_1y),
    info_ratio_1y: num(item.info_ratio_1y),
    risk_ret_3y_ann: num(item.risk_ret_3y_ann),
    risk_ret_5y_ann: num(item.risk_ret_5y_ann),
  };
}

/**
 * 分位统计映射。
 *
 * history 的 `stats` 直接来自 `bp_index_percentile` 行，DB 列名是 `min_value` /
 * `max_value`，而契约文档写的是 `min` / `max`；这里两者都兼容。
 */
export function mapPercentileSummary(raw: unknown): PercentileSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  return {
    pct: num(item.pct),
    mean: num(item.mean),
    sd: num(item.sd),
    p20: num(item.p20),
    p50: num(item.p50),
    p80: num(item.p80),
    min: num(item.min) ?? num(item.min_value),
    max: num(item.max) ?? num(item.max_value),
    sample_size: Math.max(0, Math.trunc(num(item.sample_size) ?? 0)),
    reason: str(item.reason),
  };
}

function mapDetailPercentile(raw: unknown): DetailPercentile | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const summary = mapPercentileSummary(item);
  const metric = str(item.metric);
  if (!summary || !metric) return null;
  return {
    ...summary,
    metric,
    window_key: str(item.window_key) ?? "",
  };
}

/** 详情响应 `data` -> `ValuationDetailData`；缺少指数代码时返回 null（按错误态处理）。 */
export function mapValuationDetail(
  raw: Record<string, unknown> | null | undefined,
): ValuationDetailData | null {
  if (!raw || typeof raw !== "object") return null;
  const code = str(raw.index_code);
  if (!code) return null;

  const constituents = Array.isArray(raw.constituents)
    ? raw.constituents
        .map(mapConstituent)
        .filter((item): item is DetailConstituent => item !== null)
    : [];
  const trackerFunds = Array.isArray(raw.tracker_funds)
    ? raw.tracker_funds
        .map(mapTrackerFund)
        .filter((item): item is DetailTrackerFund => item !== null)
    : [];
  const percentiles = Array.isArray(raw.percentiles)
    ? raw.percentiles
        .map(mapDetailPercentile)
        .filter((item): item is DetailPercentile => item !== null)
    : [];

  const rawRisk = raw.risk;
  const risk: ValuationDetailData["risk"] = {};
  if (rawRisk && typeof rawRisk === "object") {
    for (const key of ["1y", "3y", "5y", "all"] as const) {
      const stats = mapRiskStats((rawRisk as Record<string, unknown>)[key]);
      if (stats) risk[key] = stats;
    }
  }

  return {
    index_code: code,
    name: str(raw.name) ?? code,
    market: str(raw.market),
    index_type: asCategory(raw.index_type),
    publisher: str(raw.publisher),
    base_date: dateStr(raw.base_date),
    base_point: num(raw.base_point),
    income_method: str(raw.income_method),
    weight_method: str(raw.weight_method),
    intro: str(raw.intro),
    trade_date: dateStr(raw.trade_date),
    industry: str(raw.industry),
    close: num(raw.close_price),
    change_pct: num(raw.change_pct),
    pe_ttm: num(raw.pe_ttm),
    pb: num(raw.pb),
    dividend_yield_ttm: num(raw.dividend_yield_ttm),
    erp: num(raw.erp),
    roe_ttm: num(raw.roe_ttm),
    bond10y: num(raw.bond10y),
    level_pe: asLevel(raw.level_pe),
    level_pb: asLevel(raw.level_pb),
    level_dividend: asLevel(raw.level_dividend),
    constituents,
    tracker_funds: trackerFunds,
    percentiles,
    risk,
  };
}

function mapRiskStats(raw: unknown): DetailRiskStats | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  return {
    total_return_pct: num(item.total_return_pct),
    annualized_return_pct: num(item.annualized_return_pct),
    volatility_pct: num(item.volatility_pct),
    max_drawdown_pct: num(item.max_drawdown_pct),
    sharpe: num(item.sharpe),
    sample_size: Math.max(0, Math.trunc(num(item.sample_size) ?? 0)),
  };
}

function mapHistoryPoint(raw: unknown): ValuationHistoryPoint | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const date = dateStr(item.trade_date);
  const value = num(item.value);
  if (!date || value == null) return null;
  return { trade_date: date, value };
}

/** history 响应 `data` -> `ValuationHistoryData`；按日期升序。 */
export function mapValuationHistory(
  raw: Record<string, unknown> | null | undefined,
): ValuationHistoryData {
  const item = raw && typeof raw === "object" ? raw : {};
  const series = Array.isArray(item.series)
    ? item.series
        .map(mapHistoryPoint)
        .filter((point): point is ValuationHistoryPoint => point !== null)
    : [];
  series.sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  return { series, stats: mapPercentileSummary(item.stats) };
}

/** 从详情 `percentiles[]` 精确取某个 metric + window 的统计。 */
export function findPercentile(
  percentiles: readonly DetailPercentile[],
  metric: string,
  windowKey = "5y",
): DetailPercentile | null {
  return (
    percentiles.find(
      (item) => item.metric === metric && item.window_key === windowKey,
    ) ?? null
  );
}
