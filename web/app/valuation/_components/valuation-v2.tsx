"use client";

/**
 * /valuation v2 图表与控制器。
 *
 * 设计要点（2026-11-15 用户第 2 轮反馈）：
 * - 窗口/指标切换走 URL + 服务端 Suspense（见 page.tsx），本文件的 Toolbar 只负责
 *   router.replace + useTransition，不在 pending 期间展示旧数据；
 * - 首屏用「红利指数吸引力」气泡图（股息率 × PB，气泡=基金规模）；
 * - 估值矩阵拆成两张散点：PB 分位 × 股息率、ROE × PE（可切 log 轴），
 *   都带线性回归线 + 方程 + R² + 分位中位数参考线。
 */
import { useMemo, useTransition, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { EChart } from "@/components/EChart";
import type { IndexQuoteRow, PercentileWindow, ValuationMetric } from "@/lib/valuation-types";

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

/** URL 驱动的窗口/指标控制器；pending 期间只显示状态，不展示旧图表。 */
export function ValuationToolbar({
  window,
  metric,
}: {
  window: PercentileWindow;
  metric: ValuationMetric;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();

  const apply = (nextWindow: PercentileWindow, nextMetric: ValuationMetric) => {
    if (nextWindow === window && nextMetric === metric) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("window", nextWindow);
    params.set("metric", nextMetric);
    startTransition(() => {
      router.replace(pathname + "?" + params.toString(), { scroll: false });
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex overflow-hidden rounded-lg border border-border text-xs">
        {V2_METRICS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => apply(window, item.value)}
            className={cn(
              "px-3 py-1.5 transition-colors",
              metric === item.value
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="inline-flex overflow-hidden rounded-lg border border-border text-xs">
        {V2_WINDOWS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => apply(item.value, metric)}
            className={cn(
              "px-2.5 py-1.5 transition-colors",
              window === item.value
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
      <span className="text-[11px] text-muted-foreground">{pending ? "加载中…" : ""}</span>
    </div>
  );
}

const CATEGORY_COLORS: Record<string, string> = {
  宽基: "#4f46e5",
  行业: "#0ea5e9",
  主题: "#14b8a6",
  策略: "#f59e0b",
  其他: "#94a3b8",
};

export interface ScatterPoint {
  name: string;
  code: string;
  x: number;
  y: number;
  size: number;
  category: string;
}

/** 线性回归：返回斜率、截距、R²、方程文本。 */
export function linearRegression(points: Array<{ x: number; y: number }>): {
  slope: number;
  intercept: number;
  r2: number;
  equation: string;
} | null {
  const n = points.length;
  if (n < 3) return null;
  const sumX = points.reduce((s, p) => s + p.x, 0);
  const sumY = points.reduce((s, p) => s + p.y, 0);
  const sumXY = points.reduce((s, p) => s + p.x * p.y, 0);
  const sumXX = points.reduce((s, p) => s + p.x * p.x, 0);
  const sumYY = points.reduce((s, p) => s + p.y * p.y, 0);
  const denom = n * sumXX - sumX * sumX;
  if (Math.abs(denom) < 1e-12) return null;
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  const num = n * sumXY - sumX * sumY;
  const den = Math.sqrt(Math.max(1e-12, (n * sumXX - sumX * sumX) * (n * sumYY - sumY * sumY)));
  const r2 = (num / den) ** 2;
  const equation =
    "y = " + slope.toFixed(3) + "x " + (intercept >= 0 ? "+ " : "- ") + Math.abs(intercept).toFixed(3);
  return { slope, intercept, r2, equation };
}

function scatterBaseOption(points: ScatterPoint[], xName: string, yName: string) {
  const maxSize = Math.max(1, ...points.map((p) => p.size));
  return {
    animation: false,
    grid: { left: 10, right: 18, top: 34, bottom: 36, containLabel: true },
    tooltip: {
      confine: true,
      formatter: (params: { data?: { raw?: ScatterPoint } }) => {
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
      nameTextStyle: { color: "#6b7280", fontSize: 11 },
      axisLabel: { color: "#9ca3af", fontSize: 10, formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { color: "#f1f2f5" } },
    },
    yAxis: {
      type: "value",
      name: yName,
      nameLocation: "middle",
      nameGap: 38,
      nameTextStyle: { color: "#6b7280", fontSize: 11 },
      axisLabel: { color: "#9ca3af", fontSize: 10, formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { color: "#f1f2f5" } },
    },
    series: [
      {
        type: "scatter",
        symbolSize: (value: number[]) => 6 + 16 * Math.sqrt(Math.min(1, (value[2] ?? 0) / maxSize)),
        data: points.map((p) => ({
          value: [p.x, p.y, p.size],
          raw: p,
          itemStyle: {
            color: CATEGORY_COLORS[p.category] ?? "#94a3b8",
            opacity: 0.62,
            borderColor: "#ffffff",
            borderWidth: 1,
          },
        })),
      },
    ],
  };
}

function withRegression(
  option: Record<string, unknown>,
  points: Array<{ x: number; y: number }>,
  reg: { slope: number; intercept: number; r2: number; equation: string } | null,
  yUnit: string,
) {
  if (!reg) return option;
  const xs = points.map((p) => p.x);
  const min = Math.min(...xs);
  const max = Math.max(...xs);
  (option.series as unknown[]).push({
    type: "line",
    showSymbol: false,
    data: [
      [min, reg.slope * min + reg.intercept],
      [max, reg.slope * max + reg.intercept],
    ],
    lineStyle: { color: "#ef4444", width: 1.5, type: "dashed" },
    tooltip: { show: false },
    z: 3,
  });
  (option as Record<string, unknown>).title = {
    text: reg.equation + "   R² = " + reg.r2.toFixed(3),
    left: 10,
    top: 4,
    textStyle: { color: "#6b7280", fontSize: 11, fontWeight: 400 },
  };
  (option as Record<string, unknown>).graphic = {
    type: "text",
    right: 10,
    bottom: 4,
    style: { text: "y 单位：" + yUnit, fill: "#9ca3af", fontSize: 10 },
  };
  return option;
}

/** 红利指数吸引力：股息率 × PB，气泡=跟踪基金规模（仅含有基金的红利类指数）。 */
export function DividendValueChart({ rows }: { rows: IndexQuoteRow[] }) {
  const points = useMemo(() => {
    const list = rows.filter(
      (row) =>
        (row.name.includes("红利") || row.name.includes("股息")) &&
        row.dividend_yield_pct != null &&
        row.pb != null &&
        (row.fund_aum ?? 0) > 0,
    );
    return list
      .map((row) => ({
        name: row.name,
        code: row.index_code,
        x: row.pb as number,
        y: row.dividend_yield_pct as number,
        size: row.fund_aum ?? 0,
        category: row.category,
      }))
      .sort((a, b) => b.size - a.size);
  }, [rows]);

  const medianPb = useMemo(() => {
    const values = points.map((p) => p.x).sort((a, b) => a - b);
    return values.length ? values[Math.floor(values.length / 2)] : 0;
  }, [points]);
  const medianYield = useMemo(() => {
    const values = points.map((p) => p.y).sort((a, b) => a - b);
    return values.length ? values[Math.floor(values.length / 2)] : 0;
  }, [points]);

  if (points.length === 0) {
    return <EmptyChart text="暂无同时具备股息率、PB 与基金规模的红利指数" />;
  }

  const option = scatterBaseOption(points, "PB（倍）", "股息率（%）");
  (option as Record<string, unknown>).markLine = undefined;
  (option.series as Array<Record<string, unknown>>).push({
    type: "line",
    showSymbol: false,
    silent: true,
    data: [
      [medianPb, Math.min(...points.map((p) => p.y)) * 0.95],
      [medianPb, Math.max(...points.map((p) => p.y)) * 1.05],
    ],
    lineStyle: { color: "#94a3b8", type: "dashed", width: 1 },
    tooltip: { show: false },
  });
  (option.series as Array<Record<string, unknown>>).push({
    type: "line",
    showSymbol: false,
    silent: true,
    data: [
      [Math.min(...points.map((p) => p.x)) * 0.95, medianYield],
      [Math.max(...points.map((p) => p.x)) * 1.05, medianYield],
    ],
    lineStyle: { color: "#94a3b8", type: "dashed", width: 1 },
    tooltip: { show: false },
  });
  (option as Record<string, unknown>).graphic = [
    {
      type: "text",
      left: 14,
      top: 28,
      style: { text: "左上：低 PB + 高股息（最有吸引力）", fill: "#16a34a", fontSize: 11 },
    },
  ];
  return <EChart option={option} style={{ height: 300, width: "100%" }} />;
}

/** 估值矩阵 1：PB 分位 × 股息率（回归 + 中位数参考线）。 */
export function PbDividendMatrix({ rows }: { rows: IndexQuoteRow[] }) {
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
  const option = scatterBaseOption(points, "PB 分位（%）", "股息率（%）");
  withRegression(option, points.map((p) => ({ x: p.x, y: p.y })), reg, "%");
  return <EChart option={option} style={{ height: 300, width: "100%" }} />;
}

/** 估值矩阵 2：ROE × PE，支持 log 轴（PE 右偏）。 */
export function RoePeMatrix({ rows }: { rows: IndexQuoteRow[] }) {
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
  const reg = useMemo(
    () => linearRegression(points.map((p) => ({ x: p.x, y: p.y }))),
    [points],
  );
  if (points.length < 3) return <EmptyChart text="ROE 或 PE 数据不足，暂无法绘制矩阵" />;
  const option = scatterBaseOption(points, "PE（倍，log 轴）", "ROE（%）");
  (option.xAxis as Record<string, unknown>).type = "log";
  (option.xAxis as Record<string, unknown>).min = "dataMin";
  withRegression(option, points.map((p) => ({ x: p.x, y: p.y })), reg, "%");
  return <EChart option={option} style={{ height: 300, width: "100%" }} />;
}

function EmptyChart({ text }: { text: string }) {
  return (
    <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
      {text}
    </div>
  );
}

export function ChartCard({
  title,
  desc,
  children,
  className,
}: {
  title: string;
  desc?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-border bg-card p-4", className)}>
      <h3 className="text-sm font-medium">{title}</h3>
      {desc ? <p className="mt-0.5 text-[11px] text-muted-foreground">{desc}</p> : null}
      <div className="mt-2">{children}</div>
    </section>
  );
}
