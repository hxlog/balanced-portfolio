"use client";

import { useMemo } from "react";
import { useTheme } from "next-themes";
import { EChart } from "@/components/EChart";
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
import {
  ChartCard,
  SectionHeading,
  Surface,
} from "../_components/valuation-ui";

const CHART_HEIGHT = 280;

/** 前 12 大权重横向条形图（单系列；完整表格即其可访问数据视图）。 */
function buildWeightBarOption(
  top: readonly DetailConstituent[],
  theme: ChartTheme,
): Record<string, unknown> {
  return {
    animation: false,
    grid: { left: 4, right: 52, top: 4, bottom: 4, containLabel: true },
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
      axisLabel: { color: theme.subtext, fontSize: 9, formatter: "{value}%" },
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
        fontSize: 10,
        width: 84,
        overflow: "truncate",
      },
    },
    series: [
      {
        name: "权重",
        type: "bar",
        data: top.map((item) => item.weight),
        barWidth: 10,
        itemStyle: {
          color: theme.palette[0],
          borderRadius: [0, 4, 4, 0],
        },
        label: {
          show: true,
          position: "right",
          color: theme.subtext,
          fontSize: 9,
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
    () => ordered.filter((item) => item.weight != null).slice(0, 12),
    [ordered],
  );
  const chartOption = useMemo(
    () => buildWeightBarOption(top, theme),
    [top, theme],
  );
  const effectiveDate = ordered[0]?.effective_date ?? null;

  if (ordered.length === 0) {
    return (
      <Surface className="flex flex-col items-center justify-center px-6 py-14 text-center">
        <p className="text-sm font-medium">暂无成分股数据</p>
        <p className="mt-1 text-xs text-muted-foreground">
          后端尚未落库该指数的最新成分股快照。
        </p>
      </Surface>
    );
  }

  return (
    <div className="space-y-4">
      <ChartCard
        title="前 12 大权重"
        hint="按最新生效日权重排序"
        aside={
          <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
            {effectiveDate ?? "最新快照"}
          </span>
        }
        bodyClassName="px-2 pb-2"
      >
        {top.length > 0 ? (
          <EChart
            option={chartOption}
            style={{ height: CHART_HEIGHT, width: "100%" }}
          />
        ) : (
          <div
            className="flex items-center justify-center text-xs text-muted-foreground"
            style={{ height: CHART_HEIGHT }}
          >
            暂无权重数据
          </div>
        )}
      </ChartCard>

      <section aria-labelledby="constituent-table-heading">
        <SectionHeading
          id="constituent-table-heading"
          title="成分列表"
          hint={`${formatNumber(ordered.length, 0)} 只`}
        />
        <Surface className="overflow-hidden">
          <div className="max-h-[360px] overflow-auto overscroll-contain">
            <table className="w-full min-w-[620px] border-collapse text-sm">
              <caption className="sr-only">
                指数成分股权重表，含排名、代码、名称、行业与权重
              </caption>
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-muted text-[11px] text-muted-foreground">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    排名
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    代码
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    名称
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    行业
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
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
                    <td className="px-3 py-2 font-mono text-xs tabular-nums text-muted-foreground">
                      {formatNumber(item.rank, 0)}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs tabular-nums">
                      {item.stock_code}
                    </td>
                    <td className="px-3 py-2 font-medium">{item.name}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {item.industry_l1?.trim()
                        ? item.industry_l1
                        : EMPTY_DISPLAY}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">
                      {formatPlainPct(item.weight)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>
      </section>
    </div>
  );
}
