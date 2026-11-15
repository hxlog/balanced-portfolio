"use client";

/**
 * /valuation 重构版图表组件（Demo A 风格）。
 *
 * 设计原则：
 * - 所有图上都带「数据截止日 / 口径」注释，避免误读；
 * - Band 图支持「分位带（P20/P50/P80）」与「标准差带（均值 ±kσ）」两种模式，
 *   两条虚线会随模式与 k 值实时变化；
 * - 行业热力块用分位颜色（绿→黄→红）直接编码估值高低，点击可下钻筛选。
 */
import type { CSSProperties } from "react";
import { EChart } from "@/components/EChart";
import { cn } from "@/lib/utils";
import type {
  BroadProxyCard,
  HistoryPoint,
  IndexQuoteRow,
  PercentileStats,
  ValuationMetric,
} from "@/lib/valuation-types";
import { PercentileBar, percentileTone } from "./valuation-ui";

export const METRIC_LABEL: Record<ValuationMetric, string> = {
  pe_ttm: "PE",
  pb: "PB",
  dividend_yield_ttm: "股息率",
  erp: "风险溢价",
};

export function formatValue(value: number | null, metric: ValuationMetric): string {
  if (value == null) return "—";
  if (metric === "dividend_yield_ttm" || metric === "erp") return value.toFixed(2) + "%";
  return value.toFixed(2);
}

/** 代表性宽基卡：最新值 + 真实历史分位 + 迷你分位条。 */
export function ProxyCard({ card }: { card: BroadProxyCard }) {
  const tone = percentileTone(card.pe_percentile);
  return (
    <div className="rounded-xl border border-border bg-card p-4 transition-colors hover:border-foreground/20">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">{card.name}</span>
        <span className="font-mono text-[11px] text-muted-foreground">{card.index_code}</span>
      </div>
      <div className="mt-1 flex items-end justify-between">
        <div>
          <div className="text-2xl font-semibold tracking-tight tabular-nums">
            {card.pe == null ? "—" : card.pe.toFixed(2)}
          </div>
          <div className="text-[11px] text-muted-foreground">PE(TTM)</div>
        </div>
        <div className="text-right">
          <div className={cn("text-sm font-medium tabular-nums", tone)}>
            {card.pe_percentile == null ? "—" : card.pe_percentile.toFixed(1) + "%"}
          </div>
          <div className="text-[11px] text-muted-foreground">PE 分位</div>
        </div>
      </div>
      <div className="mt-2">
        <PercentileBar value={card.pe_percentile} />
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>
          PB <b className="font-medium text-foreground tabular-nums">{card.pb == null ? "—" : card.pb.toFixed(2)}</b>
          <span className="ml-1">({card.pb_percentile == null ? "—" : card.pb_percentile.toFixed(0) + "%"})</span>
        </span>
        <span>
          股息 <b className="font-medium text-foreground tabular-nums">{card.dividend_yield_pct == null ? "—" : card.dividend_yield_pct.toFixed(2) + "%"}</b>
        </span>
      </div>
    </div>
  );
}

export type BandMode = "pct" | "sd";

/** PE/PB Band 图：历史序列 + 分位带或标准差带 + 当前点。 */
export function PeBandChart({
  series,
  stats,
  metric,
  mode,
  sigma,
  title,
  style,
}: {
  series: HistoryPoint[];
  stats: PercentileStats | null;
  metric: ValuationMetric;
  mode: BandMode;
  sigma: number;
  title: string;
  style?: CSSProperties;
}) {
  const dates = series.map((point) => point.trade_date.slice(0, 10));
  const values = series.map((point) => Number(point.value.toFixed(4)));
  const mean = stats?.mean ?? null;
  const sd = stats?.sd ?? null;
  const band = (() => {
    if (mode === "pct") {
      return [stats?.p20 ?? null, stats?.p50 ?? null, stats?.p80 ?? null];
    }
    if (mean == null || sd == null) return [null, null, null];
    return [mean - sigma * sd, mean, mean + sigma * sd];
  })();
  const labels =
    mode === "pct" ? ["P20", "P50", "P80"] : [`-${sigma}σ`, "均值", `+${sigma}σ`];
  const colors = ["#94a3b8", "#eab308", "#94a3b8"];
  const last = values.length ? values[values.length - 1] : null;
  const unit = metric === "dividend_yield_ttm" || metric === "erp" ? "%" : "x";

  const option = {
    animation: false,
    grid: { left: 8, right: 14, top: 18, bottom: 22, containLabel: true },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value: number | null) =>
        value == null ? "—" : Number(value).toFixed(2) + unit,
    },
    xAxis: {
      type: "category",
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#e5e7eb" } },
      axisLabel: { color: "#9ca3af", fontSize: 10, hideOverlap: true },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: "#f1f2f5" } },
      axisLabel: { color: "#9ca3af", fontSize: 10 },
    },
    series: [
      {
        name: METRIC_LABEL[metric],
        type: "line",
        data: values,
        showSymbol: false,
        lineStyle: { width: 2, color: "#4f46e5" },
        areaStyle: { color: "rgba(79,70,229,0.08)" },
        markLine: {
          silent: true,
          symbol: "none",
          label: {
            position: "insideEndTop",
            color: "#94a3b8",
            fontSize: 10,
            formatter: (params: { name?: string }) => params.name ?? "",
          },
          data: band.map((value, index) => ({
            name: labels[index],
            yAxis: value ?? null,
            lineStyle: {
              color: colors[index],
              type: "dashed" as const,
              width: 1,
            },
          })),
        },
        markPoint: {
          symbol: "circle",
          symbolSize: 7,
          label: { show: false },
          data: last == null ? [] : [{ coord: [dates.length - 1, last] }],
          itemStyle: { color: "#4f46e5" },
        },
      },
    ],
  };

  return (
    <div>
      <EChart option={option} style={style || { height: 240, width: "100%" }} />
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span>{title}</span>
        <span className="tabular-nums">
          当前 {last == null ? "—" : last.toFixed(2) + unit}
        </span>
        <span className="tabular-nums">
          分位 {stats?.pct == null ? "—" : stats.pct.toFixed(1) + "%"}
        </span>
        <span className="tabular-nums">
          样本 {stats?.sample_size ?? 0} 点
        </span>
      </div>
    </div>
  );
}

/** 行业估值热力块：颜色编码 PE 分位。 */
export function IndustryHeatmap({
  rows,
  onSelect,
}: {
  rows: IndexQuoteRow[];
  onSelect: (industry: string) => void;
}) {
  const groups = new Map<string, number[]>();
  for (const row of rows) {
    if (!row.industry) continue;
    if (row.pe_percentile == null) continue;
    const list = groups.get(row.industry) ?? [];
    list.push(row.pe_percentile);
    groups.set(row.industry, list);
  }
  const cells = [...groups.entries()]
    .map(([industry, values]) => ({
      industry,
      pe: values.reduce((sum, value) => sum + value, 0) / values.length,
      count: values.length,
    }))
    .sort((a, b) => b.pe - a.pe);

  if (cells.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        行业分类数据准备中，暂无可展示的行业分位。
      </div>
    );
  }

  const colorFor = (pct: number) => {
    if (pct >= 80) return "bg-destructive/15 text-destructive";
    if (pct >= 60) return "bg-warning/20 text-warning-foreground";
    if (pct >= 40) return "bg-muted text-foreground";
    if (pct >= 20) return "bg-success/15 text-success";
    return "bg-success/25 text-success";
  };

  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
      {cells.slice(0, 16).map((cell) => (
        <button
          key={cell.industry}
          type="button"
          onClick={() => onSelect(cell.industry)}
          className={cn(
            "rounded-lg border border-transparent px-2 py-2 text-left transition-transform hover:scale-[1.02]",
            colorFor(cell.pe),
          )}
        >
          <div className="truncate text-[10px] opacity-80">{cell.industry}</div>
          <div className="text-base font-semibold tabular-nums">{cell.pe.toFixed(0)}%</div>
        </button>
      ))}
    </div>
  );
}

/** 估值矩阵：PE 分位 × PB 分位散点（点越靠右上越贵）。 */
export function ValuationMatrix({ rows }: { rows: IndexQuoteRow[] }) {
  const points = rows
    .filter((row) => row.pe_percentile != null && row.pb_percentile != null)
    .map((row) => ({
      name: row.name,
      value: [
        Number(row.pe_percentile!.toFixed(1)),
        Number(row.pb_percentile!.toFixed(1)),
        row.pe_ttm ?? 0,
      ],
      category: row.category,
    }));
  const option = {
    animation: false,
    grid: { left: 8, right: 12, top: 28, bottom: 26, containLabel: true },
    tooltip: {
      formatter: (params: { data?: { name?: string; value?: number[] } }) => {
        const value = params.data?.value ?? [];
        return (
          (params.data?.name ?? "") +
          "<br/>PE 分位 " +
          value[0] +
          "% · PB 分位 " +
          value[1] +
          "% · PE " +
          Number(value[2] ?? 0).toFixed(2)
        );
      },
    },
    xAxis: {
      type: "value",
      min: 0,
      max: 100,
      name: "PE 分位",
      nameGap: 8,
      nameTextStyle: { color: "#9ca3af", fontSize: 10 },
      splitLine: { lineStyle: { color: "#f1f2f5" } },
      axisLabel: { color: "#9ca3af", fontSize: 10 },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      name: "PB 分位",
      nameGap: 16,
      nameTextStyle: { color: "#9ca3af", fontSize: 10 },
      splitLine: { lineStyle: { color: "#f1f2f5" } },
      axisLabel: { color: "#9ca3af", fontSize: 10 },
    },
    series: [
      {
        type: "scatter",
        symbolSize: 5,
        data: points,
        itemStyle: { color: "rgba(79,70,229,0.55)" },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: "#e5e7eb", type: "dashed" },
          data: [{ xAxis: 50 }, { yAxis: 50 }],
        },
      },
    ],
  };
  return <EChart option={option} style={{ height: 240, width: "100%" }} />;
}
