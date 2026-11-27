/**
 * 全局数据更新徽标（/valuation 页头）的数据层。
 *
 * 后端契约（task-1 be-data 确认）：
 *   GET /api/v1/market/data-freshness（匿名，60s 服务端缓存）
 *   {
 *     data: [{ dataset, label, as_of, expected_date, status, is_stale,
 *              lag_days, updated_at, source, note }],   // 恒 8 条且顺序固定
 *     meta: { latest_complete_date, all_complete, expected_date, missing,
 *             cached, generated_at }
 *   }
 *
 * 约定：
 * - `latest_complete_date = min(非空 as_of)`，徽标显示「数据更新至」用这一个值；
 * - 是否齐套看 `meta.all_complete` / `meta.missing`，而不是 latest_complete_date；
 * - 接口未部署/请求失败时前端展示占位（获取中/暂不可用），绝不伪造日期。
 */

/** 8 类数据的稳定 key 与展示顺序（后端固定顺序，前端再做一次兜底）。 */
export const FRESHNESS_DATASETS = [
  { key: "a_stock", label: "A股行情" },
  { key: "hk_stock", label: "港股行情" },
  { key: "etf", label: "ETF 行情" },
  { key: "fund_nav", label: "基金净值" },
  { key: "cffex", label: "股指期货" },
  { key: "index_quotes", label: "指数行情" },
  { key: "index_valuation", label: "指数估值" },
  { key: "mvi", label: "MVI" },
] as const;

export type FreshnessDatasetKey = (typeof FRESHNESS_DATASETS)[number]["key"];

export type FreshnessStatus =
  | "ok"
  | "lagging"
  | "stale"
  | "missing"
  | "unavailable"
  | "error";

export interface DataFreshnessItem {
  dataset: string;
  label: string;
  /** 该数据最新完整日期（ISO date）；无数据为 null。 */
  as_of: string | null;
  /** 按收盘确认时点算出的应到日期（ISO date）。 */
  expected_date: string | null;
  status: FreshnessStatus;
  is_stale: boolean;
  /** expected_date - as_of 的自然日差；as_of 为空时 null。 */
  lag_days: number | null;
  updated_at: string | null;
  source: string | null;
  note: string | null;
}

export interface DataFreshnessMeta {
  latest_complete_date: string | null;
  all_complete: boolean;
  expected_date: string | null;
  missing: string[];
  cached?: boolean;
  generated_at: string | null;
}

export interface DataFreshness {
  items: DataFreshnessItem[];
  meta: DataFreshnessMeta;
}

export const FRESHNESS_API_PATH = "/api/v1/market/data-freshness";

const STATUS_SET: ReadonlySet<string> = new Set([
  "ok",
  "lagging",
  "stale",
  "missing",
  "unavailable",
  "error",
]);

const STATUS_LABEL: Record<FreshnessStatus, string> = {
  ok: "已更新",
  lagging: "滞后",
  stale: "陈旧",
  missing: "缺失",
  unavailable: "不可用",
  error: "异常",
};

/** 后端 status -> 中文短标签（tooltip 用）。 */
export function freshnessStatusLabel(status: FreshnessStatus): string {
  return STATUS_LABEL[status] ?? "未知";
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function dateOnly(value: unknown): string | null {
  const text = str(value);
  if (!text) return null;
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : null;
}

function asStatus(value: unknown): FreshnessStatus {
  return STATUS_SET.has(String(value)) ? (String(value) as FreshnessStatus) : "missing";
}

function mapItem(raw: Record<string, unknown>): DataFreshnessItem | null {
  const dataset = str(raw.dataset) ?? str(raw.key);
  if (!dataset) return null;
  const known = FRESHNESS_DATASETS.find((item) => item.key === dataset);
  const asOf = dateOnly(raw.as_of);
  const status = known || raw.status ? asStatus(raw.status) : "missing";
  const lagDays = num(raw.lag_days);
  return {
    dataset,
    label: str(raw.label) ?? known?.label ?? dataset,
    as_of: asOf,
    expected_date: dateOnly(raw.expected_date),
    status,
    is_stale:
      typeof raw.is_stale === "boolean" ? raw.is_stale : status !== "ok",
    lag_days: lagDays == null ? null : Math.trunc(lagDays),
    updated_at: str(raw.updated_at),
    source: str(raw.source),
    note: str(raw.note),
  };
}

/** 接口不可用时的 8 类占位明细（日期全部 null，不得展示成 0 或今天）。 */
export function placeholderFreshness(): DataFreshness {
  return {
    items: FRESHNESS_DATASETS.map((item) => ({
      dataset: item.key,
      label: item.label,
      as_of: null,
      expected_date: null,
      status: "missing" as const,
      is_stale: true,
      lag_days: null,
      updated_at: null,
      source: null,
      note: null,
    })),
    meta: {
      latest_complete_date: null,
      all_complete: false,
      expected_date: null,
      missing: FRESHNESS_DATASETS.map((item) => item.key),
      generated_at: null,
    },
  };
}

/**
 * 把后端响应映射成前端结构。
 *
 * 容错点：
 * - 兼容 `{data: [...]}` 信封与裸数组；
 * - 恒按 8 类固定顺序输出，后端缺类时补占位（状态 missing），后端多出的类追加在末尾；
 * - meta 缺失时从 items 现场推导（min(as_of) / missing / all_complete）。
 */
export function mapFreshness(raw: unknown): DataFreshness | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const source = Array.isArray(record)
    ? (record as unknown[])
    : Array.isArray(record.data)
      ? (record.data as unknown[])
      : null;
  if (!source) return null;
  const mapped = source
    .map((item) => (item && typeof item === "object" ? mapItem(item as Record<string, unknown>) : null))
    .filter((item): item is DataFreshnessItem => item !== null);
  if (mapped.length === 0) return null;

  const fallback = placeholderFreshness();
  const byKey = new Map(mapped.map((item) => [item.dataset, item]));
  const ordered: DataFreshnessItem[] = [];
  for (const dataset of FRESHNESS_DATASETS) {
    ordered.push(
      byKey.get(dataset.key) ??
        fallback.items.find((item) => item.dataset === dataset.key)!,
    );
    byKey.delete(dataset.key);
  }
  ordered.push(...byKey.values());

  const metaRecord =
    record.meta && typeof record.meta === "object"
      ? (record.meta as Record<string, unknown>)
      : {};

  const asOfDates = ordered
    .map((item) => item.as_of)
    .filter((value): value is string => Boolean(value));
  const missing = ordered.filter((item) => item.status === "missing" || item.as_of == null).map((item) => item.dataset);
  const latest = dateOnly(metaRecord.latest_complete_date) ?? (asOfDates.length ? asOfDates.sort()[0] : null);
  const allComplete =
    typeof metaRecord.all_complete === "boolean"
      ? metaRecord.all_complete
      : ordered.every((item) => item.as_of != null && !item.is_stale);

  return {
    items: ordered,
    meta: {
      latest_complete_date: latest,
      all_complete: allComplete,
      expected_date: dateOnly(metaRecord.expected_date),
      missing: Array.isArray(metaRecord.missing)
        ? metaRecord.missing.map((item) => String(item))
        : missing,
      cached: typeof metaRecord.cached === "boolean" ? metaRecord.cached : undefined,
      generated_at: str(metaRecord.generated_at),
    },
  };
}

/** 徽标语气：有数据且全部齐套=ok（绿点），有滞后/缺失=warning（琥珀），无数据=pending。 */
export function freshnessTone(freshness: DataFreshness | null): "ok" | "warning" | "pending" {
  if (!freshness || !freshness.meta.latest_complete_date) return "pending";
  if (!freshness.meta.all_complete || freshness.meta.missing.length > 0) return "warning";
  return "ok";
}

/**
 * 徽标主文案：数据更新至 YYYY-MM-DD。
 *
 * - 无响应（接口未就绪/仍在重试）：获取中；
 * - 有响应但 latest_complete_date 为 null（例如全部数据集暂无 as_of）：暂无数据，
 *   不能继续显示「获取中…」——接口已返回，只是确实没有完整数据日。
 */
export function freshnessBadgeText(freshness: DataFreshness | null): string {
  if (!freshness) return "数据状态 获取中…";
  const date = freshness.meta.latest_complete_date;
  return date ? `数据更新至 ${date}` : "数据状态 暂无数据";
}

/** tooltip 底部摘要：最新完整日 / 应到日 / 生成时间。 */
export function freshnessMetaSummary(freshness: DataFreshness | null): string {
  if (!freshness) return "接口尚未就绪，正在重试…";
  const parts: string[] = [];
  parts.push(
    freshness.meta.latest_complete_date
      ? `最新完整数据日 ${freshness.meta.latest_complete_date}`
      : "最新完整数据日 —",
  );
  if (freshness.meta.expected_date) parts.push(`应到 ${freshness.meta.expected_date}`);
  if (freshness.meta.generated_at) parts.push(`生成于 ${formatUpdatedAt(freshness.meta.generated_at)}`);
  return parts.join(" · ");
}

/** ISO datetime -> "YYYY-MM-DD HH:mm"（仅截断字符串，不做时区换算）。 */
export function formatUpdatedAt(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace("T", " ");
  return text.slice(0, 16);
}

/** 单类数据的语气：ok=绿，滞后/异常=琥珀，缺失=灰。 */
export function freshnessItemTone(status: FreshnessStatus): "ok" | "warning" | "muted" {
  if (status === "ok") return "ok";
  if (status === "missing" || status === "unavailable") return "muted";
  return "warning";
}

/** 单次新鲜度请求超时（轮询必须有上限，避免挂起的请求把下一轮挤掉）。 */
export const FRESHNESS_REQUEST_TIMEOUT_MS = 10_000;

/** 组合调用方的取消信号与 10s 超时信号；任一触发都会中止请求。 */
function freshnessSignal(signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(FRESHNESS_REQUEST_TIMEOUT_MS);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

/** 拉取数据新鲜度（客户端）；失败返回 null，由调用方决定占位与重试。 */
export async function fetchDataFreshness(
  signal?: AbortSignal,
): Promise<DataFreshness | null> {
  try {
    const response = await fetch(FRESHNESS_API_PATH, {
      signal: freshnessSignal(signal),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return mapFreshness(await response.json());
  } catch {
    return null;
  }
}
