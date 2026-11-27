/**
 * /valuation 首页的**服务端**数据层（仅被 page.tsx 引用，不进入客户端 bundle）。
 *
 * 取数顺序：
 * 1) 新快照接口 `GET /api/v1/valuation/indices`（一次取全 4 指标分位，<50ms）；
 * 2) 新接口未部署/失败 → 降级现网 `/api/valuation/indices`（cached-data，带 "use cache"）；
 * 3) MVI：新 `GET /api/v1/market/mvi` → 降级 overview.meta.mvi；
 * 4) 默认指数（沪深300）的 4 指标历史序列并行预取，首屏切换指标即本地状态。
 *
 * 任一数据源失败都只影响对应区块（返回空值/降级标记），页面其余部分照常渲染。
 */

import { mapIndexRow, mapMvi, mapValuationHistory } from "./valuation-api-map";
import {
  getCachedValuationHistory,
  getCachedValuationIndices,
  getCachedValuationOverview,
} from "./cached-data";
import {
  DEFAULT_BAND_INDEX,
  MVI_PATH,
  VALUATION_SNAPSHOT_PATH,
  deriveProxyCards,
  mapIndexSnapshot,
  mapMviPayload,
} from "./valuation-snapshot";
import { apiBase } from "./session-server";
import type {
  BroadProxyCard,
  IndexQuoteRow,
  MviInfo,
  PercentileWindow,
  ValuationHistory,
  ValuationMetric,
} from "./valuation-types";

const SERVER_TIMEOUT_MS = 6_000;

const BAND_METRICS: readonly ValuationMetric[] = [
  "pe_ttm",
  "pb",
  "dividend_yield_ttm",
  "erp",
];

async function serverJson(path: string): Promise<unknown | null> {
  try {
    const response = await fetch(apiBase() + path, {
      signal: AbortSignal.timeout(SERVER_TIMEOUT_MS),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

export interface ValuationHomeData {
  rows: IndexQuoteRow[];
  proxies: BroadProxyCard[];
  /** 默认指数 × 4 指标的历史序列（首屏指标切换零请求）。 */
  histories: Partial<Record<ValuationMetric, ValuationHistory>>;
  mvi: MviInfo | null;
  /** 降级/失败标记（仅用于日志；UI 不伪造数据）。 */
  degraded: string[];
}

async function loadSnapshot(
  window: PercentileWindow,
  metric: ValuationMetric,
  degraded: string[],
): Promise<IndexQuoteRow[]> {
  // v1 快照默认返回全部跟踪指数（不传 limit）；旧接口降级时才需要 limit=1000 分页参数。
  const params = new URLSearchParams({ window });
  const v1 = await serverJson(`${VALUATION_SNAPSHOT_PATH}?${params.toString()}`);
  const snapshot = mapIndexSnapshot(v1, "v1");
  if (snapshot) return snapshot.rows;
  degraded.push("snapshot_v1_unavailable");

  try {
    const legacy = await getCachedValuationIndices(1000, window, metric);
    const rows = (legacy.data ?? [])
      .map((item) => mapIndexRow(item as Record<string, unknown>))
      .filter((row) => row.index_code !== "");
    if (rows.length > 0) {
      degraded.push("snapshot_legacy");
      return rows;
    }
  } catch {
    degraded.push("snapshot_failed");
  }
  return [];
}

async function loadProxies(
  rows: IndexQuoteRow[],
  window: PercentileWindow,
  degraded: string[],
): Promise<BroadProxyCard[]> {
  const derived = deriveProxyCards(rows, window);
  if (derived.length > 0) return derived;
  try {
    const overview = await getCachedValuationOverview(window);
    const rawProxies = overview.meta?.proxies;
    if (Array.isArray(rawProxies)) {
      degraded.push("proxies_overview");
      return rawProxies.map((item) => {
        const raw = item as Record<string, unknown>;
        return {
          index_code: String(raw.index_code ?? ""),
          name: String(raw.name ?? ""),
          industry: typeof raw.industry === "string" ? raw.industry : null,
          trade_date: String(raw.trade_date ?? ""),
          pe: typeof raw.pe_ttm === "number" ? raw.pe_ttm : null,
          pe_percentile: typeof raw.pe_percentile === "number" ? raw.pe_percentile : null,
          pb: typeof raw.pb === "number" ? raw.pb : null,
          pb_percentile: typeof raw.pb_percentile === "number" ? raw.pb_percentile : null,
          dividend_yield_pct:
            typeof raw.dividend_yield_ttm === "number" ? raw.dividend_yield_ttm : null,
          risk_premium_pct: typeof raw.erp === "number" ? raw.erp : null,
          window,
        };
      });
    }
  } catch {
    degraded.push("proxies_failed");
  }
  return [];
}

async function loadMvi(degraded: string[]): Promise<MviInfo | null> {
  const payload = await serverJson(`${MVI_PATH}?range=5y`);
  const parsed = mapMviPayload(payload);
  if (parsed?.latest) return parsed;
  degraded.push("mvi_v1_unavailable");

  try {
    const overview = await getCachedValuationOverview("5y");
    const legacy = mapMvi(overview.meta?.mvi);
    if (legacy?.latest) {
      degraded.push("mvi_legacy");
      return legacy;
    }
  } catch {
    // 保留空态
  }
  degraded.push("mvi_missing");
  return null;
}

async function loadHistories(
  window: PercentileWindow,
  degraded: string[],
): Promise<Partial<Record<ValuationMetric, ValuationHistory>>> {
  const settled = await Promise.allSettled(
    BAND_METRICS.map(async (metric) => {
      const payload = await getCachedValuationHistory(DEFAULT_BAND_INDEX, metric, window);
      return [metric, mapValuationHistory(DEFAULT_BAND_INDEX, payload, metric, window)] as const;
    }),
  );
  const histories: Partial<Record<ValuationMetric, ValuationHistory>> = {};
  settled.forEach((result, index) => {
    if (result.status !== "fulfilled") {
      degraded.push("history_" + BAND_METRICS[index]);
      return;
    }
    const [metric, history] = result.value;
    if (history.series.length > 0 || history.stats) histories[metric] = history;
  });
  return histories;
}

/** 首页一次取数：快照 + 宽基卡 + 默认指数 4 指标历史 + MVI。 */
export async function getValuationHomeData(options: {
  window: PercentileWindow;
  metric: ValuationMetric;
}): Promise<ValuationHomeData> {
  const degraded: string[] = [];
  const rows = await loadSnapshot(options.window, options.metric, degraded);
  const [proxies, mvi, histories] = await Promise.all([
    loadProxies(rows, options.window, degraded),
    loadMvi(degraded),
    loadHistories(options.window, degraded),
  ]);
  return { rows, proxies, histories, mvi, degraded };
}
