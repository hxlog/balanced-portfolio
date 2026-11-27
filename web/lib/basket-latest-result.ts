/**
 * 一篮子「最近一次回测结果」的存取映射（纯函数，便于单测）。
 *
 * 落库位置：`bp_basket.latest_result`（JSONB，无新表）。两份写入方共用同一结构：
 * - 服务端：`bp_api/basket.py:build_latest_result`（示例篮子 recompute / seed）；
 * - 前端：自有篮子回测成功后 PATCH（含 nav，见 `latestResultFromBacktest`）。
 *
 * 读取方：打开 `?basket=<id>` 时用 `backtestFromLatestResult` 还原净值曲线 + 扣费后
 * 7 项指标，避免重新请求回测；列表接口只返回裁掉 nav 的摘要（bp_api/baskets.py:
 * `SELECT latest_result - 'nav'`），因此本函数在 nav 缺失时返回 null。
 */

import type {
  BasketBacktestResult,
  BasketFees,
  BasketNavPoint,
  BasketWeight,
} from "./basket-types";

/** `bp_basket.latest_result` 的规范结构（nav 仅详情接口返回）。 */
export interface BasketLatestResult {
  /** 允许直接作为 JSONB 字段（Record<string, unknown>）提交 PATCH。 */
  [key: string]: unknown;
  method: string;
  as_of: string | null;
  computed_at: string;
  effective_start: string;
  lookback_days: number;
  rebalance_band: number;
  risk_free: number;
  trading_days?: number;
  n_obs: number;
  annualized_return: number;
  annualized_vol?: number;
  max_drawdown: number;
  sharpe: number;
  sortino?: number | null;
  calmar?: number | null;
  turnover: number;
  turnover_total?: number;
  rebalance_count?: number;
  fees?: BasketFees | null;
  assets?: Array<{ symbol: string; source: string }>;
  weights?: BasketWeight[];
  nav: BasketNavPoint[];
}

/** 前端保存 latest_result 时补齐的表单口径（与服务端 recompute 同名字段）。 */
export interface LatestResultContext {
  lookback_days: number;
  rebalance_band: number;
  risk_free: number;
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metricOf(
  metrics: Record<string, number | null> | undefined,
  key: string,
): number | null {
  return metrics == null ? null : finiteOrNull(metrics[key]);
}

function parseFees(raw: unknown): BasketFees | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const fee = finiteOrNull(row.fee_rate);
  const slippage = finiteOrNull(row.slippage_rate);
  const stamp = finiteOrNull(row.stamp_duty_rate);
  if (fee == null || slippage == null || stamp == null) return null;
  return {
    fee_rate: fee,
    slippage_rate: slippage,
    stamp_duty_rate: stamp,
    total_cost: finiteOrNull(row.total_cost) ?? undefined,
  };
}

function parseNav(raw: unknown): BasketNavPoint[] | null {
  if (!Array.isArray(raw) || raw.length < 2) return null;
  const out: BasketNavPoint[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") return null;
    const row = item as Record<string, unknown>;
    const tradeDate = row.trade_date;
    const nav = row.nav;
    if (typeof tradeDate !== "string" || tradeDate === "") return null;
    if (typeof nav !== "number" || !Number.isFinite(nav)) return null;
    out.push({
      trade_date: tradeDate,
      nav,
      ret: finiteNumber(row.ret, 0),
    });
  }
  return out;
}

function parseWeights(raw: unknown): BasketWeight[] {
  if (!Array.isArray(raw)) return [];
  const out: BasketWeight[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    if (typeof row.symbol !== "string" || typeof row.source !== "string") continue;
    out.push({
      symbol: row.symbol,
      source: row.source,
      weight: finiteNumber(row.weight, 0),
    });
  }
  return out;
}

/**
 * 回测响应 → 可落库的 latest_result（含 nav）。前端自有篮子回测成功后用它 PATCH。
 */
export function latestResultFromBacktest(
  result: BasketBacktestResult,
  context: LatestResultContext,
  computedAt: string = new Date().toISOString(),
): BasketLatestResult {
  const weights = parseWeights(result.weights);
  const nav = (result.nav ?? [])
    .filter(
      (point) =>
        point &&
        typeof point.trade_date === "string" &&
        typeof point.nav === "number" &&
        Number.isFinite(point.nav),
    )
    .map((point) => ({
      trade_date: point.trade_date,
      nav: point.nav,
      ret: finiteNumber(point.ret, 0),
    }));
  return {
    method: result.method,
    as_of: nav.length > 0 ? nav[nav.length - 1].trade_date : null,
    computed_at: computedAt,
    effective_start: result.effective_start,
    lookback_days: context.lookback_days,
    rebalance_band: context.rebalance_band,
    risk_free: context.risk_free,
    trading_days: result.trading_days,
    n_obs: result.n_obs,
    annualized_return: finiteNumber(result.annualized_return, 0),
    annualized_vol: finiteNumber(result.annualized_vol, 0),
    max_drawdown: finiteNumber(result.max_drawdown, 0),
    sharpe: finiteNumber(result.sharpe, 0),
    sortino: result.sortino ?? metricOf(result.metrics, "sortino"),
    calmar: result.calmar ?? metricOf(result.metrics, "calmar"),
    turnover: finiteNumber(result.turnover, 0),
    turnover_total: finiteNumber(result.turnover_total, 0),
    rebalance_count: finiteNumber(result.rebalance_count, 0),
    fees: result.fees ?? null,
    assets: weights.map((row) => ({ symbol: row.symbol, source: row.source })),
    weights,
    nav,
  };
}

/**
 * latest_result → 可渲染的回测结果（净值曲线 + 7 项扣费后指标）。
 *
 * latest_result 缺 nav（列表接口裁剪的摘要 / 旧版无 nav 的记录）时返回 null，
 * 调用方保持「未回测」状态，避免伪造空曲线。
 */
export function backtestFromLatestResult(
  latestResult: Record<string, unknown> | null | undefined,
): BasketBacktestResult | null {
  if (!latestResult || typeof latestResult !== "object") return null;
  const nav = parseNav(latestResult.nav);
  if (!nav) return null;
  const weights = parseWeights(latestResult.weights);
  const metrics: Record<string, number | null> = {};
  const rawMetrics = latestResult.metrics;
  if (rawMetrics && typeof rawMetrics === "object") {
    for (const [key, value] of Object.entries(rawMetrics)) {
      if (typeof value === "number" && Number.isFinite(value)) metrics[key] = value;
    }
  }
  const effectiveStart =
    typeof latestResult.effective_start === "string" && latestResult.effective_start
      ? latestResult.effective_start
      : nav[0].trade_date;
  return {
    method: typeof latestResult.method === "string" ? latestResult.method : "",
    effective_start: effectiveStart,
    lookback: finiteNumber(latestResult.lookback_days, 156),
    n_obs: finiteNumber(latestResult.n_obs, Math.max(0, nav.length - 1)),
    nav,
    annualized_return: finiteNumber(
      latestResult.annualized_return,
      metricOf(metrics, "annualized_return") ?? 0,
    ),
    annualized_vol: finiteNumber(
      latestResult.annualized_vol,
      metricOf(metrics, "annualized_vol") ?? 0,
    ),
    max_drawdown: finiteNumber(
      latestResult.max_drawdown,
      metricOf(metrics, "max_drawdown") ?? 0,
    ),
    sharpe: finiteNumber(latestResult.sharpe, metricOf(metrics, "sharpe") ?? 0),
    sortino: finiteOrNull(latestResult.sortino) ?? metricOf(metrics, "sortino"),
    calmar: finiteOrNull(latestResult.calmar) ?? metricOf(metrics, "calmar"),
    trading_days: finiteOrNull(latestResult.trading_days) ?? undefined,
    fees: parseFees(latestResult.fees),
    turnover: finiteNumber(latestResult.turnover, 0),
    turnover_total: finiteNumber(latestResult.turnover_total, 0),
    rebalance_count: finiteNumber(latestResult.rebalance_count, 0),
    weights,
    contributions: [],
    rebalances: [],
    metrics,
  };
}
