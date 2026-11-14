"use client";

import { useMemo } from "react";
import { useTheme } from "next-themes";
import { EChart } from "@/components/EChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getChartTheme, type ChartTheme } from "@/lib/chart-theme";
import {
  EMPTY_DISPLAY,
  formatNumber,
  formatPlainPct,
} from "@/lib/valuation-detail-format";
import type {
  DetailConstituent,
  ValuationDetailData,
} from "@/lib/valuation-detail-types";

/** 前 8 大权重横向条形图（单系列；表格即其可访问数据视图）。 */
function buildWeightBarOption(
  top: readonly DetailConstituent[],
  theme: ChartTheme,
): Record<string, unknown> {
  return {
    animation: false,
    grid: { left: 8, right: 64, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 12 },
      valueFormatter: (value: unknown) =>
        typeof value === "number" && Number.isFinite(value)
          ? `${value.toFixed(2)}%`
          : EMPTY_DISPLAY,
    },
    xAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.subtext, formatter: "{value}%" },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: top.map((item) => item.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: theme.text,
        fontSize: 11,
        width: 96,
        overflow: "truncate",
      },
    },
    series: [
      {
        name: "权重",
        type: "bar",
        data: top.map((item) => item.weight),
        barWidth: 12,
        itemStyle: {
          color: theme.palette[0],
          borderRadius: [0, 4, 4, 0],
        },
        label: {
          show: true,
          position: "right",
          color: theme.subtext,
          fontSize: 11,
          formatter: (params: { value?: unknown }) =>
            typeof params.value === "number"
              ? `${params.value.toFixed(2)}%`
              : EMPTY_DISPLAY,
        },
      },
    ],
  };
}

function compareConstituents(
  a: DetailConstituent,
  b: DetailConstituent,
): number {
  if (a.rank != null && b.rank != null && a.rank !== b.rank) {
    return a.rank - b.rank;
  }
  if (a.rank != null && b.rank == null) return -1;
  if (a.rank == null && b.rank != null) return 1;
  return (b.weight ?? -1) - (a.weight ?? -1);
}

export function ConstituentsTab({ detail }: { detail: ValuationDetailData }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);

  const ordered = useMemo(
    () => [...detail.constituents].sort(compareConstituents),
    [detail.constituents],
  );
  const top = useMemo(
    () => ordered.filter((item) => item.weight != null).slice(0, 8),
    [ordered],
  );
  const chartOption = useMemo(
    () => buildWeightBarOption(top, theme),
    [top, theme],
  );
  const effectiveDate = ordered[0]?.effective_date ?? null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <CardTitle className="text-base">前 8 大权重</CardTitle>
            <span className="text-xs tabular-nums text-muted-foreground">
              {effectiveDate ? `成分生效日 ${effectiveDate}` : "最新成分快照"}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            按最新生效日权重排序；权重单位为百分比。
          </p>
        </CardHeader>
        <CardContent className="pt-2">
          {top.length > 0 ? (
            <EChart
              option={chartOption}
              style={{
                height: Math.max(240, top.length * 42 + 32),
                width: "100%",
              }}
            />
          ) : (
            <div className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-6 text-center text-sm text-muted-foreground">
              暂无成分股权重数据
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">成分股权重</CardTitle>
          <p className="text-xs text-muted-foreground">
            后端按最新生效日返回前 60 大成分；行业缺失显示「—」。
          </p>
        </CardHeader>
        <CardContent className="pt-2">
          {ordered.length > 0 ? (
            <div className="overflow-x-auto overscroll-x-contain rounded-lg border border-border">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <caption className="sr-only">
                  指数成分股权重表，含排名、代码、名称、行业与权重
                </caption>
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      排名
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      代码
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      名称
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      行业
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-right font-medium"
                    >
                      权重
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ordered.map((item) => (
                    <tr
                      key={item.stock_code}
                      className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                    >
                      <td className="px-4 py-3 tabular-nums text-muted-foreground">
                        {item.rank != null
                          ? formatNumber(item.rank, 0)
                          : EMPTY_DISPLAY}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs tabular-nums">
                        {item.stock_code}
                      </td>
                      <td className="px-4 py-3 font-medium">{item.name}</td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {item.industry_l1?.trim()
                          ? item.industry_l1
                          : EMPTY_DISPLAY}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">
                        {formatPlainPct(item.weight)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-10 text-center">
              <p className="text-sm font-medium">暂无成分股数据</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                后端尚未落库该指数的最新成分股快照。
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">业绩</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-10 text-center">
            <p className="text-sm font-medium">业绩数据暂未接入</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              后端暂未提供营收/净利同比与年度财务数据，当前仅展示成分股权重。
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
