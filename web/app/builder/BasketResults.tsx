"use client";

import { useMemo, useState } from "react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatDateCN } from "@/lib/asset-range";
import { getChartTheme, withAlpha } from "@/lib/chart-theme";
import {
  basketNavLegend,
  basketNavSeriesFlags,
  basketWeightRows,
  formatPct,
  formatRatio,
  formatSignedPct,
} from "@/lib/basket-format";
import type {
  BasketBacktestResult,
  BasketRebalanceEvent,
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
  optimizeLoading,
  optimizeError,
  optimizeDirty,
  backtest,
  backtestLoading,
  backtestError,
  backtestDirty,
  /** 已还原的 latest_result 参数与当前表单不一致（需重新回测才能写回结果）。 */
  backtestParamsStale,
  bandPct,
  isDark,
}: {
  weights: BasketWeight[];
  nameByKey: ReadonlyMap<string, string>;
  assetCount: number;
  methodShort: string;
  optimizeLoading: boolean;
  optimizeError: string | null;
  optimizeDirty: boolean;
  backtest: BasketBacktestResult | null;
  backtestLoading: boolean;
  backtestError: string | null;
  backtestDirty: boolean;
  /** 已还原的 latest_result 参数与当前表单不一致（需重新回测才能写回结果）。 */
  backtestParamsStale: boolean;
  bandPct: number;
  isDark: boolean;
}) {
  const theme = useMemo(() => getChartTheme(isDark), [isDark]);
  const [rebalanceDetail, setRebalanceDetail] = useState<BasketRebalanceEvent | null>(null);
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
    const eqPoints = backtest?.equal_weight_nav ?? [];
    const events = backtest?.rebalance_events ?? [];
    const navByDate = new Map(points.map((point) => [point.trade_date, point.nav]));
    return {
      animationDuration: 320,
      legend: {
        top: 0,
        left: 0,
        itemWidth: 14,
        itemHeight: 8,
        textStyle: { color: theme.subtext, fontSize: 11 },
        // 只列真实画出的系列：latest_result 还原 / 旧后端可能缺等权净值与调仓事件。
        data: basketNavLegend(backtest),
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text, fontFamily: "monospace" },
        axisPointer: { type: "cross" },
        valueFormatter: (value: number) =>
          value == null || !Number.isFinite(value) ? "-" : Number(value).toFixed(4),
      },
      grid: { top: 34, right: 18, bottom: 30, left: 52 },
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
                { offset: 0, color: withAlpha(theme.palette[0], 0.28) },
                { offset: 1, color: withAlpha(theme.palette[0], 0) },
              ],
            },
          },
        },
        {
          name: "等权净值",
          type: "line",
          showSymbol: false,
          smooth: true,
          data: eqPoints.length > 0 ? eqPoints.map((point) => point.nav) : [],
          lineStyle: { width: 1.6, color: theme.palette[1], type: "dashed" },
          itemStyle: { color: theme.palette[1] },
        },
        {
          name: "调仓",
          type: "scatter",
          symbol: "diamond",
          symbolSize: 11,
          z: 5,
          data: events.map((event) => ({
            value: [event.trade_date, navByDate.get(event.trade_date) ?? 1.0],
            rb: event,
          })),
          itemStyle: { color: "#d97706", borderColor: "#fff", borderWidth: 1 },
          tooltip: {
            formatter: (params: { data?: { rb?: BasketRebalanceEvent } }) => {
              const rb = params.data?.rb;
              if (!rb) return "";
              return (
                "<b>调仓 " + rb.trade_date + "</b><br/>" +
                "换手 " + formatPct(rb.turnover, 2) + "<br/>" +
                "点击查看权重变化"
              );
            },
          },
        },
      ],
    };
  }, [backtest, theme]);

  const clickEvents = useMemo(
    () => ({
      click: (params: unknown) => {
        const detail = params as { seriesName?: string; data?: { rb?: BasketRebalanceEvent } } | null;
        if (detail?.seriesName === "调仓" && detail?.data?.rb) {
          setRebalanceDetail(detail.data.rb);
        }
      },
    }),
    [],
  );

  const sortedLatestWeights = useMemo(
    () => [...activeRows].sort((a, b) => b.weight - a.weight),
    [activeRows],
  );

  const showWeightsSkeleton = optimizeLoading && rows.length === 0;
  const showDiagSkeleton = backtestLoading && backtest == null;
  const navSeries = backtest
    ? basketNavSeriesFlags(backtest)
    : { equalWeight: false, rebalance: false };
  const fees = backtest?.fees ?? null;
  const feeSummary = fees
    ? `佣金 ${formatPct(fees.fee_rate, 2)} · 滑点 ${formatPct(
        fees.slippage_rate,
        2,
      )} · 卖出印花税 ${formatPct(fees.stamp_duty_rate, 2)}`
    : "佣金 0.03% · 滑点 0.10% · 卖出印花税 0.10%";

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
        <CardContent className="space-y-4">
          {optimizeError && <BasketErrorPanel message={optimizeError} />}
          {showWeightsSkeleton ? (
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
            optimizeError ? null : (
              <div className="rounded-lg border border-dashed border-border bg-bg-subtle/40 px-4 py-10 text-center text-sm text-muted-foreground">
                {assetCount === 0
                  ? "添加资产后自动计算权重"
                  : "暂无可展示的权重，请检查参数后重试"}
              </div>
            )
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
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold">组合诊断</h2>
              <Badge
                variant="outline"
                className="border-primary/40 bg-primary/5 font-normal text-primary"
              >
                扣费后
              </Badge>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {backtest
                ? `最近一次回测 · ${backtest.n_obs} 个交易日 · ${feeSummary}`
                : "运行回测后生成（净值与指标均为扣费后口径）"}
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {showDiagSkeleton
            ? Array.from({ length: 7 }).map((_, index) => (
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
                    value={backtest ? formatSignedPct(backtest.annualized_return) : "—"}
                    caption={backtest ? "扣费后 · 年化" : "等待回测"}
                    tone={
                      backtest
                        ? backtest.annualized_return > 0
                          ? "up"
                          : backtest.annualized_return < 0
                            ? "down"
                            : "neutral"
                        : "neutral"
                    }
                  />
                  <DiagnosticCard
                    label="最大回撤"
                    value={backtest ? formatPct(backtest.max_drawdown) : "—"}
                    caption={backtest ? "扣费后 · 区间峰值回撤" : "等待回测"}
                    tone={
                      backtest && backtest.max_drawdown < 0 ? "down" : "neutral"
                    }
                  />
                  <DiagnosticCard
                    label="年化换手"
                    value={backtest ? formatPct(backtest.turnover) : "—"}
                    caption={backtest ? "双边 · 扣费后净值口径" : "等待回测"}
                  />
                  <DiagnosticCard
                    label="交易日数量"
                    value={backtest ? `${backtest.n_obs} 日` : "—"}
                    caption={backtest ? "回测区间交易日" : "等待回测"}
                  />
                  <DiagnosticCard
                    label="Sharpe"
                    value={backtest ? formatRatio(backtest.sharpe) : "—"}
                    caption={backtest ? "扣费后 · 年化风险调整" : "等待回测"}
                  />
                  <DiagnosticCard
                    label="Sortino"
                    value={
                      backtest ? formatRatio(backtest.sortino ?? null) : "—"
                    }
                    caption={backtest ? "扣费后 · 下行风险调整" : "等待回测"}
                  />
                  <DiagnosticCard
                    label="Calmar"
                    value={backtest ? formatRatio(backtest.calmar ?? null) : "—"}
                    caption={backtest ? "扣费后 · 年化收益/最大回撤" : "等待回测"}
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
                    } · 扣费后（${feeSummary}）`
                  : `任一资产偏离目标超过 ${formatPct(
                      bandPct / 100,
                      1,
                    )} 时整体再平衡 · 扣费后（${feeSummary}）`}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {backtestParamsStale ? (
                <Badge variant="outline" className="border-warning/40 text-warning">
                  结果参数已变更，请重新回测
                </Badge>
              ) : backtestDirty ? (
                <Badge variant="outline" className="border-warning/40 text-warning">
                  参数已变更
                </Badge>
              ) : null}
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
                style={{ height: 330, width: "100%" }}
                onEvents={clickEvents}
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                实线=篮子净值（{methodShort}，扣费后）
                {navSeries.equalWeight ? " · 虚线=等权净值" : null}
                {navSeries.rebalance ? (
                  <>
                    {" · "}
                    <span className="text-warning">◆ 调仓点</span>
                    （点击查看权重变化）
                  </>
                ) : null}
              </p>
              <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-4 sm:grid-cols-4">
                <MiniStat
                  label="年化收益（扣费后）"
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
                  label="年化换手（扣费后）"
                  value={formatPct(backtest.turnover)}
                />
                <MiniStat label="交易日数量" value={`${backtest.n_obs} 日`} />
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={rebalanceDetail != null} onOpenChange={(open) => { if (!open) setRebalanceDetail(null); }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>调仓明细 · {rebalanceDetail?.trade_date ?? ""}</DialogTitle>
            <DialogDescription>
              {rebalanceDetail?.reason ?? "再平衡"}
              {rebalanceDetail ? " · 换手 " + formatPct(rebalanceDetail.turnover, 2) : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[52vh] overflow-auto">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 bg-background">
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">资产</th>
                  <th className="py-1.5 text-right font-medium">变化前</th>
                  <th className="py-1.5 text-right font-medium">变化后</th>
                  <th className="py-1.5 text-right font-medium">变化量</th>
                </tr>
              </thead>
              <tbody>
                {(rebalanceDetail?.assets ?? [])
                  .filter((item) => Math.abs(item.delta) > 1e-8)
                  .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
                  .map((item) => (
                    <tr key={item.key} className="border-b border-border/50 last:border-0">
                      <td className="py-1.5">
                        {nameByKey.get(item.key) ?? item.symbol}
                        <span className="ml-1 font-mono text-[10px] text-muted-foreground">{item.symbol}</span>
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">{formatPct(item.prev_weight, 2)}</td>
                      <td className="py-1.5 text-right font-mono tabular-nums">{formatPct(item.target_weight, 2)}</td>
                      <td className={cn("py-1.5 text-right font-mono tabular-nums", item.delta > 0 ? "text-up" : item.delta < 0 ? "text-down" : "")}>
                        {item.delta > 0 ? "+" : ""}
                        {formatPct(item.delta, 2)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border pt-3">
            <p className="mb-1 text-xs font-medium">最新一期权重</p>
            <div className="max-h-40 overflow-auto">
              <table className="w-full border-collapse text-xs">
                <tbody>
                  {sortedLatestWeights.map((row) => (
                    <tr key={row.key ?? row.name} className="border-b border-border/40 last:border-0">
                      <td className="py-1 text-left">{row.name}</td>
                      <td className="py-1 text-right font-mono tabular-nums">{formatPct(row.weight, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </DialogContent>
      </Dialog>
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
