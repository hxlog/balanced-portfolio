/** 一篮子模式的权重排序、配色与数字格式（纯函数，便于单测）。 */

import { basketKey, type BasketWeight } from "./basket-types";

export function formatPct(
  value: number | null | undefined,
  digits = 1,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  // 入参是小数、展示时 ×100：阈值必须按「百分数点」换算回小数，
  // 否则 digits=2 时 0.0003（0.03%）会被误判成 0.00%（原文 0.5*10^-digits=0.005）。
  const epsilon = 0.5 * 10 ** -(digits + 2);
  const safe = Math.abs(value) < epsilon ? 0 : value;
  return `${(safe * 100).toFixed(digits)}%`;
}

export function formatSignedPct(
  value: number | null | undefined,
  digits = 1,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const text = formatPct(value, digits);
  return value > 0 ? `+${text}` : text;
}

export function formatRatio(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

/**
 * 回测净值图实际存在的系列。
 * latest_result 还原 / 旧后端响应可能缺 equal_weight_nav 或 rebalance_events，
 * 缺失时图例与说明文案不得再承诺该系列（避免「图例有、曲线没有」）。
 */
export function basketNavSeriesFlags(
  result:
    | {
        equal_weight_nav?: readonly unknown[] | null;
        rebalance_events?: readonly unknown[] | null;
      }
    | null
    | undefined,
): { equalWeight: boolean; rebalance: boolean } {
  return {
    equalWeight: (result?.equal_weight_nav?.length ?? 0) > 0,
    rebalance: (result?.rebalance_events?.length ?? 0) > 0,
  };
}

/** 净值图图例：只列真实画出的系列（篮子净值恒存在）。 */
export function basketNavLegend(
  result:
    | {
        equal_weight_nav?: readonly unknown[] | null;
        rebalance_events?: readonly unknown[] | null;
      }
    | null
    | undefined,
): string[] {
  const flags = basketNavSeriesFlags(result);
  return [
    "篮子净值",
    ...(flags.equalWeight ? ["等权净值"] : []),
    ...(flags.rebalance ? ["调仓"] : []),
  ];
}

/**
 * 把用户输入的风险预算（相对权重）归一化到合计 = 1。
 * 负数/NaN/Infinity 按 0 处理；全部为 0 时退化为等权。
 * 空输入返回空对象（调用方据此决定是否携带 risk_budget）。
 */
export function normalizeRiskBudget(
  raw: Record<string, number>,
): Record<string, number> {
  const keys = Object.keys(raw);
  if (keys.length === 0) return {};

  const clean: Record<string, number> = {};
  let total = 0;
  for (const key of keys) {
    const value = Number(raw[key]);
    const weight = Number.isFinite(value) && value > 0 ? value : 0;
    clean[key] = weight;
    total += weight;
  }

  if (total <= 0) {
    const equal = 1 / keys.length;
    for (const key of keys) clean[key] = equal;
  } else {
    for (const key of keys) clean[key] /= total;
  }

  // 让最大项吸收浮点残差，保证后端 `abs(sum - 1) <= 1e-6` 校验恒过。
  const last = keys[keys.length - 1];
  const sum = keys.reduce((acc, key) => acc + clean[key], 0);
  clean[last] += 1 - sum;
  return clean;
}

/**
 * 权重条/甜甜圈共用的 sky 色阶。
 * 明暗两套都保持在 195–205° 色相（sky/cyan），通过饱和度与明度区分资产。
 */
export function basketSkyColor(index: number, isDark: boolean): string {
  const i = Math.max(0, Math.floor(index));
  const hue = 195 + (i % 6) * 2; // 195,197,199,201,203,205
  const saturation = 76 + (Math.floor(i / 6) % 3) * 8; // 76/84/92
  const lightness = isDark
    ? 48 + (i % 4) * 6 // 48–66
    : 36 + (i % 4) * 8; // 36–60
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}

export interface BasketWeightRow {
  key: string;
  name: string;
  symbol: string;
  source: string;
  weight: number;
  color: string;
}

/**
 * 权重按降序排列并绑定颜色。名称缺失时回退 symbol；
 * 0 权重仍保留（让「未激活资产」在列表中可见），donut 侧自行过滤。
 */
export function basketWeightRows(
  weights: BasketWeight[],
  nameByKey: ReadonlyMap<string, string>,
  isDark: boolean,
): BasketWeightRow[] {
  return weights
    .map((row) => {
      const key = basketKey(row.symbol, row.source);
      const value = Number(row.weight);
      return {
        key,
        name: nameByKey.get(key) ?? row.symbol,
        symbol: row.symbol,
        source: row.source,
        weight: Number.isFinite(value) ? Math.max(0, value) : 0,
      };
    })
    .sort(
      (a, b) =>
        b.weight - a.weight || a.name.localeCompare(b.name, "zh-CN"),
    )
    .map((row, index) => ({
      ...row,
      color: basketSkyColor(index, isDark),
    }));
}
