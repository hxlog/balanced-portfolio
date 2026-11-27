/**
 * /valuation 图表的纯计算层（可单元测试，不依赖 React/ECharts 实例）。
 *
 * 内容：
 * - 红利指数吸引力：绝对/相对模式的取点、对数回归、中位数十字线、四象限归类；
 * - MVI：按 ISO 周去重平滑（近 5 年周频）、zone 阈值（与后端 compute_mvi.py 一致）、
 *   小走势图与双轴 overlay 图的 ECharts option 构造。
 *
 * 所有图表色值都来自 `chart-theme`（sky 主色、绿涨红跌、语义色），不在组件里硬编码。
 */

import { withAlpha, type ChartTheme } from "./chart-theme";
import type { IndexQuoteRow, MviPoint } from "./valuation-types";

export type DividendMode = "absolute" | "relative";

export interface DividendPoint {
  name: string;
  code: string;
  x: number;
  y: number;
  /** 气泡大小：跟踪基金规模（元）；未知时为 0。 */
  size: number;
  category: string;
  pb: number | null;
  dividend: number | null;
  pbPercentile: number | null;
  dividendPercentile: number | null;
}

function num(value: number | null | undefined): number | null {
  return value != null && Number.isFinite(value) ? value : null;
}

/** 红利/股息类指数（绝对与相对模式共用同一候选池）。 */
export function isDividendRow(row: IndexQuoteRow): boolean {
  return row.name.includes("红利") || row.name.includes("股息");
}

/**
 * 取红利指数散点：
 * - 绝对模式：x=PB（必须 >0，log 轴）、y=股息率；
 * - 相对模式：x=PB 5y 分位、y=股息率 5y 分位（0~100），无需基金规模。
 * 缺失值一律剔除（不补 0），按基金规模降序（气泡大到小更易读）。
 */
export function dividendPoints(
  rows: readonly IndexQuoteRow[],
  mode: DividendMode,
): DividendPoint[] {
  const points: DividendPoint[] = [];
  for (const row of rows) {
    if (!isDividendRow(row)) continue;
    const pb = num(row.pb);
    const dividend = num(row.dividend_yield_pct);
    const pbPercentile = num(row.pb_percentile);
    const dividendPercentile = num(row.dividend_percentile);
    const size = Math.max(0, num(row.fund_aum) ?? 0);
    let x: number | null = null;
    let y: number | null = null;
    if (mode === "absolute") {
      if (pb != null && pb > 0 && dividend != null) {
        x = pb;
        y = dividend;
      }
    } else if (pbPercentile != null && dividendPercentile != null) {
      x = pbPercentile;
      y = dividendPercentile;
    }
    if (x == null || y == null) continue;
    points.push({
      name: row.name,
      code: row.index_code,
      x,
      y,
      size,
      category: row.category,
      pb,
      dividend,
      pbPercentile,
      dividendPercentile,
    });
  }
  return points.sort((a, b) => b.size - a.size || a.code.localeCompare(b.code));
}

/** 中位数（偶数个取中间两个均值）；空数组返回 null。 */
export function medianOf(values: readonly number[]): number | null {
  const list = values.filter((value) => Number.isFinite(value)).slice().sort((a, b) => a - b);
  if (list.length === 0) return null;
  const mid = Math.floor(list.length / 2);
  return list.length % 2 === 1 ? list[mid] : (list[mid - 1] + list[mid]) / 2;
}

export interface LinearFit {
  slope: number;
  intercept: number;
  r2: number;
  equation: string;
}

function fitFromPairs(pairs: ReadonlyArray<{ u: number; v: number }>): LinearFit | null {
  const n = pairs.length;
  if (n < 3) return null;
  let sumU = 0;
  let sumV = 0;
  let sumUV = 0;
  let sumUU = 0;
  let sumVV = 0;
  for (const { u, v } of pairs) {
    sumU += u;
    sumV += v;
    sumUV += u * v;
    sumUU += u * u;
    sumVV += v * v;
  }
  const denom = n * sumUU - sumU * sumU;
  if (Math.abs(denom) < 1e-12) return null;
  const slope = (n * sumUV - sumU * sumV) / denom;
  const intercept = (sumV - slope * sumU) / n;
  const numerator = n * sumUV - sumU * sumV;
  const denominator = Math.sqrt(
    Math.max(1e-12, (n * sumUU - sumU * sumU) * (n * sumVV - sumV * sumV)),
  );
  const r2 = (numerator / denominator) ** 2;
  return { slope, intercept, r2, equation: "" };
}

/** 线性回归 y = slope·x + intercept（相对模式用）。 */
export function linearFit(points: ReadonlyArray<{ x: number; y: number }>): LinearFit | null {
  const fit = fitFromPairs(points.map((point) => ({ u: point.x, v: point.y })));
  if (!fit) return null;
  return {
    ...fit,
    equation:
      "y = " + fit.slope.toFixed(3) + "x " + (fit.intercept >= 0 ? "+ " : "- ") +
      Math.abs(fit.intercept).toFixed(3),
  };
}

/**
 * 对数回归 y = slope·ln(x) + intercept（log 轴，回归线口径与坐标轴一致）。
 *
 * 方程文本可传 `labels` 用业务字段名替换通用的 x/y（如 "ROE = 2.1·ln(PE) + 1.2"），
 * 避免图上标注与实际指标错位。
 */
export function logFit(
  points: ReadonlyArray<{ x: number; y: number }>,
  labels?: { xName?: string; yName?: string },
): LinearFit | null {
  if (points.some((point) => !(point.x > 0))) return null;
  const fit = fitFromPairs(points.map((point) => ({ u: Math.log(point.x), v: point.y })));
  if (!fit) return null;
  const xName = labels?.xName ?? "x";
  const yName = labels?.yName ?? "y";
  return {
    ...fit,
    equation:
      yName + " = " + fit.slope.toFixed(3) + "·ln(" + xName + ") " +
      (fit.intercept >= 0 ? "+ " : "- ") + Math.abs(fit.intercept).toFixed(3),
  };
}

/** 在对数轴上均匀采样回归线端点（避免直接用 min/max 直线造成视觉斜率失真）。 */
export function sampleLogLine(
  points: ReadonlyArray<{ x: number }>,
  fit: LinearFit,
  count = 24,
): Array<[number, number]> {
  if (points.length === 0 || count < 2) return [];
  const xs = points.map((point) => point.x).filter((value) => value > 0);
  if (xs.length === 0) return [];
  const min = Math.min(...xs);
  const max = Math.max(...xs);
  if (!(max > min)) return [];
  const logMin = Math.log(min);
  const logMax = Math.log(max);
  const samples: Array<[number, number]> = [];
  for (let index = 0; index < count; index += 1) {
    const x = Math.exp(logMin + ((logMax - logMin) * index) / (count - 1));
    samples.push([x, fit.slope * Math.log(x) + fit.intercept]);
  }
  return samples;
}

/** 绝对模式的 log 轴范围（正数、留 8% 视觉 padding）。 */
export function positiveLogRange(values: readonly number[]): [number, number] {
  const xs = values.filter((value) => value > 0);
  if (xs.length === 0) return [0.1, 10];
  const min = Math.min(...xs);
  const max = Math.max(...xs);
  const factor = 1.08;
  const low = min / factor;
  const high = max * factor;
  return low < high ? [low, high] : [low * 0.9, high * 1.1];
}

export interface DividendQuadrant {
  key: "cheap_high_yield" | "rich_high_yield" | "cheap_low_yield" | "rich_low_yield";
  label: string;
  note: string;
  tone: "success" | "warning" | "primary" | "destructive";
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

/**
 * 相对模式的四象限（x=PB 分位，y=股息率分位；50 为分界）。
 * 左下（低 PB 分位 + 高股息分位）最具吸引力。
 */
export const DIVIDEND_QUADRANTS: readonly DividendQuadrant[] = [
  { key: "cheap_high_yield", label: "低估值 · 高股息", note: "最具吸引力", tone: "success", xMin: 0, xMax: 50, yMin: 50, yMax: 100 },
  { key: "rich_high_yield", label: "高估值 · 高股息", note: "股息尚可，估值偏高", tone: "warning", xMin: 50, xMax: 100, yMin: 50, yMax: 100 },
  { key: "cheap_low_yield", label: "低估值 · 低股息", note: "估值低，股息吸引力弱", tone: "primary", xMin: 0, xMax: 50, yMin: 0, yMax: 50 },
  { key: "rich_low_yield", label: "高估值 · 低股息", note: "最不具吸引力", tone: "destructive", xMin: 50, xMax: 100, yMin: 0, yMax: 50 },
] as const;

/** 分位点所属象限；恰好 50 归入「高」侧，避免落在边界上无归属。 */
export function dividendQuadrant(x: number, y: number): DividendQuadrant["key"] {
  if (x < 50) return y >= 50 ? "cheap_high_yield" : "cheap_low_yield";
  return y >= 50 ? "rich_high_yield" : "rich_low_yield";
}

/** MVI zone 阈值与后端 scripts/compute_mvi.py:zone_of 一致。 */
export function zoneOfMvi(mvi: number): string {
  if (!Number.isFinite(mvi)) return "—";
  if (mvi < 20) return "极度低估";
  if (mvi < 40) return "低估";
  if (mvi < 60) return "合理";
  if (mvi < 80) return "高估";
  return "极度高估";
}

/** ISO 周键（YYYY-Www）；非法日期返回 null。 */
export function isoWeekKey(date: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const current = new Date(Date.UTC(year, month - 1, day));
  if (Number.isNaN(current.getTime())) return null;
  const dayNumber = current.getUTCDay() || 7;
  current.setUTCDate(current.getUTCDate() + 4 - dayNumber);
  const yearStart = new Date(Date.UTC(current.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((current.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return current.getUTCFullYear() + "-W" + String(week).padStart(2, "0");
}

/** 是否周末（MVI 只应在交易日产生点，周末点一律视为脏数据丢弃）。 */
export function isWeekendDate(date: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
  if (!match) return false;
  const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (Number.isNaN(parsed.getTime())) return false;
  const day = parsed.getUTCDay();
  return day === 0 || day === 6;
}

/**
 * 近 5 年周频平滑：丢弃周末点后，同一 ISO 周只保留最后一个交易日（去重），
 * 后端已返回周频时等价于去重；日频历史也能落到周频。
 */
export function weeklyLast(points: readonly MviPoint[]): MviPoint[] {
  const sorted = points
    .filter((point) => point && point.as_of && !isWeekendDate(point.as_of))
    .slice()
    .sort((a, b) => a.as_of.localeCompare(b.as_of));
  const byWeek = new Map<string, MviPoint>();
  for (const point of sorted) {
    const key = isoWeekKey(point.as_of);
    if (!key) continue;
    byWeek.set(key, point);
  }
  return [...byWeek.values()].sort((a, b) => a.as_of.localeCompare(b.as_of));
}

const ZONE_TONES = ["success", "success", "primary", "warning", "destructive"] as const;

function zoneColor(theme: ChartTheme, index: number): string {
  const tone = ZONE_TONES[index];
  const base =
    tone === "success" ? theme.up : tone === "destructive" ? theme.down : theme.palette[0];
  return withAlpha(base, 0.05);
}

/** MVI 近 5 年小走势图（分位带背景 + hover 显示日期/MVI/zone）。 */
export function buildMviTrendOption(
  points: readonly MviPoint[],
  theme: ChartTheme,
): Record<string, unknown> {
  const usable = weeklyLast(points).filter((point) => point.mvi != null);
  const dates = usable.map((point) => point.as_of);
  const values = usable.map((point) => Number(point.mvi));
  return {
    animation: false,
    grid: { left: 2, right: 4, top: 6, bottom: 4, containLabel: false },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (params: Array<{ dataIndex?: number; value?: unknown }>) => {
        const index = params?.[0]?.dataIndex ?? 0;
        const value = Number(values[index]);
        if (!Number.isFinite(value)) return "";
        return (
          "<b>" + (dates[index] ?? "") + "</b><br/>MVI " + value.toFixed(2) +
          " · " + zoneOfMvi(value)
        );
      },
    },
    xAxis: { type: "category", show: false, boundaryGap: false, data: dates },
    yAxis: { type: "value", show: false, min: 0, max: 100 },
    series: [
      {
        type: "line",
        showSymbol: false,
        smooth: 0.35,
        data: values,
        lineStyle: { color: theme.palette[0], width: 1.6 },
        areaStyle: { color: withAlpha(theme.palette[0], 0.1) },
        markArea: {
          silent: true,
          data: [0, 20, 40, 60, 80].map((from, index) => [
            {
              yAxis: from,
              itemStyle: { color: zoneColor(theme, index) },
            },
            { yAxis: from + 20 },
          ]),
        },
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          data: [{ yAxis: 30 }, { yAxis: 70 }].map((line) => ({
            ...line,
            lineStyle: { color: withAlpha(theme.subtext, 0.4), type: "dashed", width: 1 },
          })),
        },
      },
    ],
  };
}

export interface MviOverlayInput {
  mvi: readonly MviPoint[];
  indexPoints: ReadonlyArray<{ date: string; close: number }>;
  indexName: string;
  theme: ChartTheme;
}

/** MVI 展开的双轴图：左轴 MVI（sky）、右轴指数点位（amber），time 轴适配不同频率。 */
export function buildMviOverlayOption(input: MviOverlayInput): Record<string, unknown> {
  const { mvi, indexPoints, indexName, theme } = input;
  const mviData = weeklyLast(mvi)
    .filter((point) => point.mvi != null)
    .map((point) => [point.as_of, Number(point.mvi)]);
  const indexData = indexPoints.map((point) => [point.date, point.close]);
  return {
    animation: false,
    grid: { left: 8, right: 16, top: 38, bottom: 22, containLabel: true },
    legend: {
      top: 2,
      right: 4,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 3,
      textStyle: { color: theme.subtext, fontSize: 10 },
      data: ["MVI", indexName],
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", label: { backgroundColor: theme.tooltipBorder } },
      confine: true,
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 12 },
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: theme.axisLine } },
      axisTick: { show: false },
      axisLabel: { color: theme.subtext, fontSize: 10, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: [
      {
        type: "value",
        name: "MVI",
        min: 0,
        max: 100,
        nameTextStyle: { color: theme.subtext, fontSize: 10 },
        axisLabel: { color: theme.subtext, fontSize: 10 },
        splitLine: { lineStyle: { color: theme.splitLine } },
      },
      {
        type: "value",
        name: indexName,
        scale: true,
        nameTextStyle: { color: theme.subtext, fontSize: 10 },
        axisLabel: { color: theme.subtext, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "MVI",
        type: "line",
        yAxisIndex: 0,
        showSymbol: false,
        smooth: 0.35,
        data: mviData,
        lineStyle: { color: theme.palette[0], width: 1.8 },
        areaStyle: { color: withAlpha(theme.palette[0], 0.08) },
      },
      {
        name: indexName,
        type: "line",
        yAxisIndex: 1,
        showSymbol: false,
        smooth: 0.2,
        data: indexData,
        lineStyle: { color: theme.palette[2], width: 1.8 },
      },
    ],
  };
}

/**
 * 把（日频）指数点位对齐到估值序列的日期：取「日期 ≤ 目标日」的最后一个收盘价。
 * 估值序列是周频，行情是日频，双轴图共用 category 轴时必须先对齐。
 */
export function alignPriceToDates(
  dates: readonly string[],
  priceSeries: ReadonlyArray<{ trade_date: string; close: number }>,
): Array<number | null> {
  const sorted = priceSeries
    .filter((point) => point && point.trade_date && Number.isFinite(point.close))
    .slice()
    .sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  const result: Array<number | null> = [];
  let cursor = 0;
  let last: number | null = null;
  for (const date of dates) {
    while (cursor < sorted.length && sorted[cursor].trade_date <= date) {
      last = sorted[cursor].close;
      cursor += 1;
    }
    result.push(last);
  }
  return result;
}

export interface ValuationPriceBandStats {
  p20: number | null;
  p50: number | null;
  p80: number | null;
  mean: number | null;
  sd: number | null;
  sample_size: number;
}

export interface ValuationPriceChartInput {
  series: ReadonlyArray<{ trade_date: string; value: number }>;
  priceSeries: ReadonlyArray<{ trade_date: string; close: number }>;
  stats: ValuationPriceBandStats | null;
  /** 指标名（PE/PB/股息率/风险溢价），用于图例和 tooltip。 */
  metricLabel: string;
  /** 估值单位：x / %。 */
  unit: string;
  mode: "pct" | "sd";
  sigma: number;
  /** 20~80 分位区间底色开关。 */
  showBandArea: boolean;
  theme: ChartTheme;
}

/**
 * 指数详情「估值 × 点位」双轴图（需求 8 的可视化增强）：
 * 左轴估值指标（含 P20/P50/P80 机会/中位/危险参考线与可选分位带底色），右轴指数点位。
 */
export function buildValuationPriceOption(
  input: ValuationPriceChartInput,
): Record<string, unknown> {
  const { series, priceSeries, stats, metricLabel, unit, mode, sigma, showBandArea, theme } = input;
  const dates = series.map((point) => point.trade_date);
  const values = series.map((point) => Number(point.value.toFixed(4)));
  const prices = alignPriceToDates(dates, priceSeries);
  const band = (() => {
    if (mode === "pct") return [stats?.p20 ?? null, stats?.p50 ?? null, stats?.p80 ?? null];
    if (stats?.mean == null || stats.sd == null) return [null, null, null];
    return [stats.mean - sigma * stats.sd, stats.mean, stats.mean + sigma * stats.sd];
  })();
  const bandLabels = mode === "pct" ? ["机会 P20", "中位 P50", "危险 P80"] : ["-σ", "均值", "+σ"];
  const bandColors = [theme.up, theme.subtext, theme.down];
  const hasPrice = prices.some((price) => price != null);
  const bandArea =
    showBandArea && mode === "pct" && band[0] != null && band[2] != null
      ? [
          [
            {
              yAxis: band[0],
              itemStyle: { color: withAlpha(theme.up, 0.05) },
            },
            { yAxis: band[2], itemStyle: { color: withAlpha(theme.down, 0.04) } },
          ],
        ]
      : [];
  return {
    animation: false,
    // 2026-11-27 第二轮反馈：图例原先停在右上角，与右轴「指数点位」标题/刻度重叠；
    // 改到左上角（右轴留白仍充足），图例点击可显隐估值线/点位线（selectedMode multiple）。
    grid: { left: 8, right: 24, top: 40, bottom: 24, containLabel: true },
    legend: {
      top: 2,
      left: 8,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 3,
      selectedMode: "multiple",
      textStyle: { color: theme.subtext, fontSize: 10 },
      data: hasPrice ? [metricLabel, "指数点位"] : [metricLabel],
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 12 },
      formatter: (params: Array<{ dataIndex?: number }>) => {
        const index = params?.[0]?.dataIndex ?? 0;
        const date = dates[index] ?? "";
        const value = values[index];
        const price = prices[index];
        const lines = ["<b>" + date + "</b>"];
        if (Number.isFinite(value)) lines.push(metricLabel + " " + value.toFixed(2) + unit);
        if (price != null) lines.push("点位 " + price.toLocaleString("zh-CN", { maximumFractionDigits: 2 }));
        if (stats?.p20 != null && value != null) {
          const position = value <= stats.p20 ? "机会区" : stats.p80 != null && value >= stats.p80 ? "危险区" : "中位区";
          lines.push(position);
        }
        return lines.join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.axisLine } },
      axisTick: { show: false },
      axisLabel: {
        color: theme.subtext,
        fontSize: 10,
        hideOverlap: true,
        formatter: (value: string) => value.slice(0, 7),
      },
    },
    yAxis: [
      {
        type: "value",
        scale: true,
        name: metricLabel,
        nameTextStyle: { color: theme.subtext, fontSize: 10 },
        axisLabel: { color: theme.subtext, fontSize: 10 },
        splitLine: { lineStyle: { color: theme.splitLine } },
      },
      {
        type: "value",
        scale: true,
        name: "指数点位",
        nameTextStyle: { color: theme.subtext, fontSize: 10 },
        axisLabel: { color: theme.subtext, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: metricLabel,
        type: "line",
        yAxisIndex: 0,
        data: values,
        showSymbol: false,
        lineStyle: { width: 1.8, color: theme.palette[0] },
        areaStyle: { color: withAlpha(theme.palette[0], 0.07) },
        markArea:
          bandArea.length > 0
            ? { silent: true, data: bandArea }
            : undefined,
        markLine: {
          silent: true,
          symbol: "none",
          label: {
            position: "insideEndTop",
            color: theme.subtext,
            fontSize: 9,
            formatter: (params: { name?: string }) => params.name ?? "",
          },
          data: band.map((value, index) => ({
            name: bandLabels[index],
            yAxis: value,
            lineStyle: { color: bandColors[index], type: "dashed" as const, width: 1 },
          })),
        },
      },
      ...(hasPrice
        ? [
            {
              name: "指数点位",
              type: "line",
              yAxisIndex: 1,
              data: prices,
              showSymbol: false,
              lineStyle: { width: 1.2, color: theme.palette[2], opacity: 0.9 },
            },
          ]
        : []),
    ],
  };
}

/** 成分股权重气泡/饼图用到的字段（与 DetailConstituent 结构兼容）。 */
export interface ConstituentWeightItem {
  stock_code: string;
  name: string;
  weight: number | null;
}

export interface ConstituentPieSlice {
  name: string;
  code: string | null;
  /** 权重（百分数点，0~100）。 */
  value: number;
  /** true = 「其他（其余 N 只）」聚合片，不可下钻。 */
  rest: boolean;
}

/** 成分饼图默认只展开前 10 大权重股，其余聚合成「其他」。 */
export const CONSTITUENT_PIE_TOP = 10;

/**
 * 成分股权重饼图切片（纯计算，可单测）。
 *
 * - `hideNonTop10=true`（默认）：前 10 大 + 「其他（其余 N 只）」聚合片，
 *   其他片的权重 = 其余已披露成分权重之和（不按 100 − CR10 反推，避免把未披露权重算进来）；
 * - `hideNonTop10=false`：按权重降序展示全部已披露成分；
 * - 权重缺失/<=0 的成分剔除（不补 0、不造数）。
 */
export function constituentPieSlices(
  constituents: readonly ConstituentWeightItem[],
  hideNonTop10: boolean,
): ConstituentPieSlice[] {
  const valid = constituents
    .filter(
      (item): item is ConstituentWeightItem & { weight: number } =>
        item.weight != null && Number.isFinite(item.weight) && item.weight > 0,
    )
    .slice()
    .sort((a, b) => b.weight - a.weight);
  if (valid.length === 0) return [];
  const slices = 
    hideNonTop10 && valid.length > CONSTITUENT_PIE_TOP
      ? valid.slice(0, CONSTITUENT_PIE_TOP)
      : valid;
  const result: ConstituentPieSlice[] = slices.map((item) => ({
    name: item.name,
    code: item.stock_code,
    value: item.weight,
    rest: false,
  }));
  if (hideNonTop10 && valid.length > CONSTITUENT_PIE_TOP) {
    const restWeight = valid
      .slice(CONSTITUENT_PIE_TOP)
      .reduce((sum, item) => sum + item.weight, 0);
    if (restWeight > 0) {
      result.push({
        name: "其他（其余 " + (valid.length - CONSTITUENT_PIE_TOP) + " 只）",
        code: null,
        value: restWeight,
        rest: true,
      });
    }
  }
  return result;
}