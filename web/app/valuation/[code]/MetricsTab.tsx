"use client";

import { useMemo } from "react";
import { useTheme } from "next-themes";
import { EChart } from "@/components/EChart";
import { withAlpha, getChartTheme } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";
import { findPercentile } from "@/lib/valuation-detail-api-map";
import {
  EMPTY_DISPLAY,
  formatAumYi,
  formatNumber,
  formatPercentileValue,
  formatPlainPct,
} from "@/lib/valuation-detail-format";
import type {
  PercentileSummary,
  ValuationDetailData,
  ValuationHistoryData,
  ValuationHistoryPoint,
} from "@/lib/valuation-detail-types";
import {
  ChartCard,
  isUsablePercentile,
  LevelBadge,
  percentileLabel,
  percentileTone,
  PercentileBar,
  sumAum,
} from "../_components/valuation-ui";

const CHART_HEIGHT = 260;

interface ReferenceLine {
  name: string;
  value: number;
}

function buildPeChartOption(
  series: readonly ValuationHistoryPoint[],
  stats: PercentileSummary | null,
  theme: ReturnType<typeof getChartTheme>,
  isDark: boolean,
): Record<string, unknown> {
  const references: ReferenceLine[] = [
    { name: "P20", value: stats?.p20 ?? Number.NaN },
    { name: "P50", value: stats?.p50 ?? Number.NaN },
    { name: "P80", value: stats?.p80 ?? Number.NaN },
  ].filter(
    (item): item is ReferenceLine =>
      Number.isFinite(item.value),
  );

  const last = series.length > 0 ? series[series.length - 1] : null;

  return {
    animation: false,
    grid: { left: 4, right: 12, top: 24, bottom: 2, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 12 },
      valueFormatter: (value: unknown) =>
        typeof value === "number" && Number.isFinite(value)
          ? value.toFixed(2)
          : EMPTY_DISPLAY,
    },
    xAxis: {
      type: "category",
      data: series.map((point) => point.trade_date),
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
    yAxis: {
      type: "value",
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.subtext, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    series: [
      {
        name: "PE (TTM)",
        type: "line",
        data: series.map((point) => point.value),
        showSymbol: false,
        lineStyle: { width: 2, color: theme.palette[0] },
        itemStyle: { color: theme.palette[0] },
        areaStyle: {
          color: withAlpha(theme.palette[0], isDark ? 0.14 : 0.07),
        },
        emphasis: { focus: "series" },
        markLine: {
          silent: true,
          symbol: "none",
          label: {
            position: "insideEndTop",
            color: theme.subtext,
            fontSize: 9,
            formatter: (params: { name?: string; value?: unknown }) =>
              params.name && typeof params.value === "number"
                ? `${params.name} ${params.value.toFixed(2)}`
                : "",
          },
          lineStyle: {
            type: "dashed",
            width: 1,
            color: withAlpha(theme.subtext, 0.55),
          },
          data: references.map((item) => ({
            name: item.name,
            yAxis: item.value,
          })),
        },
        markPoint: last
          ? {
              symbol: "circle",
              symbolSize: 9,
              itemStyle: {
                color: theme.palette[0],
                borderColor: theme.tooltipBg,
                borderWidth: 2,
              },
              label: {
                show: true,
                position: "top",
                distance: 6,
                formatter: `PE ${last.value.toFixed(2)}`,
                color: theme.text,
                fontSize: 10,
                backgroundColor: theme.tooltipBg,
                borderColor: theme.tooltipBorder,
                borderWidth: 1,
                borderRadius: 4,
                padding: [3, 6],
              },
              data: [{ coord: [last.trade_date, last.value] }],
            }
          : undefined,
      },
    ],
  };
}

function StatItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate font-mono text-xs tabular-nums">{value}</dd>
    </div>
  );
}

export function MetricsTab({
  detail,
  history,
}: {
  detail: ValuationDetailData;
  history: ValuationHistoryData | null;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);
  const series = history?.series ?? [];
  const stats =
    history?.stats ?? findPercentile(detail.percentiles, "pe_ttm");
  const usable = isUsablePercentile(stats);
  const pct = usable ? stats.pct : null;
  const last = series.length > 0 ? series[series.length - 1] : null;
  const trackerAum = sumAum(detail.tracker_funds);

  const chartOption = useMemo(
    () => buildPeChartOption(series, stats, theme, isDark),
    [series, stats, theme, isDark],
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)]">
        <ChartCard
          title="PE (TTM) · 近 5 年"
          hint="虚线为 P20 / P50 / P80 参考位"
          aside={
            <span className="shrink-0 text-lg font-semibold tabular-nums">
              {formatNumber(last?.value)}
            </span>
          }
          bodyClassName="px-1 pb-1"
        >
          {series.length > 0 ? (
            <EChart
              option={chartOption}
              style={{ height: CHART_HEIGHT, width: "100%" }}
            />
          ) : (
            <div
              className="flex items-center justify-center text-xs text-muted-foreground"
              style={{ height: CHART_HEIGHT }}
            >
              暂无 PE 历史序列
            </div>
          )}
        </ChartCard>

        <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">PE 5 年分位</div>
              <div
                className={cn(
                  "mt-1.5 text-3xl font-semibold leading-none tracking-tight tabular-nums",
                  percentileTone(pct),
                )}
              >
                {pct == null ? EMPTY_DISPLAY : formatPercentileValue(pct, 1)}
              </div>
            </div>
            <LevelBadge level={percentileLabel(pct)} />
          </div>

          <PercentileBar
            value={pct}
            label="PE 分位"
            showLabels
            barClassName="h-2.5"
            className="mt-5"
          />

          <dl className="mt-5 grid grid-cols-3 gap-x-3 gap-y-4 border-t border-border pt-4">
            <StatItem label="均值" value={formatNumber(stats?.mean)} />
            <StatItem label="标准差" value={formatNumber(stats?.sd)} />
            <StatItem
              label="样本"
              value={formatNumber(stats?.sample_size, 0)}
            />
            <StatItem label="P20" value={formatNumber(stats?.p20)} />
            <StatItem label="P50" value={formatNumber(stats?.p50)} />
            <StatItem label="P80" value={formatNumber(stats?.p80)} />
            <StatItem label="最低" value={formatNumber(stats?.min)} />
            <StatItem label="最高" value={formatNumber(stats?.max)} />
          </dl>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border bg-card px-4 py-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatItem
          label="发布机构"
          value={detail.publisher ?? EMPTY_DISPLAY}
        />
        <StatItem label="市场" value={detail.market ?? EMPTY_DISPLAY} />
        <StatItem label="基日" value={detail.base_date ?? EMPTY_DISPLAY} />
        <StatItem label="基点" value={formatNumber(detail.base_point)} />
        <StatItem
          label="成分列表"
          value={`${formatNumber(detail.constituents.length, 0)} 只`}
        />
        <StatItem
          label="跟踪规模"
          value={
            trackerAum == null
              ? EMPTY_DISPLAY
              : `${formatAumYi(trackerAum)} 亿元`
          }
        />
      </dl>

      <p className="sr-only">
        PE 当前值 {formatNumber(detail.pe_ttm)}，5 年分位{" "}
        {pct == null ? "样本不足" : formatPercentileValue(pct, 1)}；PB{" "}
        {formatNumber(detail.pb)}，股息率{" "}
        {formatPlainPct(detail.dividend_yield_ttm)}。
      </p>
    </div>
  );
}
