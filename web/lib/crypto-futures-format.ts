/**
 * 加密合约看板的纯函数：API 归一化 + 数字/时间格式化。
 *
 * 这里不依赖服务端能力，server component 与 client chart 共用，
 * 保证表格、汇总卡与 ECharts tooltip 的口径完全一致。
 */
import type {
  CryptoFuturesContract,
  CryptoFuturesPercentile,
  CryptoFuturesPercentiles,
  CryptoFuturesSeriesPoint,
  CryptoFuturesSummary,
} from "./crypto-futures-types";

// ---------------------------------------------------------------------------
// 归一化（宽松解析后端 JSON，NaN/缺字段一律降级为 null/空值）
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function normalizePercentiles(value: unknown): CryptoFuturesPercentiles {
  const record = asRecord(value);
  if (!record) return {};
  const result: CryptoFuturesPercentiles = {};
  for (const [key, entry] of Object.entries(record)) {
    const row = asRecord(entry);
    if (!row) continue;
    const pct = asFiniteNumber(row.pct);
    result[key] = {
      // 后端 DDL 约束为 0~100；这里再夹一次，避免脏数据画爆分位条。
      pct: pct == null ? null : Math.min(100, Math.max(0, pct)),
      sample_size: asFiniteNumber(row.sample_size),
      as_of: asText(row.as_of),
    };
  }
  return result;
}

export function normalizeSummary(value: unknown): CryptoFuturesSummary | null {
  const row = asRecord(value);
  if (!row) return null;
  return {
    contracts: asFiniteNumber(row.contracts) ?? 0,
    total_oi_notional: asFiniteNumber(row.total_oi_notional) ?? 0,
    weighted_long_short_ratio: asFiniteNumber(row.weighted_long_short_ratio),
    median_taker_buy_sell_ratio: asFiniteNumber(row.median_taker_buy_sell_ratio),
    contracts_with_top_data: asFiniteNumber(row.contracts_with_top_data),
    total_oi_change_24h_pct: asFiniteNumber(row.total_oi_change_24h_pct),
    weighted_funding_rate: asFiniteNumber(row.weighted_funding_rate),
    smart_money_divergence: asFiniteNumber(row.smart_money_divergence),
    weighted_long_short_basis: asText(row.weighted_long_short_basis) ?? undefined,
    weighted_long_short_note: asText(row.weighted_long_short_note) ?? undefined,
    latest_captured_at: asText(row.latest_captured_at),
  };
}

export function normalizeContract(value: unknown): CryptoFuturesContract | null {
  const row = asRecord(value);
  if (!row) return null;
  const contractCode = asText(row.contract_code);
  if (!contractCode) return null;

  return {
    contract_code: contractCode,
    base_asset: asText(row.base_asset) ?? contractCode.replace(/USDT$/, ""),
    oi_notional_rank: asFiniteNumber(row.oi_notional_rank),
    captured_at: asText(row.captured_at),
    mark_price: asFiniteNumber(row.mark_price),
    index_price: asFiniteNumber(row.index_price),
    oi_contracts: asFiniteNumber(row.oi_contracts),
    oi_notional: asFiniteNumber(row.oi_notional),
    long_short_ratio: asFiniteNumber(row.long_short_ratio),
    taker_buy_sell_ratio: asFiniteNumber(row.taker_buy_sell_ratio),
    basis_pct: asFiniteNumber(row.basis_pct),
    funding_rate: asFiniteNumber(row.funding_rate),
    funding_time: asText(row.funding_time),
    funding_percentile_30d: asFiniteNumber(row.funding_percentile_30d),
    oi_change_24h_pct: asFiniteNumber(row.oi_change_24h_pct),
    top_account_ratio: asFiniteNumber(row.top_account_ratio),
    top_position_ratio: asFiniteNumber(row.top_position_ratio),
    smart_money_divergence: asFiniteNumber(row.smart_money_divergence),
    percentiles: normalizePercentiles(row.percentiles),
  };
}

export function normalizeSeriesPoint(value: unknown): CryptoFuturesSeriesPoint | null {
  const row = asRecord(value);
  if (!row) return null;
  const capturedAt = asText(row.captured_at);
  if (!capturedAt) return null;

  return {
    captured_at: capturedAt,
    mark_price: asFiniteNumber(row.mark_price),
    oi_notional: asFiniteNumber(row.oi_notional),
    long_short_ratio: asFiniteNumber(row.long_short_ratio),
    taker_buy_sell_ratio: asFiniteNumber(row.taker_buy_sell_ratio),
    basis_pct: asFiniteNumber(row.basis_pct),
    top_account_ratio: asFiniteNumber(row.top_account_ratio),
    top_position_ratio: asFiniteNumber(row.top_position_ratio),
  };
}

// ---------------------------------------------------------------------------
// 选择 / 排序辅助
// ---------------------------------------------------------------------------

/** 合约榜默认排序：OI 名义值倒序，缺失值沉底。 */
export function sortContractsByOi(
  contracts: readonly CryptoFuturesContract[],
): CryptoFuturesContract[] {
  return [...contracts].sort((a, b) => {
    if (a.oi_notional == null && b.oi_notional == null) {
      return (a.oi_notional_rank ?? Number.MAX_SAFE_INTEGER)
        - (b.oi_notional_rank ?? Number.MAX_SAFE_INTEGER);
    }
    if (a.oi_notional == null) return 1;
    if (b.oi_notional == null) return -1;
    return b.oi_notional - a.oi_notional;
  });
}

/** 取 30 日多空比分位；兼容 `long_short_ratio:30` 及下划线变体。 */
export function getLongShortPercentile30(
  contract: CryptoFuturesContract,
): CryptoFuturesPercentile | null {
  const entries = Object.entries(contract.percentiles);
  const direct = contract.percentiles["long_short_ratio:30"];
  if (direct) return direct;
  const match = entries.find(
    ([key]) =>
      key.startsWith("long_short_ratio")
      && (key.endsWith(":30") || key.includes(":30") || key.includes("_30")),
  );
  return match?.[1] ?? null;
}

/** 汇总接口失败时，从合约榜反推最近快照时间。 */
export function latestContractCapturedAt(
  contracts: readonly CryptoFuturesContract[],
): string | null {
  let latest: string | null = null;
  let latestMs = Number.NEGATIVE_INFINITY;
  for (const contract of contracts) {
    if (!contract.captured_at) continue;
    const ms = Date.parse(contract.captured_at);
    if (Number.isFinite(ms) && ms > latestMs) {
      latest = contract.captured_at;
      latestMs = ms;
    }
  }
  return latest;
}

// ---------------------------------------------------------------------------
// 数字格式化
// ---------------------------------------------------------------------------

const INT_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const PRICE_2_FORMAT = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const PRICE_4_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
const PRICE_6_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });

export function formatCount(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return INT_FORMAT.format(value);
}

export function formatPrice(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1000) return PRICE_2_FORMAT.format(value);
  if (abs >= 1) return PRICE_4_FORMAT.format(value);
  if (abs >= 0.01) return PRICE_6_FORMAT.format(value);
  if (abs === 0) return "0.00";
  return value.toPrecision(4);
}

/** 汇总卡/表格用：中文亿/十亿单位。 */
export function formatNotional(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)} 万亿`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)} 十亿`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)} 亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)} 万`;
  return INT_FORMAT.format(value);
}

/** ECharts 坐标轴用紧凑单位（避免中文单位把轴宽挤爆）。 */
export function formatNotionalAxis(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return value.toFixed(0);
}

export function formatPriceAxis(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}k`;
  if (abs >= 1) return value.toFixed(2);
  if (abs >= 0.01) return value.toFixed(4);
  return value === 0 ? "0" : value.toExponential(1);
}

export function formatRatio(value: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

export function formatTakerRatio(value: number | null): string {
  return formatRatio(value, 3);
}

export function formatPercentile(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}%`;
}

export function formatSignedPct(value: number | null, digits = 3): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

// ---------------------------------------------------------------------------
// 时间格式化（统一上海时区；formatToParts 拼装避免 Node/浏览器 locale 差异）
// ---------------------------------------------------------------------------

const SHANGHAI_DATE_TIME = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const SHANGHAI_CHART_DATE_TIME = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const SHANGHAI_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function partsMap(parts: Intl.DateTimeFormatPart[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const part of parts) {
    if (part.type !== "literal") map[part.type] = part.value;
  }
  return map;
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** `2026-11-14T13:25:00+00:00` → `2026-11-14 21:25`（上海时间）。 */
export function formatShanghaiDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  try {
    const p = partsMap(SHANGHAI_DATE_TIME.formatToParts(date));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
  } catch {
    return date.toISOString();
  }
}

/** 图表 x 轴标签；跨日时带 MM-DD，否则只显示 HH:mm。 */
export function formatShanghaiChartLabel(iso: string, includeDate: boolean): string {
  const date = parseDate(iso);
  if (!date) return "";
  try {
    const p = partsMap(SHANGHAI_CHART_DATE_TIME.formatToParts(date));
    return includeDate ? `${p.month}-${p.day} ${p.hour}:${p.minute}` : `${p.hour}:${p.minute}`;
  } catch {
    return iso.slice(11, 16);
  }
}

/** 用于判断 24h 序列是否跨上海自然日。 */
export function shanghaiDayKey(iso: string): string {
  const date = parseDate(iso);
  if (!date) return "";
  try {
    return SHANGHAI_DAY.format(date);
  } catch {
    return iso.slice(0, 10);
  }
}

/** 千分位格式化（USD 金额，不带中文单位）。 */
export function formatThousands(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

/** 资金费率（小数 → 带 4 位小数的百分比）。 */
export function formatFundingRate(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return (value * 100).toFixed(4) + "%";
}

/** 百分数（已是百分数点）。 */
export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits) + "%";
}
