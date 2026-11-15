"use client";

import { useEffect, useMemo, useState } from "react";
import { useTheme } from "next-themes";
import { Activity, AlertTriangle, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EChart } from "@/components/EChart";
import { getChartTheme, withAlpha } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";
import {
  formatThousands,
  formatNotionalAxis,
  formatPrice,
  formatPriceAxis,
  formatRatio,
  formatShanghaiChartLabel,
  normalizeSeriesPoint,
  shanghaiDayKey,
} from "@/lib/crypto-futures-format";
import type {
  CryptoFuturesContract,
  CryptoFuturesSeriesPoint,
} from "@/lib/crypto-futures-types";

const SERIES_REFRESH_MS = 60_000;

/** 序列窗口：回补 Binance 历史后可查看 7 天 / 30 天。 */
const SERIES_WINDOWS = [
  { hours: 24, label: "24H", desc: "最近 24 小时" },
  { hours: 168, label: "7D", desc: "最近 7 天" },
  { hours: 720, label: "30D", desc: "最近 30 天" },
] as const;

type SeriesWindowHours = (typeof SERIES_WINDOWS)[number]["hours"];

type SeriesStatus = "loading" | "ready" | "error";

interface SeriesState {
  status: SeriesStatus;
  data: CryptoFuturesSeriesPoint[];
  error: string | null;
}

function longShortTone(value: number | null): string {
  if (value == null) return "text-muted-foreground";
  if (value > 1) return "text-success";
  if (value < 1) return "text-destructive";
  return "text-foreground";
}

function finiteValues(values: ReadonlyArray<number | null>): number[] {
  return values.filter(
    (value): value is number => value != null && Number.isFinite(value),
  );
}

function minMax(values: ReadonlyArray<number | null>): [number, number] | null {
  const finite = finiteValues(values);
  if (finite.length === 0) return null;
  return [Math.min(...finite), Math.max(...finite)];
}

function ChartSkeleton() {
  return <div className="h-[440px] w-full animate-pulse rounded-lg bg-muted" />;
}

function ChartEmpty() {
  return (
    <div className="flex h-[440px] flex-col items-center justify-center gap-2 px-6 text-center">
      <Activity className="h-7 w-7 text-muted-foreground/60" aria-hidden="true" />
      <p className="text-sm font-medium">暂无 24 小时序列</p>
      <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
        首次部署或该合约刚进入合约池时，5 分钟快照尚在积累。数据落库后会自动出现。
      </p>
    </div>
  );
}

export function CryptoFuturesChart({
  contract,
}: {
  contract: CryptoFuturesContract;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const [state, setState] = useState<SeriesState>({
    status: "loading",
    data: [],
    error: null,
  });
  const [retryToken, setRetryToken] = useState(0);
  const [hours, setHours] = useState<SeriesWindowHours>(24);

  const contractCode = contract.contract_code;
  const windowMeta = SERIES_WINDOWS.find((item) => item.hours === hours) ?? SERIES_WINDOWS[0];

  useEffect(() => {
    let cancelled = false;
    let controller: AbortController | null = null;

    setState({ status: "loading", data: [], error: null });

    const load = async (initial: boolean) => {
      controller?.abort();
      const nextController = new AbortController();
      controller = nextController;
      try {
        const response = await fetch(
          `/api/crypto/futures/${encodeURIComponent(contractCode)}/series?hours=${hours}`,
          {
            cache: "no-store",
            headers: { Accept: "application/json" },
            signal: nextController.signal,
          },
        );
        if (!response.ok) {
          if (response.status === 404) throw new Error("未找到该合约的序列数据");
          throw new Error(`序列接口返回 ${response.status}`);
        }
        const body = (await response.json()) as { data?: unknown };
        const rows = Array.isArray(body.data)
          ? body.data
            .map(normalizeSeriesPoint)
            .filter((row): row is CryptoFuturesSeriesPoint => row !== null)
          : [];
        if (!cancelled) {
          setState({ status: "ready", data: rows, error: null });
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof Error && error.name === "AbortError") return;
        const message = error instanceof Error ? error.message : "获取序列失败";
        setState((previous) => ({
          status: "error",
          // 自动刷新失败时保留上一份数据，避免图表闪成错误态。
          data: initial ? [] : previous.data,
          error: message,
        }));
      }
    };

    void load(true);
    const timer = window.setInterval(() => {
      void load(false);
    }, SERIES_REFRESH_MS);

    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, [contractCode, retryToken, hours]);

  const points = state.data;
  const spansMultipleDays = useMemo(
    () => new Set(points.map((point) => shanghaiDayKey(point.captured_at))).size > 1,
    [points],
  );

  const rangeSummary = useMemo(() => {
    const price = minMax(points.map((point) => point.mark_price));
    const oi = minMax(points.map((point) => point.oi_notional));
    const ratio = minMax(points.map((point) => point.long_short_ratio));
    return { price, oi, ratio };
  }, [points]);

  const chartOption = useMemo(() => {
    const theme = getChartTheme(isDark);
    const priceColor = theme.palette[0];
    const oiColor = theme.palette[2];
    const ratioColor = theme.palette[4];

    const labels = points.map((point) =>
      formatShanghaiChartLabel(point.captured_at, spansMultipleDays),
    );
    const priceData = points.map((point) => point.mark_price);
    const oiData = points.map((point) => point.oi_notional);
    const ratioData = points.map((point) => point.long_short_ratio);

    return {
      backgroundColor: "transparent",
      animation: false,
      textStyle: { color: theme.text },
      aria: {
        enabled: true,
        description: `${contractCode} ${windowMeta.desc}：标记价折线、OI 名义值面积图与多空比折线。`,
      },
      legend: {
        top: 0,
        left: 4,
        itemWidth: 14,
        itemHeight: 8,
        textStyle: { color: theme.subtext, fontSize: 11 },
        data: ["标记价", "OI 名义值", "多空比"],
      },
      axisPointer: {
        link: [{ xAxisIndex: "all" }],
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.text, fontSize: 12 },
        axisPointer: {
          type: "cross",
          crossStyle: { color: theme.axisLine },
        },
        formatter: (rawParams: unknown) => {
          if (!Array.isArray(rawParams) || rawParams.length === 0) return "";
          const first = rawParams[0] as { axisValue?: string };
          const rows = new Map<string, string>();

          for (const raw of rawParams) {
            const param = raw as {
              seriesName?: string;
              value?: unknown;
              color?: string;
            };
            if (!param.seriesName || rows.has(param.seriesName)) continue;
            if (typeof param.value !== "number" || !Number.isFinite(param.value)) {
              continue;
            }

            const value = param.value;
            let display: string;
            if (param.seriesName === "标记价") {
              display = `USDT ${formatPrice(value)}`;
            } else if (param.seriesName === "OI 名义值") {
              display = `${formatThousands(value)} USDT`;
            } else {
              display = formatRatio(value, 3);
            }

            const marker = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${param.color ?? theme.subtext};margin-right:5px"></span>`;
            rows.set(
              param.seriesName,
              `<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;margin:3px 0">`
                + `<span>${marker}${param.seriesName}</span>`
                + `<b style="font-variant-numeric:tabular-nums">${display}</b>`
                + `</div>`,
            );
          }

          return `<div style="font-size:11px;color:${theme.subtext};margin-bottom:4px">${first.axisValue ?? ""}</div>`
            + [...rows.values()].join("");
        },
      },
      dataZoom: [
        {
          type: "inside",
          xAxisIndex: [0, 1],
          // 不写 start/end：ECharts 合并 option 时保留用户缩放，避免 60s 轮询把视野重置。
        },
      ],
      grid: [
        { left: 64, right: 78, top: 42, height: "50%" },
        { left: 64, right: 78, top: "72%", height: "18%" },
      ],
      xAxis: [
        {
          type: "category",
          gridIndex: 0,
          data: labels,
          boundaryGap: false,
          axisLine: { lineStyle: { color: theme.axisLine } },
          axisTick: { show: false },
          axisLabel: { show: false },
          axisPointer: { label: { show: false } },
        },
        {
          type: "category",
          gridIndex: 1,
          data: labels,
          boundaryGap: false,
          axisLine: { lineStyle: { color: theme.axisLine } },
          axisTick: { show: false },
          axisLabel: {
            color: theme.subtext,
            fontSize: 10,
            hideOverlap: true,
          },
          axisPointer: {
            label: {
              backgroundColor: theme.tooltipBg,
              borderColor: theme.tooltipBorder,
              color: theme.text,
              fontSize: 10,
            },
          },
        },
      ],
      yAxis: [
        {
          type: "value",
          gridIndex: 0,
          name: "标记价 (USDT)",
          position: "left",
          scale: true,
          nameTextStyle: { color: theme.subtext, fontSize: 11 },
          axisLabel: {
            color: theme.subtext,
            fontSize: 10,
            formatter: (value: number) => formatPriceAxis(value),
          },
          splitLine: {
            lineStyle: { color: theme.splitLine, type: "dashed" },
          },
        },
        {
          type: "value",
          gridIndex: 0,
          name: "OI 名义值 (USDT)",
          position: "right",
          scale: true,
          nameTextStyle: { color: theme.subtext, fontSize: 11 },
          axisLabel: {
            color: theme.subtext,
            fontSize: 10,
            formatter: (value: number) => formatNotionalAxis(value),
          },
          splitLine: { show: false },
        },
        {
          type: "value",
          gridIndex: 1,
          name: "多空比",
          position: "left",
          scale: true,
          nameTextStyle: { color: theme.subtext, fontSize: 11 },
          axisLabel: {
            color: theme.subtext,
            fontSize: 10,
            formatter: (value: number) => value.toFixed(1),
          },
          splitLine: {
            lineStyle: { color: theme.splitLine, type: "dashed" },
          },
        },
      ],
      series: [
        {
          name: "标记价",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: priceData,
          symbol: "none",
          smooth: true,
          connectNulls: false,
          lineStyle: { width: 2, color: priceColor },
          itemStyle: { color: priceColor },
          z: 2,
        },
        {
          name: "OI 名义值",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 1,
          data: oiData,
          symbol: "none",
          smooth: true,
          connectNulls: false,
          lineStyle: { width: 2, color: oiColor },
          itemStyle: { color: oiColor },
          z: 1,
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: withAlpha(oiColor, 0.28) },
                { offset: 1, color: withAlpha(oiColor, 0) },
              ],
            },
          },
        },
        {
          name: "多空比",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 2,
          data: ratioData,
          symbol: "none",
          smooth: true,
          connectNulls: false,
          lineStyle: { width: 2, color: ratioColor },
          itemStyle: { color: ratioColor },
        },
      ],
    };
  }, [points, spansMultipleDays, isDark, contractCode]);

  const hasValues = points.some(
    (point) =>
      point.mark_price != null
      || point.oi_notional != null
      || point.long_short_ratio != null,
  );

  return (
    <Card className="min-w-0 self-start border-border/60 bg-card/60 min-[1100px]:sticky min-[1100px]:top-20">
      <CardHeader className="border-b border-border/60 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                aria-hidden="true"
              />
              <CardTitle className="truncate text-base">
                {contract.base_asset}
                <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">
                  {contract.contract_code}
                </span>
              </CardTitle>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {windowMeta.desc} · 5 分钟快照（历史为 1 小时补采） · 上海时间
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {SERIES_WINDOWS.map((item) => (
              <button
                key={item.hours}
                type="button"
                onClick={() => setHours(item.hours)}
                className={cn(
                  "rounded-md border px-2 py-1 font-mono text-[11px] tabular-nums transition-colors",
                  hours === item.hours
                    ? "border-foreground bg-foreground text-background"
                    : "border-border text-muted-foreground hover:bg-muted",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
          <div>
            <div className="text-muted-foreground">标记价</div>
            <div className="mt-0.5 font-mono text-sm tabular-nums">
              {formatPrice(contract.mark_price)}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">OI 名义值</div>
            <div className="mt-0.5 font-mono text-sm tabular-nums">
              {formatThousands(contract.oi_notional)}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">多空比</div>
            <div
              className={cn(
                "mt-0.5 font-mono text-sm tabular-nums",
                longShortTone(contract.long_short_ratio),
              )}
            >
              {formatRatio(contract.long_short_ratio, 3)}
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-2 sm:p-4">
        {state.status === "loading" && !hasValues ? (
          <ChartSkeleton />
        ) : state.status === "error" && !hasValues ? (
          <div className="flex h-[440px] flex-col items-center justify-center gap-2 px-6 text-center">
            <AlertTriangle
              className="h-7 w-7 text-destructive"
              aria-hidden="true"
            />
            <p className="text-sm font-medium">序列数据暂不可用</p>
            <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
              {state.error ?? "请稍后重试"}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRetryToken((token) => token + 1)}
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              重试
            </Button>
          </div>
        ) : !hasValues ? (
          <ChartEmpty />
        ) : (
          <>
            {state.status === "error" && state.error && (
              <div className="mb-2 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1.5 text-[11px] text-warning">
                刷新失败：{state.error}；继续展示上一次成功数据。
              </div>
            )}
            <p className="sr-only">
              {contract.contract_code} 最近 24 小时：
              {rangeSummary.price
                ? `标记价 ${formatPrice(rangeSummary.price[0])} 至 ${formatPrice(rangeSummary.price[1])} USDT，`
                : ""}
              {rangeSummary.oi
                ? `OI 名义值 ${formatThousands(rangeSummary.oi[0])} 至 ${formatThousands(rangeSummary.oi[1])}，`
                : ""}
              {rangeSummary.ratio
                ? `多空比 ${formatRatio(rangeSummary.ratio[0], 3)} 至 ${formatRatio(rangeSummary.ratio[1], 3)}。`
                : ""}
            </p>
            <div
              role="img"
              aria-label={`${contract.contract_code} 最近 24 小时标记价、OI 名义值与多空比走势`}
            >
              <EChart option={chartOption} style={{ height: 440, width: "100%" }} />
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
              上图双轴：左轴标记价折线，右轴 OI 名义值面积图；下图为多空比。
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
