"use client";

import { useMemo } from "react";
import { useTheme } from "next-themes";
import { EChart } from "@/components/EChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getChartTheme, withAlpha, type ChartTheme } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";
import { findPercentile } from "@/lib/valuation-detail-api-map";
import {
  EMPTY_DISPLAY,
  formatNumber,
  formatPercentileValue,
  formatPlainPct,
  formatSignedPct,
  hasUsablePercentile,
  percentileLabel,
  percentileTone,
  percentileUnavailableText,
} from "@/lib/valuation-detail-format";
import type {
  PercentileSummary,
  ValuationDetailData,
  ValuationHistoryData,
  ValuationHistoryPoint,
} from "@/lib/valuation-detail-types";

/** 单序列 PE 折线：只画 PE，点位右轴待后端提供后再叠加。 */
function buildPeChartOption(
  series: readonly ValuationHistoryPoint[],
  theme: ChartTheme,
  isDark: boolean,
): Record<string, unknown> {
  return {
    animation: false,
    grid: { left: 56, right: 20, top: 30, bottom: 38 },
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
        hideOverlap: true,
        formatter: (value: string) => value.slice(0, 7),
      },
    },
    yAxis: {
      type: "value",
      scale: true,
      name: "PE (TTM)",
      nameGap: 16,
      nameTextStyle: { color: theme.subtext, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.subtext },
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
          color: withAlpha(theme.palette[0], isDark ? 0.16 : 0.1),
        },
        emphasis: { focus: "series" },
      },
    ],
  };
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

function PePercentileCard({ stats }: { stats: PercentileSummary | null }) {
  const usable = hasUsablePercentile(stats);
  const pct = usable ? stats.pct : null;
  const tone = percentileTone(pct);
  const label = percentileLabel(pct);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">PE 分位</CardTitle>
        <p className="text-xs text-muted-foreground">
          近 5 年历史分位 · 样本需 ≥120 个交易日
        </p>
      </CardHeader>
      <CardContent className="pt-2">
        {usable ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span
                className={cn(
                  "text-3xl font-semibold tabular-nums tracking-tight",
                  tone,
                )}
              >
                {formatPercentileValue(stats.pct)}
              </span>
              {label && (
                <span className={cn("text-xs font-medium", tone)}>{label}</span>
              )}
            </div>

            <div
              className="relative mt-4 h-3 w-full overflow-hidden rounded-full bg-muted"
              aria-hidden="true"
            >
              <div className="absolute inset-y-0 left-0 w-[30%] bg-success/25" />
              <div className="absolute inset-y-0 left-[30%] w-[40%] bg-warning/25" />
              <div className="absolute inset-y-0 left-[70%] right-0 bg-destructive/25" />
              <div
                className="absolute top-1/2 h-5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground ring-2 ring-background"
                style={{ left: `${clampPercent(stats.pct)}%` }}
              />
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] tabular-nums text-muted-foreground">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>

            <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-border/60 pt-3 text-xs">
              <div>
                <dt className="text-muted-foreground">均值</dt>
                <dd className="mt-0.5 font-mono tabular-nums">
                  {formatNumber(stats.mean)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">中位数</dt>
                <dd className="mt-0.5 font-mono tabular-nums">
                  {formatNumber(stats.p50)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">样本</dt>
                <dd className="mt-0.5 font-mono tabular-nums">
                  {formatNumber(stats.sample_size, 0)}
                </dd>
              </div>
            </dl>
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-5">
            <p className="text-sm font-medium">样本不足</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {stats
                ? `当前有效样本 ${formatNumber(stats.sample_size, 0)} 个，分位需 ≥120 个交易日。`
                : "暂无 PE 分位统计。"}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface CoreMetricRow {
  key: string;
  label: string;
  display: string;
  stats: PercentileSummary | null;
  usable: boolean;
  meanDisplay: string;
  meanTitle: string;
}

function CoreMetricsCard({ detail }: { detail: ValuationDetailData }) {
  const rows: CoreMetricRow[] = [
    {
      key: "pb",
      label: "PB",
      display: formatNumber(detail.pb),
      stats: findPercentile(detail.percentiles, "pb"),
      usable: false,
      meanDisplay: EMPTY_DISPLAY,
      meanTitle: "近 5 年均值",
    },
    {
      key: "dividend",
      label: "股息率 TTM",
      display: formatPlainPct(detail.dividend_yield_ttm),
      stats: findPercentile(detail.percentiles, "dividend_yield_ttm"),
      usable: false,
      meanDisplay: EMPTY_DISPLAY,
      meanTitle: "近 5 年均值（百分数点）",
    },
    {
      key: "erp",
      label: "风险溢价",
      display: formatSignedPct(detail.erp),
      stats: findPercentile(detail.percentiles, "erp"),
      usable: false,
      meanDisplay: EMPTY_DISPLAY,
      meanTitle: "近 5 年均值（百分数点）",
    },
  ];

  if (detail.roe_ttm != null) {
    rows.push({
      key: "roe",
      label: "ROE TTM",
      display: formatPlainPct(detail.roe_ttm),
      stats: null,
      usable: false,
      meanDisplay: EMPTY_DISPLAY,
      meanTitle: "后端暂未提供 ROE 分位",
    });
  }

  for (const row of rows) {
    row.usable = hasUsablePercentile(row.stats);
    if (row.key === "pb") {
      row.meanDisplay = formatNumber(row.stats?.mean);
    } else if (row.key === "erp") {
      row.meanDisplay = formatSignedPct(row.stats?.mean);
    } else if (row.stats) {
      row.meanDisplay = formatPlainPct(row.stats.mean);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">核心指标</CardTitle>
        <p className="text-xs text-muted-foreground">
          分位窗口为近 5 年；缺失或样本不足显示「—」/「样本不足」
        </p>
      </CardHeader>
      <CardContent className="overflow-x-auto pt-2">
        <table className="w-full min-w-[340px] border-collapse text-sm">
          <caption className="sr-only">
            指数核心估值指标：PB、股息率、风险溢价与 ROE
          </caption>
          <thead>
            <tr className="border-b border-border/60 text-[11px] text-muted-foreground">
              <th scope="col" className="pb-2 pr-2 text-left font-medium">
                指标
              </th>
              <th scope="col" className="px-2 pb-2 text-right font-medium">
                当前
              </th>
              <th scope="col" className="px-2 pb-2 text-right font-medium">
                5 年分位
              </th>
              <th scope="col" className="pb-2 pl-2 text-right font-medium">
                均值
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                className="border-b border-border/40 last:border-0"
              >
                <th
                  scope="row"
                  className="py-2.5 pr-2 text-left font-normal text-muted-foreground"
                >
                  {row.label}
                </th>
                <td className="px-2 py-2.5 text-right font-mono tabular-nums">
                  {row.display}
                </td>
                <td
                  className={cn(
                    "px-2 py-2.5 text-right font-mono text-xs tabular-nums",
                    row.usable
                      ? percentileTone(row.stats?.pct)
                      : "text-muted-foreground",
                  )}
                  title={
                    row.usable
                      ? "近 5 年历史分位"
                      : percentileUnavailableText(row.stats)
                  }
                >
                  {row.usable
                    ? formatPercentileValue(row.stats?.pct, 1)
                    : row.stats
                      ? "样本不足"
                      : EMPTY_DISPLAY}
                </td>
                <td
                  className="py-2.5 pl-2 text-right font-mono text-xs tabular-nums text-muted-foreground"
                  title={row.meanTitle}
                >
                  {row.meanDisplay}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
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
  const chartOption = useMemo(
    () => buildPeChartOption(series, theme, isDark),
    [history, theme, isDark],
  );
  const peStats =
    history?.stats ?? findPercentile(detail.percentiles, "pe_ttm");
  const lastDate =
    series.length > 0 ? series[series.length - 1].trade_date : detail.trade_date;

  return (
    <div className="grid grid-cols-1 gap-6 min-[1100px]:grid-cols-[minmax(0,1fr)_360px]">
      <Card className="min-w-0">
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <CardTitle className="text-base">估值与点位</CardTitle>
            <span className="text-xs tabular-nums text-muted-foreground">
              PE (TTM) · 近 5 年
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            当前展示 PE 序列，点位右轴待后端提供后叠加。
            {lastDate ? ` 数据截至 ${lastDate}。` : ""}
          </p>
        </CardHeader>
        <CardContent className="pt-2">
          {series.length > 0 ? (
            <EChart
              option={chartOption}
              style={{ height: 380, width: "100%" }}
            />
          ) : (
            <div className="flex h-[380px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-6 text-center text-sm text-muted-foreground">
              暂无 PE 历史序列
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-6">
        <PePercentileCard stats={peStats} />
        <CoreMetricsCard detail={detail} />
      </div>
    </div>
  );
}
