/**
 * /valuation 首页的数据层（客户端取数与映射）。
 *
 * 目标接口（task-2 be-valuation 契约）：
 *   GET /api/v1/valuation/indices?window=5y  一次性返回全部指数 4 指标当前值+分位（快照表）
 *   GET /api/v1/market/mvi?range=5y          周频 MVI 序列 + 因子贡献
 *   GET /api/v1/market/mvi/overlay?index=... MVI 双轴图所需指数收盘序列
 *
 * 兼容策略：新接口未部署/失败时自动降级到现网接口
 *   GET /api/valuation/indices / /api/valuation/{code}/history / /api/valuation/overview
 * 并返回 `source` 标记，绝不伪造数据（失败返回 null，由 UI 显示占位/空态）。
 */

import { mapIndexRow, mapMvi, mapValuationHistory } from "./valuation-api-map";
import type {
  BroadProxyCard,
  IndexQuoteRow,
  MviInfo,
  MviPoint,
  PercentileWindow,
  ValuationHistory,
  ValuationMetric,
} from "./valuation-types";

export const VALUATION_BASE_PATH = "/api/valuation";
export const VALUATION_INDICES_PATH = `${VALUATION_BASE_PATH}/indices`;
export const VALUATION_OVERVIEW_PATH = `${VALUATION_BASE_PATH}/overview`;
export const VALUATION_SNAPSHOT_PATH = "/api/v1/valuation/indices";
export const MVI_PATH = "/api/v1/market/mvi";
export const MVI_OVERLAY_PATH = "/api/v1/market/mvi/overlay";

/** 首页 Valuation Band 的指数选择器（4 只）。 */
export const BAND_INDEX_OPTIONS = [
  { code: "000300", name: "沪深300" },
  { code: "000510", name: "中证A500" },
  { code: "000016", name: "上证50" },
  { code: "000985", name: "中证全指" },
] as const;

export const DEFAULT_BAND_INDEX = BAND_INDEX_OPTIONS[0].code;

/**
 * MVI 展开图（双轴）的指数选择器（4 只，默认沪深300）。
 *
 * 000985 中证全指暂无可用点位历史（估值 fallback 接入晚、免费源仅滚动 20 日），
 * 默认打开 000985 会命中「点位数据建设中」，故默认 000300；000985 保留在列表末尾。
 */
export const MVI_OVERLAY_INDEX_OPTIONS = [
  { code: "000300", name: "沪深300" },
  { code: "000510", name: "中证A500" },
  { code: "000016", name: "上证50" },
  { code: "000985", name: "中证全指" },
] as const;

export const DEFAULT_MVI_OVERLAY_INDEX = MVI_OVERLAY_INDEX_OPTIONS[0].code;

/** 首页代表性宽基卡顺序（与后端 _BROAD_PROXY_CODES 一致）。 */
export const PROXY_CODES = ["000016", "000300", "000510", "000905", "000852"] as const;

const BAND_METRICS: readonly ValuationMetric[] = ["pe_ttm", "pb", "dividend_yield_ttm", "erp"];

/** 估值快照（含来源标记，便于排查降级）。 */
export interface IndexSnapshot {
  rows: IndexQuoteRow[];
  asOf: string | null;
  updatedAt: string | null;
  source: "v1" | "legacy";
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function dateOnly(value: unknown): string | null {
  const text = str(value);
  if (!text) return null;
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : null;
}

function payloadData(raw: unknown): unknown | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  return "data" in record ? record.data : raw;
}

function payloadMeta(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object") return {};
  const meta = (raw as Record<string, unknown>).meta;
  return meta && typeof meta === "object" ? (meta as Record<string, unknown>) : {};
}

/** 单次请求超时：避免网络挂起时图表永久停在骨架（失败按 null 走空态/错误态）。 */
export const CLIENT_REQUEST_TIMEOUT_MS = 15_000;

function requestSignal(signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(CLIENT_REQUEST_TIMEOUT_MS);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

async function getJson(path: string, signal?: AbortSignal): Promise<unknown | null> {
  try {
    const response = await fetch(path, { signal: requestSignal(signal), cache: "no-store" });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

/** 估值快照响应 -> IndexSnapshot（列表行复用唯一的 mapIndexRow 映射）。 */
export function mapIndexSnapshot(
  raw: unknown,
  source: "v1" | "legacy" = "v1",
): IndexSnapshot | null {
  const data = payloadData(raw);
  if (!Array.isArray(data)) return null;
  const rows = data
    .map((item) => (item && typeof item === "object" ? mapIndexRow(item as Record<string, unknown>) : null))
    .filter((row): row is IndexQuoteRow => row !== null && row.index_code !== "");
  if (rows.length === 0) return null;
  const meta = payloadMeta(raw);
  const asOfCandidates = rows.map((row) => row.trade_date).filter(Boolean);
  const updatedCandidates = rows
    .map((row) => {
      const value = (row as unknown as Record<string, unknown>).updated_at;
      return typeof value === "string" ? value : null;
    })
    .filter((value): value is string => Boolean(value));
  return {
    rows,
    asOf:
      dateOnly(meta.as_of) ??
      (asOfCandidates.length ? asOfCandidates.slice().sort().at(-1)! : null),
    updatedAt:
      str(meta.updated_at) ??
      str(meta.generated_at) ??
      (updatedCandidates.length ? updatedCandidates.slice().sort().at(-1)! : null),
    source,
  };
}

/**
 * 拉取估值快照：优先新快照接口，失败降级现网列表接口。
 * 只发一次请求（4 指标一次取全）；metric 仅用于降级请求的兼容参数。
 */
export async function fetchIndexSnapshot(options: {
  window: PercentileWindow;
  metric: ValuationMetric;
  signal?: AbortSignal;
}): Promise<IndexSnapshot | null> {
  // v1 快照默认返回全部跟踪指数；limit 只在旧接口降级请求时使用。
  const v1Params = new URLSearchParams({ window: options.window });
  const v1 = await getJson(`${VALUATION_SNAPSHOT_PATH}?${v1Params.toString()}`, options.signal);
  const snapshot = mapIndexSnapshot(v1, "v1");
  if (snapshot) return snapshot;

  const legacyParams = new URLSearchParams({
    limit: "1000",
    window: options.window,
    metric: options.metric,
  });
  const legacy = await getJson(`${VALUATION_INDICES_PATH}?${legacyParams.toString()}`, options.signal);
  return mapIndexSnapshot(legacy, "legacy");
}

/** 单指标历史序列：现网历史接口优先，新 v1 历史接口兜底。 */
export async function fetchIndexHistory(
  code: string,
  metric: ValuationMetric,
  window: PercentileWindow,
  signal?: AbortSignal,
): Promise<ValuationHistory | null> {
  const params = new URLSearchParams({ metric, window });
  const legacy = await getJson(
    `${VALUATION_BASE_PATH}/${encodeURIComponent(code)}/history?${params.toString()}`,
    signal,
  );
  if (legacy) {
    const history = mapValuationHistory(code, legacy as Record<string, unknown>, metric, window);
    if (history.series.length > 0 || history.stats) return history;
  }
  const v1 = await getJson(
    `/api/v1/valuation/${encodeURIComponent(code)}/history?${params.toString()}`,
    signal,
  );
  if (!v1) return null;
  const history = mapValuationHistory(code, v1 as Record<string, unknown>, metric, window);
  return history.series.length > 0 || history.stats ? history : null;
}

/** 一次性取某指数 4 个指标的历史序列（指标 tab 本地切换的数据基础）。 */
export async function fetchBandHistories(
  code: string,
  window: PercentileWindow,
  signal?: AbortSignal,
): Promise<Partial<Record<ValuationMetric, ValuationHistory>>> {
  const settled = await Promise.all(
    BAND_METRICS.map(async (metric) => {
      const history = await fetchIndexHistory(code, metric, window, signal);
      return [metric, history] as const;
    }),
  );
  const result: Partial<Record<ValuationMetric, ValuationHistory>> = {};
  for (const [metric, history] of settled) {
    if (history) result[metric] = history;
  }
  return result;
}

function mapMviPointList(raw: unknown): MviPoint[] {
  if (!Array.isArray(raw)) return [];
  const points: MviPoint[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const date = dateOnly(record.as_of) ?? dateOnly(record.date) ?? dateOnly(record.trade_date);
    if (!date) continue;
    points.push({ as_of: date, mvi: num(record.mvi) ?? num(record.value), risk: num(record.risk) ?? num(record.risk_score) });
  }
  points.sort((a, b) => a.as_of.localeCompare(b.as_of));
  return points;
}

function normalizeMviLatest(raw: unknown): Record<string, unknown> | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const asOf = dateOnly(record.as_of) ?? dateOnly(record.date) ?? dateOnly(record.trade_date);
  const mvi = num(record.mvi) ?? num(record.value) ?? num(record.score);
  if (mvi == null) return null;
  return {
    as_of: asOf ?? "",
    mvi,
    cheap_score: num(record.cheap_score) ?? num(record.valuation_score),
    risk_score: num(record.risk_score) ?? num(record.risk),
    zone: str(record.zone) ?? "",
    factors: (record.factors as Record<string, number> | undefined) ?? null,
    weights: (record.weights as Record<string, number> | undefined) ?? null,
    contributions: (record.contributions as Record<string, number> | undefined) ?? null,
    risk_factors:
      (record.risk_factors as Record<string, number | null> | undefined) ?? null,
  };
}

/**
 * MVI 响应映射。兼容三种形态：
 * 1) { data: { latest, history } }（新接口推荐）
 * 2) { data: [{as_of,mvi,...}] }（仅序列）
 * 3) { latest, history }（旧 overview.meta.mvi）
 */
export function mapMviPayload(raw: unknown): MviInfo | null {
  if (!raw || typeof raw !== "object") return null;
  const container = payloadData(raw);
  if (!container) return null;

  if (Array.isArray(container)) {
    const history = mapMviPointList(container);
    if (history.length === 0) return null;
    const last = history.at(-1)!;
    return {
      latest: {
        as_of: last.as_of,
        mvi: last.mvi ?? 0,
        cheap_score: 100 - (last.mvi ?? 0),
        risk_score: last.risk,
        zone: "",
        factors: null,
        weights: null,
        contributions: null,
        risk_factors: null,
      },
      history,
    };
  }

  const record = container as Record<string, unknown>;
  const latest = normalizeMviLatest(
    record.latest ?? record.current ?? record.mvi_latest,
  );
  const history = mapMviPointList(
    record.history ?? record.series ?? record.points ?? record.mvi_series,
  );
  if (!latest && history.length === 0) return null;
  if (latest) {
    return mapMvi({ latest, history }) ?? { latest: null, history };
  }
  return mapMvi({ latest: null, history });
}

/** 拉取 MVI：新接口优先，旧 overview.meta.mvi 兜底。 */
export async function fetchMvi(
  range: "1y" | "3y" | "5y" | "10y" | "all" = "5y",
  signal?: AbortSignal,
): Promise<MviInfo | null> {
  const v1 = await getJson(`${MVI_PATH}?range=${range}`, signal);
  const parsed = mapMviPayload(v1);
  if (parsed?.latest) return parsed;

  const legacy = await getJson(`${VALUATION_OVERVIEW_PATH}?window=5y`, signal);
  const legacyMeta = payloadMeta(legacy);
  const legacyMvi = mapMvi(legacyMeta.mvi);
  if (legacyMvi?.latest) return legacyMvi;
  return parsed;
}

export interface MviOverlayPoint {
  date: string;
  close: number;
}

export interface MviOverlay {
  code: string;
  name: string;
  series: MviOverlayPoint[];
  mvi: MviPoint[];
  /** 后端标注“该指数暂无可用的点位序列”（仍返回 200 + MVI），UI 显示建设中而非报错。 */
  missing: boolean;
}

function mapOverlaySeries(raw: unknown): MviOverlayPoint[] {
  if (!Array.isArray(raw)) return [];
  const points: MviOverlayPoint[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const date = dateOnly(record.date) ?? dateOnly(record.trade_date) ?? dateOnly(record.as_of);
    const close = num(record.close) ?? num(record.value) ?? num(record.price) ?? num(record.point);
    if (!date || close == null || close <= 0) continue;
    points.push({ date, close });
  }
  points.sort((a, b) => a.date.localeCompare(b.date));
  return points;
}

/** MVI 双轴图 overlay 响应映射（指数收盘序列 + 可选 MVI 序列）。 */
export function mapMviOverlay(raw: unknown): MviOverlay | null {
  const container = payloadData(raw);
  if (!container || typeof container !== "object" || Array.isArray(container)) return null;
  const record = container as Record<string, unknown>;
  const code = str(record.index_code) ?? str(record.code) ?? str(record.index) ?? "";
  const name = str(record.index_name) ?? str(record.name) ?? code;
  const series = mapOverlaySeries(
    record.series ?? record.price_series ?? record.index_series ?? record.close_series,
  );
  const missing = record.missing === true;
  const mvi = mapMviPointList(
    record.mvi ?? record.mvi_series ?? record.mvi_history ?? record.overlay_mvi,
  );
  if (series.length === 0) {
    // 明确标注缺数据时保留 MVI 序列，由弹窗显示“点位数据建设中”；其它情况视为失败。
    if (!missing) return null;
    return { code, name, series, mvi, missing };
  }
  return { code, name, series, mvi, missing };
}

/** 拉取 MVI 双轴图 overlay；失败返回 null（按钮处显示空态，不伪造曲线）。 */
export async function fetchMviOverlay(
  code: string,
  signal?: AbortSignal,
): Promise<MviOverlay | null> {
  const params = new URLSearchParams({ index: code, range: "5y" });
  const raw = await getJson(`${MVI_OVERLAY_PATH}?${params.toString()}`, signal);
  return mapMviOverlay(raw);
}

/** 由估值快照行推导首页代表性宽基卡（省掉一次 overview 请求）。 */
export function deriveProxyCards(
  rows: readonly IndexQuoteRow[],
  window: PercentileWindow,
): BroadProxyCard[] {
  const byCode = new Map(rows.map((row) => [row.index_code, row]));
  const cards: BroadProxyCard[] = [];
  for (const code of PROXY_CODES) {
    const row = byCode.get(code);
    if (!row) continue;
    cards.push({
      index_code: row.index_code,
      name: row.name,
      industry: row.industry ?? null,
      trade_date: row.trade_date,
      pe: row.pe_ttm,
      pe_percentile: row.pe_percentile,
      pb: row.pb,
      pb_percentile: row.pb_percentile,
      dividend_yield_pct: row.dividend_yield_pct,
      risk_premium_pct: row.risk_premium_pct,
      window,
    });
  }
  return cards;
}
