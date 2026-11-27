/**
 * `/valuation/[code]` 的展示格式化与语气色。
 *
 * 基础数字/百分比格式化复用 `valuation-mock.ts`（全站唯一入口），这里只补充
 * 详情页特有的「亿元」「0~100 分位」「样本是否可用」三类逻辑。
 */

import type {
  DetailTrackerFund,
  PercentileSummary,
} from "./valuation-detail-types";
import {
  EMPTY_DISPLAY,
  formatNumber,
  formatPlainPct,
  formatSignedPct,
} from "./valuation-mock";

export { EMPTY_DISPLAY, formatNumber, formatPlainPct, formatSignedPct };

/** 后端分位样本门槛：有效样本 <120 时不输出 pct。 */
export const MIN_PERCENTILE_SAMPLE = 120;

/** 元 -> 亿元，保留 2 位小数；缺失显示「—」。 */
export function formatAumYi(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_DISPLAY;
  return (value / 1e8).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** 0~100 分位 -> 百分比文本（与 DB/API 同口径，不再 ×100）。 */
export function formatPercentileValue(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_DISPLAY;
  return `${value.toFixed(digits)}%`;
}

/**
 * 分位语气色（**全站唯一实现**，`valuation-ui.tsx` 只做 re-export，勿再复制阈值）。
 *
 * 阈值口径：<30 分位=便宜=success，30~70=中性=primary（sky 蓝），>70=高估=destructive。
 * 入参为 0~100（API 口径），与涨跌色 text-up/text-down 解耦。
 */
export function percentileTone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "text-muted-foreground";
  if (value < 30) return "text-success";
  if (value > 70) return "text-destructive";
  return "text-primary";
}

/** 分位 -> 「低估 / 中性 / 高估」；与 percentileTone 共用同一组阈值，样本不足返回 null。 */
export function percentileLabel(
  value: number | null | undefined,
): "低估" | "中性" | "高估" | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (value < 30) return "低估";
  if (value > 70) return "高估";
  return "中性";
}

/**
 * 跟踪基金规模口径（元）：优先最新基金规模 fund_scale，缺失回退快照规模 aum。
 *
 * 明细表、Top10 条形图与「规模合计」必须共用本函数，否则同一页面会出现
 * 「各行相加 ≠ 合计」的口径分叉。
 */
export function trackerFundScale(
  fund: Pick<DetailTrackerFund, "fund_scale" | "aum">,
): number | null {
  const scale = fund.fund_scale ?? fund.aum;
  return scale != null && Number.isFinite(scale) ? scale : null;
}

/** 跟踪基金规模合计（元）；无有效规模时返回 null（不伪造 0）。 */
export function sumTrackerFundScale(
  funds: readonly Pick<DetailTrackerFund, "fund_scale" | "aum">[],
): number | null {
  let total: number | null = null;
  for (const fund of funds) {
    const scale = trackerFundScale(fund);
    if (scale != null) total = (total ?? 0) + scale;
  }
  return total;
}

/** 分位统计是否可用（pct 非空且样本 ≥120）。 */
export function hasUsablePercentile(
  stats: PercentileSummary | null | undefined,
): stats is PercentileSummary & { pct: number } {
  return Boolean(
    stats &&
      stats.pct != null &&
      Number.isFinite(stats.pct) &&
      stats.sample_size >= MIN_PERCENTILE_SAMPLE,
  );
}

/** 分位不可用时的说明文案。 */
export function percentileUnavailableText(
  stats: PercentileSummary | null | undefined,
): string {
  if (!stats) return "暂无分位统计";
  return `样本不足（${formatNumber(stats.sample_size, 0)} < ${MIN_PERCENTILE_SAMPLE}）`;
}

/**
 * 跟踪误差告警阈值（百分数点）：TE > 5% 视为跟踪质量偏弱，UI 用 warning 提示。
 * 口径：bp_fund_risk.tracking_error_1y（acc_nav / 回退 ETF 后复权，年化日收益差标准差）。
 */
export const TE_WARNING_THRESHOLD_PCT = 5;

export type TrackingErrorTone = "warning" | "normal" | "missing";

/** TE 语气：>5% 告警（琥珀），否则普通数值，缺失单独标记。 */
export function trackingErrorTone(
  value: number | null | undefined,
): TrackingErrorTone {
  if (value == null || !Number.isFinite(value)) return "missing";
  return value > TE_WARNING_THRESHOLD_PCT ? "warning" : "normal";
}

/** TE 文字色 class（告警=warning，普通=默认，缺失=muted）。 */
export function trackingErrorClass(
  value: number | null | undefined,
): string {
  const tone = trackingErrorTone(value);
  if (tone === "warning") return "text-warning font-medium";
  if (tone === "missing") return "text-muted-foreground";
  return "";
}

/** ISO datetime -> "YYYY-MM-DD HH:mm"（截断字符串，不做时区换算；用于「更新于」）。 */
export function formatUpdatedAtCompact(
  value: string | null | undefined,
): string {
  if (!value) return EMPTY_DISPLAY;
  return value.replace("T", " ").slice(0, 16);
}

/** 「跟踪基金」右上角的元信息：规模合计 · 数据截至 · 更新于。 */
export function formatTrackerMeta(args: {
  totalAum: number | null;
  asOf: string | null | undefined;
  updatedAt: string | null | undefined;
}): string {
  const aum = args.totalAum == null ? EMPTY_DISPLAY : `${formatAumYi(args.totalAum)} 亿元`;
  return [
    `规模合计 ${aum}`,
    `数据截至 ${args.asOf ?? EMPTY_DISPLAY}`,
    `更新于 ${formatUpdatedAtCompact(args.updatedAt)}`,
  ].join(" · ");
}

/** 跟踪基金表可排序的指标：规模/费率/跟踪误差/年化波动/近 1 年收益。 */
export type TrackerFundSortKey =
  | "scale"
  | "management_fee"
  | "custody_fee"
  | "ann_vol_1y"
  | "tracking_error_1y"
  | "ret_12m";

export type SortDirection = "asc" | "desc";

/** 跟踪基金排序取值（规模走统一口径 trackerFundScale；缺失返回 null）。 */
export function trackerFundSortValue(
  fund: DetailTrackerFund,
  key: TrackerFundSortKey,
): number | null {
  if (key === "scale") return trackerFundScale(fund);
  const value = fund[key];
  return value != null && Number.isFinite(value) ? value : null;
}

/**
 * 跟踪基金前端纯排序：升/降序切换，**null 恒垫底**（不参与方向翻转）。
 * 非数值字段（名称）不参与，由调用方只在可排序列挂按钮。
 */
export function sortTrackerFunds(
  funds: readonly DetailTrackerFund[],
  key: TrackerFundSortKey,
  direction: SortDirection,
): DetailTrackerFund[] {
  const sign = direction === "asc" ? 1 : -1;
  return funds.slice().sort((a, b) => {
    const left = trackerFundSortValue(a, key);
    const right = trackerFundSortValue(b, key);
    if (left == null && right == null) return 0;
    if (left == null) return 1;
    if (right == null) return -1;
    return sign * (left - right);
  });
}