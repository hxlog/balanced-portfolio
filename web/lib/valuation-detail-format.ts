/**
 * `/valuation/[code]` 的展示格式化与语气色。
 *
 * 基础数字/百分比格式化复用 `valuation-mock.ts`（全站唯一入口），这里只补充
 * 详情页特有的「亿元」「0~100 分位」「样本是否可用」三类逻辑。
 */

import type { PercentileSummary } from "./valuation-detail-types";
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
 * 分位语气色：低分位=便宜=success，中间=warning，高分位=高估=destructive。
 * 入参为 0~100（API 口径），与涨跌色 text-up/text-down 解耦。
 */
export function percentileTone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "text-muted-foreground";
  if (value <= 30) return "text-success";
  if (value >= 70) return "text-destructive";
  return "text-warning";
}

/** 分位 -> 「低估 / 中性 / 高估」；样本不足返回 null。 */
export function percentileLabel(
  value: number | null | undefined,
): "低估" | "中性" | "高估" | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (value <= 30) return "低估";
  if (value >= 70) return "高估";
  return "中性";
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
