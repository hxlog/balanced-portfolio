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
  BasketEqualNavPoint,
  BasketFees,
  BasketNavPoint,
  BasketRebalanceEvent,
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
  /** 结果参数快照（服务端 build_latest_result 将补；旧记录缺省。用于与当前表单比对）。 */
  params?: Record<string, unknown>;
  /** 等权对照净值 / 调仓事件（后端回测响应提供时保留，缺失时不画也不承诺）。 */
  equal_weight_nav?: BasketEqualNavPoint[];
  rebalance_events?: BasketRebalanceEvent[];
}

/** 前端保存 latest_result 时补齐的表单口径（与服务端 recompute 同名字段）。 */
export interface LatestResultContext {
  lookback_days: number;
  rebalance_band: number;
  risk_free: number;
  start?: string | null;
  end?: string | null;
}

/** 当前表单的回测参数快照（小数口径，日期为 ISO 或 null）。 */
export interface BasketParamsSnapshot {
  lookback_days: number;
  rebalance_band: number;
  risk_free: number;
  start: string | null;
  end: string | null;
  /** 优化方法（后端 params 契约含 method）；缺省时跳过比对。 */
  method?: string;
  /** 资产指纹（后端 params 契约含 asset_hash）；缺省时跳过比对。 */
  asset_hash?: string;
}

/** latest_result.params 中可与当前表单比对的子集（缺失的键不参与比对）。 */
export interface BasketResultParams {
  lookback_days?: number;
  rebalance_band?: number;
  risk_free?: number;
  start?: string | null;
  end?: string | null;
  method?: string;
  asset_hash?: string;
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

/** 等权对照净值：只保留合法点；缺失/空数组返回 null（调用方据此不画该系列）。 */
function parseEqualWeightNav(raw: unknown): BasketEqualNavPoint[] | null {
  if (!Array.isArray(raw)) return null;
  const out: BasketEqualNavPoint[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    if (typeof row.trade_date !== "string" || row.trade_date === "") continue;
    if (typeof row.nav !== "number" || !Number.isFinite(row.nav)) continue;
    out.push({ trade_date: row.trade_date, nav: row.nav });
  }
  return out.length > 0 ? out : null;
}

/** 调仓事件：结构由后端生成，这里只要求 trade_date 合法，其余字段原样保留（渲染侧已是宽松读取）。 */
function parseRebalanceEvents(raw: unknown): BasketRebalanceEvent[] | null {
  if (!Array.isArray(raw)) return null;
  const events = raw.filter((item) => {
    if (!item || typeof item !== "object") return false;
    const row = item as Record<string, unknown>;
    return typeof row.trade_date === "string" && row.trade_date !== "";
  }) as BasketRebalanceEvent[];
  return events.length > 0 ? events : null;
}

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function rotr(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

/**
 * 同步 SHA-256 十六进制摘要。
 * 浏览器 Web Crypto（crypto.subtle）是异步 API，而 latest_result.params 的生成是纯函数，
 * 这里内置一份标准实现（仅用于资产指纹，输入长度很小）。
 */
function sha256Hex(text: string): string {
  const data = new TextEncoder().encode(text);
  const padded = new Uint8Array((((data.length + 8) >> 6) + 1) * 64);
  padded.set(data);
  padded[data.length] = 0x80;
  const bitLength = data.length * 8;
  const tail = padded.length - 8;
  // 64 位大端长度：高位 32 位为 0（资产列表远小于 2^32 bit），低 32 位写入尾部。
  padded[tail + 4] = (bitLength >>> 24) & 0xff;
  padded[tail + 5] = (bitLength >>> 16) & 0xff;
  padded[tail + 6] = (bitLength >>> 8) & 0xff;
  padded[tail + 7] = bitLength & 0xff;

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const words = new Uint32Array(64);

  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      const j = offset + i * 4;
      words[i] =
        (padded[j] << 24) | (padded[j + 1] << 16) | (padded[j + 2] << 8) | padded[j + 3];
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(words[i - 15], 7) ^ rotr(words[i - 15], 18) ^ (words[i - 15] >>> 3);
      const s1 = rotr(words[i - 2], 17) ^ rotr(words[i - 2], 19) ^ (words[i - 2] >>> 10);
      words[i] = (words[i - 16] + s0 + words[i - 7] + s1) | 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let i = 0; i < 64; i += 1) {
      const sigma1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const choose = (e & f) ^ (~e & g);
      const t1 = (h + sigma1 + choose + SHA256_K[i] + words[i]) | 0;
      const sigma0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (sigma0 + majority) | 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) | 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) | 0;
    }
    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
    h5 = (h5 + f) | 0;
    h6 = (h6 + g) | 0;
    h7 = (h7 + h) | 0;
  }

  const hex = (value: number) => (value >>> 0).toString(16).padStart(8, "0");
  return hex(h0) + hex(h1) + hex(h2) + hex(h3) + hex(h4) + hex(h5) + hex(h6) + hex(h7);
}

/**
 * 资产指纹（与后端 build_latest_result 的 params.asset_hash 同口径）：
 * 每项拼成 symbol@source，升序排序后用换行符连接，取 sha256(utf-8) 十六进制前 16 位。
 */
export function basketAssetHash(
  assets: readonly { symbol: string; source: string }[],
): string {
  const text = assets
    .map((asset) => asset.symbol + "@" + asset.source)
    .sort()
    .join("\n");
  return sha256Hex(text).slice(0, 16);
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
  // 后端响应带等权净值 / 调仓事件时一并保留，下次打开可原样还原（缺失则不写，避免空数组进库）。
  const equalWeightNav = parseEqualWeightNav(result.equal_weight_nav);
  const rebalanceEvents = parseRebalanceEvents(result.rebalance_events);
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
    // 结果参数绑定：与 nav 同批写入，供下次打开与当前表单比对（与后端
    // build_latest_result 的 params 契约同口径：method + 数值/日期参数 + 资产指纹）。
    params: {
      method: result.method,
      lookback_days: context.lookback_days,
      rebalance_band: context.rebalance_band,
      risk_free: context.risk_free,
      start: context.start ?? null,
      end: context.end ?? null,
      asset_hash: basketAssetHash(weights),
    },
    ...(equalWeightNav ? { equal_weight_nav: equalWeightNav } : {}),
    ...(rebalanceEvents ? { rebalance_events: rebalanceEvents } : {}),
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
    // 旧记录 / 服务端未提供时保持缺失，渲染侧据此不画等权曲线与调仓点、不写说明文案。
    equal_weight_nav: parseEqualWeightNav(latestResult.equal_weight_nav) ?? undefined,
    rebalance_events: parseRebalanceEvents(latestResult.rebalance_events) ?? [],
    contributions: [],
    rebalances: [],
    metrics,
  };
}

const RESULT_PARAM_KEYS = [
  "method",
  "lookback_days",
  "rebalance_band",
  "risk_free",
  "start",
  "end",
  "asset_hash",
] as const;

function normalizeIsoDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text === "" ? null : text.slice(0, 10);
}

/**
 * latest_result.params → 可比子集。
 *
 * 后端 build_latest_result 将补 params 字段；旧记录 / 列表裁剪等没有该字段时返回
 * null，调用方降级为旧行为（不判定过期、不拦截写回）。只保留认识的键，缺哪个键
 * 就跳过哪个键的比对，避免后端只补部分参数时误报。
 */
export function latestResultParams(
  latestResult: Record<string, unknown> | null | undefined,
): BasketResultParams | null {
  const raw = latestResult?.params;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  const out: BasketResultParams = {};
  if (typeof row.lookback_days === "number" && Number.isFinite(row.lookback_days)) {
    out.lookback_days = row.lookback_days;
  }
  if (typeof row.rebalance_band === "number" && Number.isFinite(row.rebalance_band)) {
    out.rebalance_band = row.rebalance_band;
  }
  if (typeof row.risk_free === "number" && Number.isFinite(row.risk_free)) {
    out.risk_free = row.risk_free;
  }
  if ("start" in row) out.start = normalizeIsoDate(row.start);
  if ("end" in row) out.end = normalizeIsoDate(row.end);
  if (typeof row.method === "string" && row.method !== "") out.method = row.method;
  if (typeof row.asset_hash === "string" && row.asset_hash !== "") {
    out.asset_hash = row.asset_hash.toLowerCase();
  }
  return RESULT_PARAM_KEYS.some((key) => key in out) ? out : null;
}

/** 回测入参 → 参数快照（latestResultFromBacktest 写入 params 与还原结果比对共用）。 */
export function paramsSnapshotFromInput(input: {
  lookback_days: number;
  rebalance_band: number;
  risk_free: number;
  start?: string | null;
  end?: string | null;
  method?: string;
  assets?: readonly { symbol: string; source: string }[];
}): BasketParamsSnapshot {
  return {
    lookback_days: Math.max(2, Math.round(input.lookback_days)),
    rebalance_band: input.rebalance_band,
    risk_free: input.risk_free,
    start: normalizeIsoDate(input.start),
    end: normalizeIsoDate(input.end),
    method: input.method,
    asset_hash: input.assets ? basketAssetHash(input.assets) : undefined,
  };
}

/**
 * 结果参数与当前参数快照比对（只比对结果侧实际携带的键）。
 *
 * 日期口径：结果侧为 null/缺失视为「未指定/未知」不报变更（后端旧版只补数值参数、
 * 示例篮子的 params 也没有 start/end，避免与表单默认区间误报）；结果侧有具体日期
 * 时与当前表单（null 表示已清空）严格比对。
 */
export function paramsMatch(
  stored: BasketResultParams,
  current: BasketParamsSnapshot,
): boolean {
  if (
    stored.lookback_days != null &&
    Math.round(stored.lookback_days) !== Math.round(current.lookback_days)
  ) {
    return false;
  }
  if (
    stored.rebalance_band != null &&
    Math.abs(stored.rebalance_band - current.rebalance_band) > 1e-9
  ) {
    return false;
  }
  if (
    stored.risk_free != null &&
    Math.abs(stored.risk_free - current.risk_free) > 1e-9
  ) {
    return false;
  }
  if (stored.start != null && stored.start !== current.start) return false;
  if (stored.end != null && stored.end !== current.end) return false;
  // 方法与资产指纹也属于「结果是否对应当前定义」的一部分（后端 params 契约含这两个键）；
  // 旧记录 / 旧前端未写入时跳过，保持降级兼容。
  if (stored.method != null && current.method != null && stored.method !== current.method) {
    return false;
  }
  if (
    stored.asset_hash != null &&
    current.asset_hash != null &&
    stored.asset_hash !== current.asset_hash.toLowerCase()
  ) {
    return false;
  }
  return true;
}

/**
 * latest_result 与当前表单参数比对：
 * - true = 结果参数与当前表单一致；
 * - false = 结果参数已过期；
 * - null = 结果未携带 params（旧记录），调用方降级为旧行为。
 */
export function latestResultParamsMatch(
  latestResult: Record<string, unknown> | null | undefined,
  current: BasketParamsSnapshot,
): boolean | null {
  const stored = latestResultParams(latestResult);
  return stored == null ? null : paramsMatch(stored, current);
}
