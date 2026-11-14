"use client";

import { useMemo } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EChart } from "@/components/EChart";
import { formatDateCN } from "@/lib/asset-range";
import { getChartTheme, withAlpha } from "@/lib/chart-theme";
import {
  basketWeightRows,
  formatPct,
  formatRatio,
  formatSignedPct,
} from "@/lib/basket-format";
import type {
  BasketBacktestResult,
  BasketDiagnostics,
  BasketWeight,
} from "@/lib/basket-types";
import { cn } from "@/lib/utils";

export function BasketErrorPanel({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="min-w-0 break-words">{message}</span>
    </div>
  );
}

function Pulse({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function BasketResults({
  weights,
  nameByKey,
  assetCount,
  methodShort,
  diagnostics,
  optimizeLoading,
  optimizeError,
  optimizeDirty,
  backtest,
  backtestLoading,
  backtestError,
  backtestDirty,
  bandPct,
  isDark,
}: {
  weights: BasketWeight[];
  nameByKey: ReadonlyMap<string, string>;
  assetCount: number;
  methodShort: string;
  diagnostics: BasketDiagnostics | null;
  optimizeLoading: boolean;
  optimizeError: string | null;
  optimizeDirty: boolean;
  backtest: BasketBacktestResult | null;
  backtestLoading: boolean;
  backtestError: string | null;
  backtestDirty: boolean;
  bandPct: number;
  isDark: boolean;
}) {
  const theme = useMemo(() => getChartTheme(isDark), [isDark]);
  const rows = useMemo(
    () => basketWeightRows(weights, nameByKey, isDark),
    [weights, nameByKey, isDark],
  );
  const activeRows = useMemo(
    () => rows.filter((row) => row.weight > 0),
    [rows],
  );

  const donutOption = useMemo<Record<string, unknown>>(
    () => ({
      animationDuration: 320,
      tooltip: {
        trigger: "item",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text },
        formatter: (params: { name?: string; value?: number }) =>
          `${params.name ?? ""}<br/><span style="font-family:monospace;font-variant-numeric:tabular-nums">${formatPct(
            Number(params.value ?? 0),
            2,
          )}</span>`,
      },
      title: {
        text: methodShort,
        subtext: `${activeRows.length} 项有效`,
        left: "center",
        top: "40%",
        textAlign: "center",
        textStyle: { color: theme.text, fontSize: 13, fontWeight: 600 },
        subtextStyle: { color: theme.subtext, fontSize: 11 },
      },
      series: [
        {
          name: "目标权重",
          type: "pie",
          radius: ["56%", "78%"],
          center: ["50%", "50%"],
          itemStyle: { borderColor: theme.tooltipBg, borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scaleSize: 4 },
          data: activeRows.map((row) => ({
            name: row.name,
            value: +row.weight.toFixed(6),
            itemStyle: { color: row.color },
          })),
        },
      ],
    }),
    [activeRows, methodShort, theme],
  );

  const navOption = useMemo<Record<string, unknown>>(() => {
    const points = backtest?.nav ?? [];
    return {
      animationDuration: 320,
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text, fontFamily: "monospace" },
        axisPointer: { type: "cross" },
        valueFormatter: (value: number) =>
          value == null || !Number.isFinite(value) ? "-" : Number(value).toFixed(4),
      },
      grid: { top: 20, right: 18, bottom: 30, left: 52 },
      xAxis: {
        type: "category",
        data: points.map((point) => point.trade_date),
        axisLabel: { color: theme.subtext, hideOverlap: true },
        axisLine: { lineStyle: { color: theme.axisLine } },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: theme.subtext },
        splitLine: { lineStyle: { color: theme.splitLine } },
      },
      series: [
        {
          name: "篮子净值",
          type: "line",
          showSymbol: false,
          smooth: true,
          data: points.map((point) => point.nav),
          lineStyle: { width: 2, color: theme.palette[0] },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: withAlpha(theme.palette[0], 0.3) },
                { offset: 1, color: withAlpha(theme.palette[0], 0) },
              ],
            },
          },
        },
      ],
    };
  }, [backtest, theme]);

  const showWeightsSkeleton = optimizeLoading && rows.length === 0;
  const showDiagSkeleton = optimizeLoading && diagnostics == null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">目标权重</CardTitle>
              <CardDescription>
                {methodShort} · {activeRows.length} 项有效 / {assetCount} 项资产
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {optimizeDirty && (
                <Badge variant="outline" className="border-warning/40 text-warning">
                  参数已变更
                </Badge>
              )}
              {optimizeLoading && rows.length > 0 && (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {optimizeError ? (
            <BasketErrorPanel message={optimizeError} />
          ) : showWeightsSkeleton ? (
            <div className="grid items-center gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="space-y-4">
                {Array.from({ length: 5 }).map((_, index) => (
                  <div key={index} className="space-y-1.5">
                    <div className="flex justify-between gap-4">
                      <Pulse className="h-3 w-28" />
                      <Pulse className="h-3 w-12" />
                    </div>
                    <Pulse className="h-2 w-full" />
                  </div>
                ))}
              </div>
              <Pulse className="mx-auto h-[220px] w-[220px] rounded-full" />
            </div>
          ) : rows.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-bg-subtle/40 px-4 py-10 text-center text-sm text-muted-foreground">
              {assetCount === 0
                ? "添加资产后自动计算权重"
                : "暂无可展示的权重，请检查参数后重试"}
            </div>
          ) : (
            <div className="grid items-center gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="space-y-3">
                {rows.map((row) => (
                  <div key={row.key} className="group">
                    <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                      <span className="min-w-0 truncate font-medium">{row.name}</span>
                      <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
                        {formatPct(row.weight, 2)}
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full transition-[width] duration-500 ease-out"
                        style={{
                          width: `${row.weight * 100}%`,
                          minWidth: row.weight > 0 ? 2 : 0,
                          backgroundColor: row.color,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <div className="h-[250px] w-full">
                {activeRows.length > 0 ? (
                  <EChart
                    option={donutOption}
                    style={{ height: "100%", width: "100%" }}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                    暂无有效权重
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">组合诊断</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {diagnostics
                ? `回看 ${diagnostics.lookback} 个交易日 · 样本 ${diagnostics.n_obs} 日 · 起始 ${
                    formatDateCN(diagnostics.effective_start) ?? "—"
                  }`
                : "选择资产后基于滚动窗口自动计算"}
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {showDiagSkeleton
            ? Array.from({ length: 4 }).map((_, index) => (
                <Card key={index}>
                  <CardContent className="space-y-2 p-4">
                    <Pulse className="h-3 w-16" />
                    <Pulse className="h-7 w-24" />
                    <Pulse className="h-3 w-20" />
                  </CardContent>
                </Card>
              ))
            : (
                <>
                  <DiagnosticCard
                    label="年化收益"
                    value={
                      diagnostics
                        ? formatSignedPct(diagnostics.annualized_return)
                        : "—"
                    }
                    caption={
                      diagnostics ? `回看 ${diagnostics.lookback} 日` : "等待计算"
                    }
                    tone={
                      diagnostics
                        ? diagnostics.annualized_return > 0
                          ? "up"
                          : diagnostics.annualized_return < 0
                            ? "down"
                            : "neutral"
                        : "neutral"
                    }
                  />
                  <DiagnosticCard
                    label="年化波动"
                    value={diagnostics ? formatPct(diagnostics.volatility) : "—"}
                    caption={diagnostics ? `${diagnostics.n_obs} 个样本` : "等待计算"}
                  />
                  <DiagnosticCard
                    label="夏普比率"
                    value={diagnostics ? formatRatio(diagnostics.sharpe) : "—"}
                    caption="年化风险调整收益"
                  />
                  <DiagnosticCard
                    label="有效资产"
                    value={
                      diagnostics
                        ? `${diagnostics.active_assets} / ${assetCount}`
                        : "—"
                    }
                    caption={
                      diagnostics
                        ? `起始 ${formatDateCN(diagnostics.effective_start) ?? "—"}`
                        : "等待计算"
                    }
                  />
                </>
              )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">回测净值</CardTitle>
              <CardDescription>
                {backtest
                  ? `偏离带 ${formatPct(bandPct / 100, 1)} · ${backtest.rebalance_count} 次调仓 · 有效起点 ${
                      formatDateCN(backtest.effective_start) ?? "—"
                    }`
                  : `任一资产偏离目标超过 ${formatPct(bandPct / 100, 1)} 时整体再平衡`}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {backtestDirty && (
                <Badge variant="outline" className="border-warning/40 text-warning">
                  参数已变更
                </Badge>
              )}
              {backtestLoading && (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {backtestError ? (
            <BasketErrorPanel message={backtestError} />
          ) : backtestLoading && !backtest ? (
            <Pulse className="h-[320px] w-full" />
          ) : !backtest ? (
            <div className="flex h-[240px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-bg-subtle/40 text-center">
              <p className="text-sm text-muted-foreground">
                点击「运行回测」生成净值曲线
              </p>
              <p className="text-xs text-muted-foreground">
                回测只读清洗行情，成分不足窗口时权重为 0，不拖后整体起点。
              </p>
            </div>
          ) : (
            <>
              <EChart
                option={navOption}
                style={{ height: 320, width: "100%" }}
              />
              <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-4 sm:grid-cols-4">
                <MiniStat
                  label="年化收益"
                  value={formatSignedPct(backtest.annualized_return)}
                  tone={
                    backtest.annualized_return > 0
                      ? "up"
                      : backtest.annualized_return < 0
                        ? "down"
                        : "neutral"
                  }
                />
                <MiniStat
                  label="最大回撤"
                  value={formatPct(backtest.max_drawdown)}
                  tone={backtest.max_drawdown < 0 ? "down" : "neutral"}
                />
                <MiniStat
                  label="年化换手"
                  value={formatPct(backtest.turnover)}
                />
                <MiniStat label="样本" value={`${backtest.n_obs} 日`} />
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DiagnosticCard({
  label,
  value,
  caption,
  tone = "neutral",
}: {
  label: string;
  value: string;
  caption: string;
  tone?: "up" | "down" | "neutral";
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div
          className={cn(
            "mt-1.5 font-mono text-xl font-semibold tabular-nums sm:text-2xl",
            tone === "up" && "text-up",
            tone === "down" && "text-down",
          )}
        >
          {value}
        </div>
        <div className="mt-1 truncate text-[11px] text-muted-foreground">
          {caption}
        </div>
      </CardContent>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "up" | "down" | "neutral";
}) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 font-mono text-sm font-medium tabular-nums sm:text-base",
          tone === "up" && "text-up",
          tone === "down" && "text-down",
        )}
      >
        {value}
      </div>
    </div>
  );
}
