"use client";

import { useMemo } from "react";
import { useTheme } from "next-themes";
import { EChart } from "@/components/EChart";
import { getChartTheme, type ChartTheme } from "@/lib/chart-theme";
import {
  EMPTY_DISPLAY,
  formatAumYi,
  formatNumber,
} from "@/lib/valuation-detail-format";
import type {
  DetailTrackerFund,
  ValuationDetailData,
} from "@/lib/valuation-detail-types";
import {
  ChartCard,
  SectionHeading,
  sumAum,
  Surface,
} from "../_components/valuation-ui";

const CHART_HEIGHT = 260;

interface FundBar {
  fund: DetailTrackerFund;
  aumYi: number;
}

function buildFundBarOption(
  bars: readonly FundBar[],
  theme: ChartTheme,
): Record<string, unknown> {
  return {
    animation: false,
    grid: { left: 4, right: 56, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 12 },
      valueFormatter: (value: unknown) =>
        typeof value === "number" && Number.isFinite(value)
          ? `${value.toFixed(2)} 亿元`
          : EMPTY_DISPLAY,
    },
    xAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.subtext, fontSize: 9 },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: bars.map((bar) => bar.fund.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: theme.text,
        fontSize: 10,
        width: 96,
        overflow: "truncate",
      },
    },
    series: [
      {
        name: "规模",
        type: "bar",
        data: bars.map((bar) => bar.aumYi),
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
              ? params.value.toFixed(2)
              : EMPTY_DISPLAY,
        },
      },
    ],
  };
}

export function FundsTab({ detail }: { detail: ValuationDetailData }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const theme = getChartTheme(isDark);
  const funds = detail.tracker_funds;
  const total = sumAum(funds);
  const asOf =
    funds.find((fund) => fund.trade_date)?.trade_date ?? detail.trade_date;

  const bars = useMemo<FundBar[]>(
    () =>
      funds
        .filter(
          (fund): fund is DetailTrackerFund & { aum: number } =>
            fund.aum != null && Number.isFinite(fund.aum) && fund.aum > 0,
        )
        .sort((a, b) => b.aum - a.aum)
        .slice(0, 10)
        .map((fund) => ({ fund, aumYi: fund.aum / 1e8 })),
    [funds],
  );
  const chartOption = useMemo(
    () => buildFundBarOption(bars, theme),
    [bars, theme],
  );

  if (funds.length === 0) {
    return (
      <Surface className="flex flex-col items-center justify-center px-6 py-14 text-center">
        <p className="text-sm font-medium">暂无跟踪基金数据</p>
        <p className="mt-1 text-xs text-muted-foreground">
          后端尚未落库该指数的 ETF / 联接基金快照。
        </p>
      </Surface>
    );
  }

  return (
    <div className="space-y-4">
      <Surface className="grid grid-cols-1 divide-y divide-border sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="p-4">
          <div className="text-[10px] text-muted-foreground">合计规模</div>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
              {formatAumYi(total)}
            </span>
            <span className="text-[11px] text-muted-foreground">亿元</span>
          </div>
        </div>
        <div className="p-4">
          <div className="text-[10px] text-muted-foreground">跟踪基金</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
            {formatNumber(funds.length, 0)}
            <span className="ml-1 text-[11px] font-normal text-muted-foreground">
              只
            </span>
          </div>
        </div>
        <div className="p-4">
          <div className="text-[10px] text-muted-foreground">数据截至</div>
          <div className="mt-1 font-mono text-sm tabular-nums">
            {asOf ?? EMPTY_DISPLAY}
          </div>
        </div>
      </Surface>

      <ChartCard
        title="ETF 规模"
        hint="前 10 只 · 单位亿元"
        bodyClassName="px-2 pb-2"
      >
        {bars.length > 0 ? (
          <EChart
            option={chartOption}
            style={{ height: CHART_HEIGHT, width: "100%" }}
          />
        ) : (
          <div
            className="flex items-center justify-center text-xs text-muted-foreground"
            style={{ height: CHART_HEIGHT }}
          >
            暂无有效的规模数据
          </div>
        )}
      </ChartCard>

      <section aria-labelledby="fund-table-heading">
        <SectionHeading
          id="fund-table-heading"
          title="基金列表"
          hint={`${formatNumber(funds.length, 0)} 只`}
        />
        <Surface className="overflow-hidden">
          <div className="max-h-[360px] overflow-auto overscroll-contain">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <caption className="sr-only">
                跟踪该指数的基金列表，含代码、名称、基金公司、风险等级与规模
              </caption>
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-muted text-[11px] text-muted-foreground">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    代码
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    基金
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    基金公司
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    风险
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    规模（亿元）
                  </th>
                </tr>
              </thead>
              <tbody>
                {funds.map((fund) => (
                  <tr
                    key={fund.fund_code}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                  >
                    <td className="px-3 py-2 font-mono text-xs tabular-nums">
                      {fund.fund_code}
                    </td>
                    <td className="px-3 py-2 font-medium">{fund.name}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {fund.company_name ?? EMPTY_DISPLAY}
                    </td>
                    <td className="px-3 py-2">
                      {fund.risk_grade ? (
                        <span className="inline-flex items-center rounded border border-border px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground">
                          {fund.risk_grade}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {EMPTY_DISPLAY}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">
                      {formatAumYi(fund.aum)}
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
