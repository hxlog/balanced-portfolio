"use client";

/**
 * /valuation v2 图表与控制器。
 *
 * 视觉规范（2026-11 用户确认）：保留现网 sky 主色 / 绿涨红跌 / 语义 token，
 * 不重做视觉。本文件只做数据与交互增强：
 * - 红利指数吸引力：绝对模式（PB 对数轴 + ln 回归 + 中位十字线）/ 相对模式（四象限）；
 * - MVI：双仪表盘（估值分/风险分）+ 公式 tooltip + 近 5 年周频平滑 + 展开双轴图；
 * - 两张估值矩阵沿用原有散点 + 回归线。
 */
import { useMemo, useState, type ReactNode } from "react";
import { useTheme } from "next-themes";
import { LineChart as LineChartIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { EChart } from "@/components/EChart";
import { getChartTheme, withAlpha, type ChartTheme } from "@/lib/chart-theme";
import {
  DIVIDEND_QUADRANTS,
  buildMviTrendOption,
  dividendPoints,
  linearFit,
  logFit,
  medianOf,
  positiveLogRange,
  sampleLogLine,
  weeklyLast,
  zoneOfMvi,
} from "@/lib/valuation-chart-model";
import type { IndexQuoteRow, MviInfo, PercentileWindow, ValuationMetric } from "@/lib/valuation-types";
import { InfoTip } from "./valuation-ui";
import { MviOverlayModal } from "./mvi-overlay-modal";

export const V2_METRICS: ReadonlyArray<{ value: ValuationMetric; label: string }> = [
  { value: "pe_ttm", label: "PE" },
  { value: "pb", label: "PB" },
  { value: "dividend_yield_ttm", label: "股息率" },
  { value: "erp", label: "风险溢价" },
];

export const V2_WINDOWS: ReadonlyArray<{ value: PercentileWindow; label: string }> = [
  { value: "1y", label: "1 年" },
  { value: "3y", label: "3 年" },
  { value: "5y", label: "5 年" },
  { value: "10y", label: "10 年" },
  { value: "all", label: "全历史" },
];

export type DividendMode = "absolute" | "relative";

const CATEGORY_COLOR_INDEX: Record<string, number> = {
  宽基: 0,
  行业: 1,
  主题: 5,
  策略: 2,
  其他: 4,
};

function categoryColor(category: string, theme: ChartTheme): string {
  const index = CATEGORY_COLOR_INDEX[category];
  return index == null ? theme.subtext : theme.palette[index % theme.palette.length];
}

/** 线性回归：返回斜率、截距、R²、方程文本（估值矩阵沿用）。 */
export function linearRegression(points: Array<{ x: number; y: number }>): {
  slope: number;
  intercept: number;
  r2: number;
  equation: string;
} | null {
  const fit = linearFit(points);
  return fit ? { slope: fit.slope, intercept: fit.intercept, r2: fit.r2, equation: fit.equation } : null;
}

function scatterBaseOption(
  points: Array<{ name: string; code: string; x: number; y: number; size: number; category: string }>,
  xName: string,
  yName: string,
  theme: ChartTheme,
) {
  const maxSize = Math.max(1, ...points.map((p) => p.size));
  return {
    animation: false,
    grid: { left: 10, right: 18, top: 34, bottom: 36, containLabel: true },
    tooltip: {
      confine: true,
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (params: { data?: { raw?: (typeof points)[number] } }) => {
        const raw = params.data?.raw;
        if (!raw) return "";
        return (
          "<b>" + raw.name + "</b> " + raw.code +
          "<br/>" + xName + " " + raw.x.toFixed(2) +
          "<br/>" + yName + " " + raw.y.toFixed(2) +
          "<br/>基金规模 " + (raw.size / 1e8).toFixed(1) + " 亿"
        );
      },
    },
    xAxis: {
      type: "value",
      name: xName,
      nameLocation: "middle",
      nameGap: 24,
      nameTextStyle: { color: theme.subtext, fontSize: 10 },
      axisLabel: { color: theme.subtext, fontSize: 9, formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    yAxis: {
      type: "value",
      name: yName,
      nameLocation: "middle",
      nameGap: 38,
      nameTextStyle: { color: theme.subtext, fontSize: 10 },
      axisLabel: { color: theme.subtext, fontSize: 9, formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    series: [
      {
        type: "scatter",
        symbolSize: (value: number[]) => 6 + 16 * Math.sqrt(Math.min(1, (value[2] ?? 0) / maxSize)),
        data: points.map((p) => ({
          value: [p.x, p.y, p.size],
          raw: p,
          itemStyle: {
            color: categoryColor(p.category, theme),
            opacity: 0.62,
            borderColor: theme.tooltipBg,
            borderWidth: 1,
          },
        })),
      },
    ],
  };
}

type Regression = { slope: number; intercept: number; r2: number; equation: string };

/**
 * 把回归线 + 方程 + 单位标注塞进散点 option。
 *
 * `lineData` 必须由调用方按坐标轴口径生成：线性轴两端两点即可；log 轴必须用
 * `sampleLogLine` 在对数尺度采样，否则「数据空间两点直线」在 ECharts 对数轴上
 * 会被画成视觉曲线、并与坐标轴口径不一致。
 */
function attachRegression(
  option: Record<string, unknown>,
  reg: Regression | null,
  lineData: Array<[number, number]>,
  yUnit: string,
  theme: ChartTheme,
) {
  if (!reg || lineData.length < 2) return option;
  (option.series as unknown[]).push({
    type: "line",
    showSymbol: false,
    silent: true,
    data: lineData,
    lineStyle: { color: theme.down, width: 1.5, type: "dashed" },
    tooltip: { show: false },
    z: 3,
  });
  (option as Record<string, unknown>).title = {
    text: reg.equation + "   R² = " + reg.r2.toFixed(3),
    left: 10,
    top: 4,
    textStyle: { color: theme.subtext, fontSize: 11, fontWeight: 400 },
  };
  (option as Record<string, unknown>).graphic = {
    type: "text",
    right: 10,
    bottom: 4,
    style: { text: "y 单位：" + yUnit, fill: theme.subtext, fontSize: 10 },
  };
  return option;
}

/** 线性轴矩阵（PB 分位 × 股息率）：回归线取 x 两端点即可。 */
function withLinearRegression(
  option: Record<string, unknown>,
  points: Array<{ x: number; y: number }>,
  reg: Regression | null,
  yUnit: string,
  theme: ChartTheme,
) {
  if (!reg || points.length < 2) return attachRegression(option, reg, [], yUnit, theme);
  const xs = points.map((p) => p.x);
  const min = Math.min(...xs);
  const max = Math.max(...xs);
  return attachRegression(
    option,
    reg,
    [
      [min, reg.slope * min + reg.intercept],
      [max, reg.slope * max + reg.intercept],
    ],
    yUnit,
    theme,
  );
}

/** log 轴矩阵（ROE × PE）：与红利图一致，在对数尺度采样回归线。 */
function withLogRegression(
  option: Record<string, unknown>,
  points: Array<{ x: number; y: number }>,
  reg: Regression | null,
  yUnit: string,
  theme: ChartTheme,
) {
  const lineData = reg ? sampleLogLine(points.map((p) => ({ x: p.x })), reg) : [];
  return attachRegression(option, reg, lineData, yUnit, theme);
}

/** 红利指数吸引力：绝对估值（PB 对数轴）或相对估值（PB/股息率 5y 分位四象限）。 */
export function DividendValueChart({
  rows,
  mode,
}: {
  rows: IndexQuoteRow[];
  mode: DividendMode;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);
  const points = useMemo(() => dividendPoints(rows, mode), [rows, mode]);

  if (points.length === 0) {
    return (
      <EmptyChart
        text={
          mode === "relative"
            ? "暂无同时具备 PB/股息率 5 年分位与基金规模的红利指数"
            : "暂无同时具备股息率、PB 与基金规模的红利指数"
        }
      />
    );
  }

  const maxSize = Math.max(1, ...points.map((point) => point.size));
  const scatter = {
    type: "scatter",
    symbolSize: (value: number[]) => 6 + 16 * Math.sqrt(Math.min(1, (value[2] ?? 0) / maxSize)),
    data: points.map((point) => ({
      value: [point.x, point.y, point.size],
      raw: point,
      itemStyle: {
        color: categoryColor(point.category, theme),
        opacity: 0.62,
        borderColor: theme.tooltipBg,
        borderWidth: 1,
      },
    })),
  };

  if (mode === "relative") {
    const median = 50;
    const option: Record<string, unknown> = {
      animation: false,
      // 与绝对模式切换时 ECharts 默认 merge 会残留旧的回归方程标题，这里显式隐藏。
      title: { show: false },
      grid: { left: 10, right: 18, top: 34, bottom: 30, containLabel: true },
      tooltip: {
        confine: true,
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text, fontSize: 11 },
        formatter: (params: { data?: { raw?: (typeof points)[number] } }) => {
          const raw = params.data?.raw;
          if (!raw) return "";
          return (
            "<b>" + raw.name + "</b> " + raw.code +
            "<br/>PB 5y 分位 " + raw.x.toFixed(1) + "% · 股息率 5y 分位 " + raw.y.toFixed(1) + "%" +
            (raw.pb != null ? "<br/>当前 PB " + raw.pb.toFixed(2) + " · 股息率 " + (raw.dividend ?? 0).toFixed(2) + "%" : "") +
            "<br/>基金规模 " + (raw.size / 1e8).toFixed(1) + " 亿"
          );
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "PB 5y 分位（%，越低越便宜）",
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: theme.subtext, fontSize: 10 },
        axisLabel: { color: theme.subtext, fontSize: 9, formatter: "{value}%" },
        splitLine: { lineStyle: { color: theme.splitLine } },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "股息率 5y 分位（%）",
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { color: theme.subtext, fontSize: 10 },
        axisLabel: { color: theme.subtext, fontSize: 9, formatter: "{value}%" },
        splitLine: { lineStyle: { color: theme.splitLine } },
      },
      graphic: DIVIDEND_QUADRANTS.map((quadrant) => {
        const x = quadrant.xMin === 0 ? "10%" : "78%";
        const y = quadrant.yMax === 100 ? "14%" : "78%";
        const color =
          quadrant.tone === "success"
            ? theme.up
            : quadrant.tone === "destructive"
              ? theme.down
              : quadrant.tone === "warning"
                ? theme.palette[2]
                : theme.palette[0];
        return {
          type: "text",
          left: x,
          top: y,
          style: {
            text: quadrant.label + "\n" + quadrant.note,
            fill: withAlpha(color, 0.85),
            fontSize: 10,
            lineHeight: 14,
          },
        };
      }),
      series: [
        {
          ...scatter,
          markArea: {
            silent: true,
            data: DIVIDEND_QUADRANTS.map((quadrant) => {
              const color =
                quadrant.tone === "success"
                  ? theme.up
                  : quadrant.tone === "destructive"
                    ? theme.down
                    : theme.palette[2];
              return [
                {
                  xAxis: quadrant.xMin,
                  yAxis: quadrant.yMin,
                  itemStyle: { color: withAlpha(color, quadrant.tone === "primary" ? 0.03 : 0.05) },
                },
                { xAxis: quadrant.xMax, yAxis: quadrant.yMax },
              ];
            }),
          },
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { color: theme.axisLine, type: "dashed", width: 1 },
            data: [{ xAxis: median }, { yAxis: median }],
          },
        },
      ],
    };
    return <EChart option={option} style={{ height: 320, width: "100%" }} />;
  }

  // 绝对估值：PB 用对数轴；回归线按 ln(PB) 拟合后在 log 轴上采样，避免视觉斜率失真。
  const [xMin, xMax] = positiveLogRange(points.map((point) => point.x));
  const reg = logFit(points.map((point) => ({ x: point.x, y: point.y })), {
    xName: "PB",
    yName: "股息率",
  });
  const medianPb = medianOf(points.map((point) => point.x));
  const medianYield = medianOf(points.map((point) => point.y));
  const option: Record<string, unknown> = {
    animation: false,
    grid: { left: 10, right: 18, top: 34, bottom: 30, containLabel: true },
    tooltip: {
      confine: true,
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (params: { data?: { raw?: (typeof points)[number] } }) => {
        const raw = params.data?.raw;
        if (!raw) return "";
        return (
          "<b>" + raw.name + "</b> " + raw.code +
          "<br/>PB " + raw.x.toFixed(2) + " 倍 · 股息率 " + raw.y.toFixed(2) + "%" +
          "<br/>基金规模 " + (raw.size / 1e8).toFixed(1) + " 亿"
        );
      },
    },
    xAxis: {
      type: "log",
      name: "PB（倍，对数轴）",
      nameLocation: "middle",
      nameGap: 24,
      min: xMin,
      max: xMax,
      nameTextStyle: { color: theme.subtext, fontSize: 10 },
      axisLabel: { color: theme.subtext, fontSize: 9, formatter: (value: number) => value.toFixed(2) },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    yAxis: {
      type: "value",
      name: "股息率（%）",
      nameLocation: "middle",
      nameGap: 30,
      scale: true,
      nameTextStyle: { color: theme.subtext, fontSize: 10 },
      axisLabel: { color: theme.subtext, fontSize: 9, formatter: (value: number) => value.toFixed(1) },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    series: [
      {
        ...scatter,
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: theme.axisLine, type: "dashed", width: 1 },
          data: [
            ...(medianPb != null ? [{ xAxis: medianPb }] : []),
            ...(medianYield != null ? [{ yAxis: medianYield }] : []),
          ],
        },
      },
    ],
    title: {
      show: true,
      text: reg
        ? reg.equation + "   R² = " + reg.r2.toFixed(3)
        : "",
      left: 10,
      top: 4,
      textStyle: { color: theme.subtext, fontSize: 11, fontWeight: 400 },
    },
    // graphic 数组长度固定 4：相对模式有 4 个象限标注，ECharts merge 不会移除多余项，
    // 这里补两个空占位，保证两模式来回切换不残留上一次的文字标注。
    graphic: [
      {
        type: "text",
        left: 14,
        top: 30,
        style: { text: "左上：低 PB + 高股息（最有吸引力）", fill: theme.up, fontSize: 10 },
      },
      {
        type: "text",
        right: 10,
        bottom: 4,
        style: { text: "虚线：PB / 股息率中位数 · 回归按 ln(PB) 拟合", fill: theme.subtext, fontSize: 9 },
      },
      { type: "text", style: { text: "" } },
      { type: "text", style: { text: "" } },
    ],
  };
  if (reg) {
    (option.series as unknown[]).push({
      type: "line",
      showSymbol: false,
      silent: true,
      data: sampleLogLine(points.map((point) => ({ x: point.x })), reg),
      lineStyle: { color: theme.down, width: 1.5, type: "dashed" },
      tooltip: { show: false },
      z: 3,
    });
  }
  return <EChart option={option} style={{ height: 320, width: "100%" }} />;
}

function EmptyChart({ text }: { text: string }) {
  return (
    <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
      {text}
    </div>
  );
}

/** 估值矩阵 1：PB 分位 × 股息率（回归 + 中位数参考线）。 */
export function PbDividendMatrix({ rows }: { rows: IndexQuoteRow[] }) {
  const { resolvedTheme } = useTheme();
  const theme = getChartTheme(resolvedTheme === "dark");
  const points = useMemo(
    () =>
      rows
        .filter((row) => row.pb_percentile != null && row.dividend_yield_pct != null)
        .map((row) => ({
          name: row.name,
          code: row.index_code,
          x: row.pb_percentile as number,
          y: row.dividend_yield_pct as number,
          size: row.fund_aum ?? 0,
          category: row.category,
        })),
    [rows],
  );
  const reg = useMemo(
    () => linearRegression(points.map((p) => ({ x: p.x, y: p.y }))),
    [points],
  );
  if (points.length < 3) return <EmptyChart text="PB 分位或股息率数据不足，暂无法绘制矩阵" />;
  const option = scatterBaseOption(points, "PB 分位（%）", "股息率（%）", theme);
  withLinearRegression(option, points.map((p) => ({ x: p.x, y: p.y })), reg, "%", theme);
  return <EChart option={option} style={{ height: 300, width: "100%" }} />;
}

/** 估值矩阵 2：ROE × PE，支持 log 轴（PE 右偏）。 */
export function RoePeMatrix({ rows }: { rows: IndexQuoteRow[] }) {
  const { resolvedTheme } = useTheme();
  const theme = getChartTheme(resolvedTheme === "dark");
  const points = useMemo(
    () =>
      rows
        .filter((row) => row.roe_ttm != null && row.pe_ttm != null && row.pe_ttm > 0)
        .map((row) => ({
          name: row.name,
          code: row.index_code,
          x: row.pe_ttm as number,
          y: row.roe_ttm as number,
          size: row.fund_aum ?? 0,
          category: row.category,
        })),
    [rows],
  );
  // PE 用 log 轴 → 回归按 y = a·ln(PE) + b 拟合，并在对数尺度采样画线（与红利图同口径）。
  const reg = useMemo(
    () =>
      logFit(points.map((p) => ({ x: p.x, y: p.y })), {
        xName: "PE",
        yName: "ROE",
      }),
    [points],
  );
  if (points.length < 3) return <EmptyChart text="ROE 或 PE 数据不足，暂无法绘制矩阵" />;
  const option = scatterBaseOption(points, "PE（倍，log 轴）", "ROE（%）", theme);
  (option.xAxis as Record<string, unknown>).type = "log";
  (option.xAxis as Record<string, unknown>).min = "dataMin";
  withLogRegression(option, points.map((p) => ({ x: p.x, y: p.y })), reg, "%", theme);
  return <EChart option={option} style={{ height: 300, width: "100%" }} />;
}

/** 半环仪表盘（纯 SVG，双指数：估值分 / 风险分）。 */
export function ScoreGauge({
  score,
  title,
  subtitle,
  leftLabel = "0",
  rightLabel = "100",
  palette,
}: {
  score: number;
  title?: ReactNode;
  subtitle?: string;
  leftLabel?: string;
  rightLabel?: string;
  palette: string[];
}) {
  const size = 190;
  const cx = size / 2;
  const cy = size / 2 + 14;
  const radius = size / 2 - 16;
  const zones = [
    { from: 0, to: 20, color: palette[0] },
    { from: 20, to: 40, color: palette[1] },
    { from: 40, to: 60, color: palette[2] },
    { from: 60, to: 80, color: palette[3] },
    { from: 80, to: 100, color: palette[4] },
  ];
  const angleOf = (value: number) => Math.PI - (value / 100) * Math.PI;
  const point = (angle: number, dist: number) => [cx + dist * Math.cos(angle), cy - dist * Math.sin(angle)];
  const arcs = zones.map((zone) => {
    const [x0, y0] = point(angleOf(zone.from), radius);
    const [x1, y1] = point(angleOf(zone.to), radius);
    return <path key={zone.from} d={"M " + x0 + " " + y0 + " A " + radius + " " + radius + " 0 0 1 " + x1 + " " + y1} stroke={zone.color} strokeWidth={14} fill="none" />;
  });
  const clamped = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  const [nx, ny] = point(angleOf(clamped), radius - 6);
  return (
    <div className="flex flex-col items-center">
      <svg viewBox={"0 0 " + size + " " + (size - 8)} className="w-full max-w-[200px]" role="img" aria-label={(typeof title === "string" ? title : "评分") + " " + Math.round(clamped)}>
        {arcs}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={4.5} fill="currentColor" />
        <text x={cx} y={cy - 30} textAnchor="middle" fontSize={26} fontWeight={700} fill="currentColor">
          {Math.round(clamped)}
        </text>
        <text x={cx - radius - 4} y={cy + 20} textAnchor="middle" fontSize={9} fill="#94a3b8">
          {leftLabel}
        </text>
        <text x={cx + radius + 4} y={cy + 20} textAnchor="middle" fontSize={9} fill="#94a3b8">
          {rightLabel}
        </text>
      </svg>
      <div className="flex items-center justify-center gap-1 text-xs font-medium">{title}</div>
      {subtitle ? <div className="text-[10px] text-muted-foreground">{subtitle}</div> : null}
    </div>
  );
}

const RISK_PALETTE = ["#16a34a", "#65a30d", "#eab308", "#f97316", "#dc2626"];
const CHEAP_PALETTE = [...RISK_PALETTE].reverse();

function zoneToneClass(zone: string): string {
  if (zone.includes("低估")) return "border-success/30 bg-success/10 text-success";
  if (zone.includes("高估")) return "border-destructive/30 bg-destructive/10 text-destructive";
  return "border-border bg-muted text-muted-foreground";
}

/** 市场估值指数面板（双仪表盘 + 因子贡献 + 近 5 年周频走势 + 打开双轴图）。 */
export function MviPanel({ mvi }: { mvi: MviInfo | null }) {
  const { resolvedTheme } = useTheme();
  const theme = getChartTheme(resolvedTheme === "dark");
  const [overlayOpen, setOverlayOpen] = useState(false);

  const latest = mvi?.latest ?? null;
  if (!latest) {
    return <EmptyChart text="MVI 数据准备中（每日 23:50 更新）" />;
  }

  const trendPoints = mvi?.history ?? [];
  const weekly = weeklyLast(trendPoints);
  const trendOption = buildMviTrendOption(trendPoints, theme);
  const zone = latest.zone || zoneOfMvi(latest.mvi);
  const cheapScore = latest.cheap_score ?? Math.max(0, Math.min(100, 100 - latest.mvi));
  const riskScore = latest.risk_score;
  const factors = latest.factors ?? {};
  const weights = latest.weights ?? {};
  const factorLabels = Object.keys(factors);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="text-[10px] text-muted-foreground">当前 MVI</div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight tabular-nums">{latest.mvi.toFixed(2)}</span>
            <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", zoneToneClass(zone))}>
              {zone}
            </span>
          </div>
          <div className="mt-0.5 text-[10px] tabular-nums text-muted-foreground">数据截至 {latest.as_of}</div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1 text-[11px]"
          onClick={() => setOverlayOpen(true)}
        >
          <LineChartIcon className="size-3.5" />
          打开图表
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-1">
        <div className="space-y-1">
          <div className="flex items-center justify-center gap-1 text-xs font-medium">
            估值分
            <InfoTip label="估值分">
              <p className="font-medium">估值分（越高越便宜）</p>
              <p className="mt-1">
                100 − MVI。由 PE/PB（反向）、股息率、风险溢价、ROE 五个因子的 104 周滚动分位加权：
              </p>
              <p className="mt-1 tabular-nums">
                PE 16.86% · PB 19.27% · 股息率 28.53% · 风险溢价 23.47% · ROE 11.88%
              </p>
              <p className="mt-1">5 大宽基等权合成；v1 固定权重（in-sample），仅作研究参考。</p>
            </InfoTip>
          </div>
          <ScoreGauge
            score={cheapScore}
            title={<span className="sr-only">估值分 {Math.round(cheapScore)}</span>}
            leftLabel="贵"
            rightLabel="便宜"
            palette={CHEAP_PALETTE}
          />
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-center gap-1 text-xs font-medium">
            风险分
            <InfoTip label="风险分">
              <p className="font-medium">风险分（越高越危险）</p>
              <p className="mt-1">
                60 日年化波动率分位 × 55% + 近 1 年最大回撤分位 × 45%（沪深300，1260 日滚动分位）。
              </p>
              <p className="mt-1">0 = 安全，100 = 危险；与估值分共振时安全边际更高。</p>
            </InfoTip>
          </div>
          <ScoreGauge
            score={riskScore ?? 0}
            title={<span className="sr-only">风险分 {riskScore == null ? "暂无" : Math.round(riskScore)}</span>}
            leftLabel="安全"
            rightLabel="危险"
            palette={RISK_PALETTE}
          />
        </div>
      </div>

      {factorLabels.length > 0 ? (
        <div className="space-y-1.5">
          {factorLabels.slice(0, 5).map((label) => {
            const value = factors[label] ?? 0;
            const weight = (weights[label] ?? 0) * 100;
            return (
              <div key={label}>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="truncate">{label}</span>
                  <span className="ml-2 shrink-0 tabular-nums text-muted-foreground">
                    {value.toFixed(1)}% · 权重 {weight.toFixed(1)}%
                  </span>
                </div>
                <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary"
                    style={{ width: Math.max(2, Math.min(100, value)) + "%" }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      <div>
        <div className="mb-1 flex items-center justify-between text-[10px] text-muted-foreground">
          <span>近 5 年周频走势</span>
          <span className="tabular-nums">{weekly.length} 周</span>
        </div>
        <EChart option={trendOption} style={{ height: 84, width: "100%" }} />
      </div>

      <p className="text-[10px] leading-relaxed text-muted-foreground/80">
        周频（ISO 周去重、去周末点）· 104 周滚动分位 · v1 固定权重（in-sample）· 每日 23:50 更新。
      </p>

      <MviOverlayModal open={overlayOpen} onOpenChange={setOverlayOpen} mvi={mvi} />
    </div>
  );
}

/** 图表卡：标题 + 一行说明 + 图表本体（可选标题旁说明 / 右上角操作）。 */
export function ChartCard({
  title,
  desc,
  titleExtra,
  aside,
  children,
  className,
}: {
  title: string;
  desc?: string;
  titleExtra?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-border bg-card p-4", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1 text-sm font-medium">
            {title}
            {titleExtra}
          </h3>
          {desc ? <p className="mt-0.5 text-[11px] text-muted-foreground">{desc}</p> : null}
        </div>
        {aside}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}
