/**
 * 一篮子资产（单层风险平价）模式 — 共享类型与常量。
 *
 * 该模式与四象限组合完全解耦：不落库、不触发 Celery 任务，只调用后端
 * `POST /api/basket/optimize` 与 `POST /api/basket/backtest` 做同步计算。
 */

import type { Asset } from "./api";

export const BASKET_MAX_ASSETS = 64;
/** 个股主数据源；后端 upsert_asset_config 会自动抓 bfq/qfq/hfq 三口径。 */
export const STOCK_SOURCE = "stock_sina";
/** 股票回测主口径（后端固定使用 hfq）。 */
export const STOCK_BACKTEST_ADJUST = "hfq" as const;

export const BASKET_METHOD_OPTIONS = [
  {
    value: "risk_parity",
    title: "风险平价",
    short: "风险平价",
    desc: "等风险贡献（ERC）：每个资产对组合波动的贡献相同。",
  },
  {
    value: "max_sharpe",
    title: "最大夏普",
    short: "最大夏普",
    desc: "在长仓约束下最大化历史夏普比率。",
  },
  {
    value: "max_sortino",
    title: "最大 Sortino",
    short: "最大 Sortino",
    desc: "只惩罚下行波动的最优风险调整收益。",
  },
  {
    value: "min_variance",
    title: "最小方差",
    short: "最小方差",
    desc: "最小化组合历史波动率，追求最平滑的净值。",
  },
  {
    value: "equal_weight",
    title: "等权",
    short: "等权",
    desc: "每个资产权重相同，作为朴素参照。",
  },
  {
    value: "risk_budget",
    title: "风险预算",
    short: "风险预算",
    desc: "按自定义风险预算分配风险贡献，默认等预算。",
  },
] as const;

export type BasketMethod = (typeof BASKET_METHOD_OPTIONS)[number]["value"];

export const BASKET_METHOD_LABELS: Record<string, string> = Object.fromEntries(
  BASKET_METHOD_OPTIONS.map((m) => [m.value, m.title]),
);

export function basketMethodLabel(method: string): string {
  return BASKET_METHOD_LABELS[method] ?? method;
}

export const BASKET_ADJUST_OPTIONS = [
  { value: "bfq", label: "不复权" },
  { value: "qfq", label: "前复权" },
  { value: "hfq", label: "后复权" },
] as const;

export type BasketAdjust = (typeof BASKET_ADJUST_OPTIONS)[number]["value"];

export const BASKET_CATEGORY_FILTERS = [
  { value: "index", label: "指数" },
  { value: "etf", label: "ETF" },
  { value: "stock", label: "股票" },
  { value: "commodity", label: "商品" },
  { value: "bond", label: "债券" },
] as const;

export interface StockSearchItem {
  stock_code: string;
  name: string;
  market: string | null;
  industry_l1: string | null;
  is_st: boolean;
  sources: string[];
}

export interface StockSearchResponse {
  data: StockSearchItem[];
  meta: { total: number; limit?: number; offset?: number };
}

export interface StockIndustry {
  industry: string;
  count: number;
}

export interface StockIndustriesResponse {
  data: StockIndustry[];
  meta: { industries?: number };
}

export interface BasketAssetRef {
  symbol: string;
  source: string;
}

export interface BasketOptimizeInput {
  assets: BasketAssetRef[];
  method: BasketMethod;
  lookback_days: number;
  risk_free: number;
  risk_budget?: Record<string, number>;
}

export interface BasketBacktestInput extends BasketOptimizeInput {
  rebalance_band: number;
}

export interface BasketWeight {
  symbol: string;
  source: string;
  weight: number;
}

export interface BasketDiagnostics {
  method: string;
  lookback: number;
  effective_start: string | null;
  n_obs: number;
  volatility: number;
  sharpe: number;
  annualized_return: number;
  active_assets: number;
}

export interface BasketOptimizeResult {
  method: string;
  weights: BasketWeight[];
  diagnostics: BasketDiagnostics;
}

export interface BasketNavPoint {
  trade_date: string;
  nav: number;
  ret: number;
}

export interface BasketContribution {
  key?: string;
  symbol: string;
  source: string;
  avg_weight: number;
  asset_return: number;
  contribution: number;
}

export interface BasketRebalance {
  trade_date: string;
  reason?: string;
  target_weights?: Record<string, number>;
  prev_weights?: Record<string, number> | null;
  delta?: Record<string, number> | null;
  max_deviation?: number;
  turnover?: number;
}

export interface BasketBacktestResult {
  method: string;
  effective_start: string;
  lookback: number;
  n_obs: number;
  nav: BasketNavPoint[];
  annualized_return: number;
  annualized_vol: number;
  max_drawdown: number;
  sharpe: number;
  turnover: number;
  turnover_total: number;
  rebalance_count: number;
  weights: BasketWeight[];
  contributions: BasketContribution[];
  rebalances: BasketRebalance[];
  metrics: Record<string, number | null>;
}

/** 篮子里的一项资产（与四象限的 quadrant 无关）。 */
export interface BasketItem {
  key: string;
  symbol: string;
  source: string;
  name: string;
  category?: string;
  vendor?: string;
  assetClass?: string;
  industry?: string;
  market?: string;
  /** 仅影响本页展示口径；请求体从不携带该字段。 */
  adjustView: BasketAdjust;
  /** 是否已在资产池（`/api/assets`）中；未接入的股票无法回测。 */
  inPool: boolean;
  /** 资产池内是否已有清洗行情；未接入/待拉取时给出提示。 */
  hasData: boolean;
}

export function basketKey(symbol: string, source: string): string {
  return `${symbol}@${source}`;
}

export function defaultAdjustForAsset(
  asset: Pick<Asset, "source" | "adjust">,
): BasketAdjust {
  const raw = asset.adjust;
  if (raw === "bfq" || raw === "qfq" || raw === "hfq") return raw;
  return asset.source.startsWith("stock_") ? STOCK_BACKTEST_ADJUST : "bfq";
}

export function basketItemFromAsset(asset: Asset): BasketItem {
  return {
    key: basketKey(asset.symbol, asset.source),
    symbol: asset.symbol,
    source: asset.source,
    name: asset.name || asset.symbol,
    category: asset.category,
    vendor: asset.vendor,
    assetClass: asset.asset_class,
    adjustView: defaultAdjustForAsset(asset),
    inPool: true,
    hasData: Boolean(asset.last_clean_date),
  };
}

export function basketItemFromStock(
  stock: StockSearchItem,
  poolHit?: Asset,
): BasketItem {
  return {
    key: basketKey(stock.stock_code, STOCK_SOURCE),
    symbol: stock.stock_code,
    source: STOCK_SOURCE,
    name: stock.name,
    category: "stock",
    vendor: "sina",
    assetClass: "stock",
    industry: stock.industry_l1 ?? undefined,
    market: stock.market ?? undefined,
    adjustView: STOCK_BACKTEST_ADJUST,
    inPool: Boolean(poolHit),
    hasData: Boolean(poolHit?.last_clean_date),
  };
}
