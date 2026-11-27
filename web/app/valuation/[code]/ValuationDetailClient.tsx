"use client";

/**
 * 指数详情（F9 级分析视图，/valuation/[code]，含 HSI）。
 *
 * 自上而下的分析路径：
 *   1) 头部：名称/代码/类型/行业/市场 + 收盘涨跌 + 数据日期
 *   2) 4 个 MetricCard：PE / PB / 股息率 / 风险溢价（当前值 + 5 年分位）
 *   3) 控制器：指标 × 分位带/标准差 × 窗口 × 分位带底色开关
 *   4) 左栏：估值×点位双轴图（无点位数据回退估值带图）→ 描述统计 → 收益风险 → 成分股
 *   5) 右栏：指数简介 → 分位矩阵 → 行业分布 → 跟踪基金（规模合计/数据截至/更新于、
 *      Top10 规模图、TE>5% warning）
 *
 * 空态统一走 DataEmptyState（「数据建设中」），局部加载/错误态只影响对应卡片；
 * 不修改共享 UI 组件，沿用现网 border/bg-card/语义色。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, RotateCcw } from "lucide-react";
import { EChart } from "@/components/EChart";
import { getChartTheme } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";
import { mapValuationHistory } from "@/lib/valuation-detail-api-map";
import {
  EMPTY_DISPLAY,
  TE_WARNING_THRESHOLD_PCT,
  formatAumYi,
  formatNumber,
  formatPlainPct,
  formatSignedPct,
  formatTrackerMeta,
  formatUpdatedAtCompact,
  hasUsablePercentile,
  percentileUnavailableText,
  sortTrackerFunds,
  trackerFundAriaSort,
  trackerFundScale,
  trackerFundSortButtonLabel,
  trackingErrorClass,
  trackingErrorTone,
  type SortDirection,
  type TrackerFundSortKey,
} from "@/lib/valuation-detail-format";
import type {
  DetailPercentile,
  DetailRiskStats,
  DetailTrackerFund,
  ValuationDetailData,
  ValuationHistoryData,
} from "@/lib/valuation-detail-types";
import type {
  HistoryPoint,
  PercentileStats,
  PercentileWindow,
  ValuationMetric,
} from "@/lib/valuation-types";
import {
  buildValuationPriceOption,
  constituentPieSlices,
  type ConstituentPieSlice,
} from "@/lib/valuation-chart-model";
import { formatValue, METRIC_LABEL, type BandMode, PeBandChart } from "../_components/revamp-charts";
import {
  ChartSkeleton,
  DataEmptyState,
  MetricCard,
  PercentileBar,
  percentileTone,
  SectionHeading,
  sumAum,
} from "../_components/valuation-ui";
import { CompareFundsDialog, DetailStats } from "./DetailStats";

const METRICS: Array<{ value: ValuationMetric; label: string }> = [
  { value: "pe_ttm", label: "PE" },
  { value: "pb", label: "PB" },
  { value: "dividend_yield_ttm", label: "股息率" },
  { value: "erp", label: "风险溢价" },
];

const WINDOWS: Array<{ value: PercentileWindow; label: string }> = [
  { value: "1y", label: "1 年" },
  { value: "3y", label: "3 年" },
  { value: "5y", label: "5 年" },
  { value: "10y", label: "10 年" },
  { value: "all", label: "全历史" },
];

const WINDOW_LABEL: Record<string, string> = {
  "1y": "1 年",
  "3y": "3 年",
  "5y": "5 年",
  "10y": "10 年",
  all: "全历史",
};

const RISK_ROWS: Array<{ key: keyof DetailRiskStats; label: string; isPct: boolean }> = [
  { key: "annualized_return_pct", label: "年化收益", isPct: true },
  { key: "volatility_pct", label: "年化波动", isPct: true },
  { key: "max_drawdown_pct", label: "最大回撤", isPct: true },
  { key: "sharpe", label: "夏普（rf=0）", isPct: false },
  { key: "total_return_pct", label: "区间收益", isPct: true },
];

const METRIC_UNIT: Record<ValuationMetric, string> = {
  pe_ttm: "x",
  pb: "x",
  dividend_yield_ttm: "%",
  erp: "%",
};

function findPct(
  percentiles: DetailPercentile[],
  metric: ValuationMetric,
  window: PercentileWindow,
): DetailPercentile | null {
  return (
    percentiles.find((item) => item.metric === metric && item.window_key === window) ?? null
  );
}

function toChartStats(
  row: DetailPercentile | null,
  metric: ValuationMetric,
  window: PercentileWindow,
): PercentileStats | null {
  if (!row) return null;
  return {
    metric,
    window_key: window,
    pct: row.pct,
    mean: row.mean,
    sd: row.sd,
    p20: row.p20,
    p50: row.p50,
    p80: row.p80,
    min: row.min,
    max: row.max,
    sample_size: row.sample_size,
  };
}

interface FundBar {
  fund: DetailTrackerFund;
  aumYi: number;
}

/** Top10 跟踪基金规模条形图（沿用明细页图表样式与语义色）。 */
function buildFundAumOption(bars: readonly FundBar[], theme: ReturnType<typeof getChartTheme>) {
  return {
    animation: false,
    grid: { left: 4, right: 52, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 11 },
      valueFormatter: (value: unknown) =>
        typeof value === "number" && Number.isFinite(value)
          ? value.toFixed(2) + " 亿元"
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
      axisLabel: { color: theme.text, fontSize: 10, width: 108, overflow: "truncate" },
    },
    series: [
      {
        name: "规模",
        type: "bar",
        data: bars.map((bar) => bar.aumYi),
        barWidth: 9,
        itemStyle: { color: theme.palette[0], borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: "right",
          color: theme.subtext,
          fontSize: 9,
          formatter: (params: { value?: unknown }) =>
            typeof params.value === "number" ? params.value.toFixed(2) : EMPTY_DISPLAY,
        },
      },
    ],
  };
}


/** 成分股权重饼图（前 10 大 + 其他 / 全部已披露），沿用主题 palette 与现网图表风格。 */
function buildConstituentPieOption(
  slices: readonly ConstituentPieSlice[],
  theme: ReturnType<typeof getChartTheme>,
) {
  return {
    animation: false,
    tooltip: {
      trigger: "item",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (params: { name?: string; value?: number; percent?: number }) => {
        const name = params.name ?? "";
        const value = Number(params.value ?? 0);
        const percent = typeof params.percent === "number" ? params.percent.toFixed(1) : null;
        return name + " · " + value.toFixed(2) + "%" + (percent ? "（占已披露 " + percent + "%）" : "");
      },
    },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: theme.tooltipBg, borderWidth: 1 },
        emphasis: { scale: true, scaleSize: 4 },
        data: slices.map((slice, index) => ({
          name: slice.name,
          value: Number(slice.value.toFixed(4)),
          itemStyle: {
            color: slice.rest ? theme.subtext : theme.palette[index % theme.palette.length],
          },
        })),
      },
    ],
  };
}

/** 跟踪基金表可排序表头（升/降序切换；null 值排序时恒垫底，逻辑在 sortTrackerFunds）。 */
function FundSortHeader({
  label,
  columnKey,
  sort,
  onSort,
}: {
  label: string;
  columnKey: TrackerFundSortKey;
  sort: { key: TrackerFundSortKey; dir: SortDirection } | null;
  onSort: (key: TrackerFundSortKey) => void;
}) {
  const active = sort?.key === columnKey;
  return (
    <th
      className="py-1.5 text-right font-medium"
      aria-sort={trackerFundAriaSort(sort, columnKey)}
    >
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
        aria-label={trackerFundSortButtonLabel(label, sort, columnKey)}
      >
        {label}
        {active ? (
          sort!.dir === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />
        ) : (
          <ArrowUpDown className="size-3 opacity-40" />
        )}
      </button>
    </th>
  );
}

export function ValuationDetailClient({
  code,
  detail,
  history,
}: {
  code: string;
  detail: ValuationDetailData | null;
  history: ValuationHistoryData | null;
}) {
  const { resolvedTheme } = useTheme();
  const theme = getChartTheme(resolvedTheme === "dark");
  const [metric, setMetric] = useState<ValuationMetric>("pe_ttm");
  const [window, setWindow] = useState<PercentileWindow>("5y");
  const [mode, setMode] = useState<BandMode>("pct");
  const [sigma, setSigma] = useState(1);
  const [showBandArea, setShowBandArea] = useState(true);
  /** 成分饼图：默认隐藏非前 10 大权重股（其余聚合成「其他」）。 */
  const [hideNonTop10, setHideNonTop10] = useState(true);
  /** 跟踪基金表前端排序；null = 后端返回顺序（按规模降序）。 */
  const [fundSort, setFundSort] = useState<{
    key: TrackerFundSortKey;
    dir: SortDirection;
  } | null>(null);

  // 历史序列缓存：{ key: `${code}:${metric}:${window}`, data }。渲染前必须校验 key 与当前
  // 指标/窗口一致，否则切换瞬间会把旧指标的序列当成新指标画（错标/错轴/闪错）。
  const INITIAL_HISTORY_KEY = code + ":pe_ttm:5y";
  const historyCacheRef = useRef<Map<string, ValuationHistoryData>>(new Map());
  if (history && !historyCacheRef.current.has(INITIAL_HISTORY_KEY)) {
    historyCacheRef.current.set(INITIAL_HISTORY_KEY, history);
  }
  const [historyVersion, setHistoryVersion] = useState(0);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  // key 含指数代码：客户端在 /valuation/[code] 之间切换时缓存不会串号。
  const currentHistoryKey = code + ":" + metric + ":" + window;

  useEffect(() => {
    // 命中缓存直接渲染；未命中才请求。请求失败只把错误记在当前 key 上（不污染其它组合）。
    if (historyCacheRef.current.has(currentHistoryKey)) return;
    const controller = new AbortController();
    // 15s 超时：网络挂起时也要落错误态（超时是 TimeoutError，不会被当作切换取消吞掉）。
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)]);
    let active = true;
    setLoadingKey(currentHistoryKey);
    setErrorKey((previous) => (previous === currentHistoryKey ? null : previous));
    fetch(
      "/api/valuation/" + encodeURIComponent(code) + "/history?metric=" + metric + "&window=" + window,
      { signal },
    )
      .then((response) => {
        if (!response.ok) throw new Error("history " + response.status);
        return response.json();
      })
      .then((payload) => {
        if (!active) return;
        historyCacheRef.current.set(currentHistoryKey, mapValuationHistory(payload.data ?? {}));
        setHistoryVersion((version) => version + 1);
      })
      .catch((error) => {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setErrorKey(currentHistoryKey);
      })
      .finally(() => {
        if (active) setLoadingKey((key) => (key === currentHistoryKey ? null : key));
      });
    return () => {
      active = false;
      controller.abort();
    };
    // metric/window 已由 currentHistoryKey 覆盖；retryTick 用于错误态重试。
  }, [code, currentHistoryKey, metric, window, retryTick]);

  const historyData = useMemo(
    () => historyCacheRef.current.get(currentHistoryKey) ?? null,
    // historyVersion 让 Map 写入后重新读取，避免缓存命中但界面不更新。
    [currentHistoryKey, historyVersion],
  );
  const historyError = errorKey === currentHistoryKey ? "历史序列加载失败，请重试" : null;
  // 无缓存且无错误 = 请求尚未返回（含 effect 还没跑的第一帧），一律骨架；
  // 有错误且无缓存才进错误态，避免切换瞬间闪一帧旧错误/空态。
  const historyLoading =
    !historyData && (loadingKey === currentHistoryKey || !historyError);

  const retryHistory = () => {
    historyCacheRef.current.delete(currentHistoryKey);
    setHistoryVersion((version) => version + 1);
    setErrorKey((previous) => (previous === currentHistoryKey ? null : previous));
    setLoadingKey(currentHistoryKey);
    setRetryTick((tick) => tick + 1);
  };

  /** 切换前预置目标 key 的 loading/清错，保证渲染首帧就是骨架而不是旧 key 的错误/空态。 */
  const prepareHistoryKey = (nextMetric: ValuationMetric, nextWindow: PercentileWindow) => {
    const key = code + ":" + nextMetric + ":" + nextWindow;
    if (historyCacheRef.current.has(key)) return;
    setErrorKey((previous) => (previous === key ? null : previous));
    setLoadingKey(key);
  };
  const selectMetric = (next: ValuationMetric) => {
    if (next === metric) return;
    prepareHistoryKey(next, window);
    setMetric(next);
  };
  const selectWindow = (next: PercentileWindow) => {
    if (next === window) return;
    prepareHistoryKey(metric, next);
    setWindow(next);
  };
  const selectMetricWindow = (nextMetric: ValuationMetric, nextWindow: PercentileWindow) => {
    if (nextMetric === metric && nextWindow === window) return;
    prepareHistoryKey(nextMetric, nextWindow);
    setMetric(nextMetric);
    setWindow(nextWindow);
  };

  const stats = findPct(detail?.percentiles ?? [], metric, window);
  const series: HistoryPoint[] = useMemo(
    () => (historyData?.series ?? []).map((point) => ({ trade_date: point.trade_date, value: point.value })),
    [historyData],
  );
  const chartStats = toChartStats(stats, metric, window);
  const unit = METRIC_UNIT[metric];

  const disclosure = detail?.constituents[0]?.effective_date ?? null;
  const funds = detail?.tracker_funds ?? [];
  const totalAum = detail ? sumAum(funds) : null;
  const constituents = detail?.constituents ?? [];
  const cr10 = constituents.slice(0, 10).reduce((sum, item) => sum + (item.weight ?? 0), 0);
  const disclosedWeight = constituents.reduce((sum, item) => sum + (item.weight ?? 0), 0);
  const pieSlices = useMemo(
    () => constituentPieSlices(constituents, hideNonTop10),
    [constituents, hideNonTop10],
  );
  const pieOption = useMemo(() => buildConstituentPieOption(pieSlices, theme), [pieSlices, theme]);
  const trackerMeta = detail
    ? formatTrackerMeta({
        totalAum,
        asOf: detail.tracker_funds_as_of,
        updatedAt: detail.tracker_funds_updated_at,
      })
    : "";

  const fundBars = useMemo<FundBar[]>(
    () =>
      funds
        .map((fund) => ({ fund, scale: trackerFundScale(fund) }))
        .filter(
          (row): row is { fund: DetailTrackerFund; scale: number } =>
            row.scale != null && row.scale > 0,
        )
        .map((row) => ({ fund: row.fund, aumYi: row.scale / 1e8 }))
        .sort((a, b) => b.aumYi - a.aumYi)
        .slice(0, 10),
    [funds],
  );
  const fundOption = useMemo(() => buildFundAumOption(fundBars, theme), [fundBars, theme]);
  const sortedFunds = useMemo(
    () => (fundSort ? sortTrackerFunds(funds, fundSort.key, fundSort.dir) : funds),
    [funds, fundSort],
  );
  const toggleFundSort = (key: TrackerFundSortKey) => {
    setFundSort((current) =>
      current?.key === key
        ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "desc" },
    );
  };

  const priceOption = useMemo(() => {
    if (!detail || detail.price_series.length === 0 || series.length === 0) return null;
    return buildValuationPriceOption({
      series,
      priceSeries: detail.price_series,
      stats: chartStats,
      metricLabel: METRIC_LABEL[metric],
      unit,
      mode,
      sigma,
      showBandArea,
      theme,
    });
  }, [detail, series, chartStats, metric, unit, mode, sigma, showBandArea, theme]);

  const industryWeights = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of constituents) {
      const key = item.industry_l1 ?? "未分类";
      map.set(key, (map.get(key) ?? 0) + (item.weight ?? 0));
    }
    const total = [...map.values()].reduce((sum, value) => sum + value, 0) || 1;
    return [...map.entries()]
      .map(([industry, weight]) => ({ industry, weight, ratio: (weight / total) * 100 }))
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 8);
  }, [constituents]);

  const metricCards = useMemo(() => {
    if (!detail) return [];
    const definitions: Array<{ metric: ValuationMetric; label: string; value: number | null; unit: string }> = [
      { metric: "pe_ttm", label: "PE (TTM)", value: detail.pe_ttm, unit: "x" },
      { metric: "pb", label: "PB", value: detail.pb, unit: "x" },
      { metric: "dividend_yield_ttm", label: "股息率 (TTM)", value: detail.dividend_yield_ttm, unit: "%" },
      { metric: "erp", label: "风险溢价", value: detail.erp, unit: "%" },
    ];
    return definitions.map((definition) => {
      const row = findPct(detail.percentiles, definition.metric, "5y");
      return { ...definition, row };
    });
  }, [detail]);

  if (!detail) {
    return (
      <div className="mx-auto mt-10 flex min-h-[50vh] w-full max-w-3xl flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle className="size-8 text-warning" />
        <h1 className="text-lg font-semibold">未能加载指数 {code} 的估值数据</h1>
        <p className="text-sm text-muted-foreground">
          接口暂不可用或该指数暂无数据；请稍后重试，或返回指数列表另选标的。
        </p>
        <Link href="/valuation" className="text-sm text-primary underline-offset-4 hover:underline">
          返回指数估值列表
        </Link>
      </div>
    );
  }

  const riskRows = (["1y", "3y", "5y", "all"] as const).filter((key) => detail.risk[key]);

  return (
    <>
      {/* 头部 */}
        <header className="mt-2 flex flex-wrap items-end justify-between gap-4 border-b border-border pb-3">
          <div>
            <div className="flex flex-wrap items-baseline gap-3">
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{detail.name}</h1>
              <span className="font-mono text-sm text-muted-foreground">{detail.index_code}</span>
              <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                {detail.index_type}
              </span>
              {detail.market ? (
                <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  {detail.market}
                </span>
              ) : null}
              {detail.industry ? (
                <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  {detail.industry}
                </span>
              ) : null}
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span>估值日期 {detail.trade_date ?? "—"}</span>
              <span>·</span>
              <span>成分 {constituents.length > 0 ? constituents.length + " 只" : "数据建设中"}</span>
              <span>·</span>
              <span>跟踪基金 {funds.length} 只</span>
              {disclosure ? (
                <>
                  <span>·</span>
                  <span>成分披露 {disclosure}</span>
                </>
              ) : null}
            </p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold tracking-tight tabular-nums">
              {detail.close == null ? "—" : formatNumber(detail.close, 2)}
            </div>
            <div
              className={cn(
                "text-xs tabular-nums",
                detail.change_pct == null
                  ? "text-muted-foreground"
                  : detail.change_pct >= 0
                    ? "text-up"
                    : "text-down",
              )}
            >
              {formatSignedPct(detail.change_pct)}
            </div>
          </div>
        </header>

        {/* 4 个核心指标卡：当前值 + 5 年分位 */}
        <section className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {metricCards.map((card) => {
            const row = card.row;
            const usable = hasUsablePercentile(row);
            const pct = usable && row?.pct != null ? row.pct : null;
            const value =
              card.value == null
                ? EMPTY_DISPLAY
                : card.unit === "%"
                  ? formatPlainPct(card.value)
                  : formatNumber(card.value, 2);
            return (
              <MetricCard
                key={card.metric}
                label={card.label + " · 5 年分位"}
                value={value}
                hint={
                  <span className={percentileTone(pct)}>
                    {pct != null ? "分位 " + pct.toFixed(1) + "%" : percentileUnavailableText(row)}
                    {" · 中位 "}
                    {row?.p50 == null
                      ? "—"
                      : card.unit === "%"
                        ? formatPlainPct(row.p50)
                        : formatNumber(row.p50, 2)}
                  </span>
                }
                percentile={pct}
              />
            );
          })}
        </section>

        {/* 控制器 */}
        <div className="sticky top-0 z-20 -mx-4 mt-3 border-b border-border/60 bg-background/95 px-4 py-2.5 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="inline-flex overflow-hidden rounded-lg border border-border text-xs">
              {METRICS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => selectMetric(item.value)}
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
              <button
                type="button"
                onClick={() => setMode("pct")}
                className={cn(
                  "px-3 py-1.5",
                  mode === "pct" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted",
                )}
              >
                分位带
              </button>
              <button
                type="button"
                onClick={() => setMode("sd")}
                className={cn(
                  "px-3 py-1.5",
                  mode === "sd" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted",
                )}
              >
                标准差
              </button>
            </div>
            {mode === "sd" ? (
              <div className="inline-flex overflow-hidden rounded-lg border border-border text-xs">
                {[1, 2, 3].map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSigma(value)}
                    className={cn(
                      "px-2.5 py-1.5",
                      sigma === value
                        ? "bg-foreground text-background"
                        : "text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {value}σ
                  </button>
                ))}
              </div>
            ) : null}
            <div className="inline-flex overflow-hidden rounded-lg border border-border text-xs">
              {WINDOWS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => selectWindow(item.value)}
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
            <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                checked={showBandArea}
                onChange={(event) => setShowBandArea(event.target.checked)}
                className="size-3.5 rounded border-border"
              />
              分位带底色
            </label>
            {historyLoading ? (
              <span className="text-[11px] text-muted-foreground">加载中…</span>
            ) : null}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          {/* 左栏 */}
          <div className="space-y-4 xl:col-span-2">
            <section className="rounded-xl border border-border bg-card p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 className="text-sm font-medium">
                    {METRIC_LABEL[metric]} · {WINDOW_LABEL[window]}
                    {detail.price_series.length > 0 ? "估值与点位" : "估值带"}
                  </h2>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {mode === "pct"
                      ? "虚线为 P20 / P50 / P80（机会/中位/危险）"
                      : "虚线为均值 ±" + sigma + "σ"}
                    ；样本 {stats?.sample_size ?? 0} 点
                  </p>
                </div>
                <div className="text-right">
                  <div className="text-lg font-semibold tabular-nums">
                    {stats?.pct == null ? "—" : stats.pct.toFixed(1) + "%"}
                    <span className="ml-1 text-[11px] font-normal text-muted-foreground">分位</span>
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    均值 {stats?.mean == null ? "—" : formatValue(stats.mean, metric)}
                  </div>
                </div>
              </div>
              <div className="mt-2">
                {historyLoading ? (
                  <ChartSkeleton height={300} label="估值序列加载中" />
                ) : historyError && series.length === 0 ? (
                  <div className="flex h-[300px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-xs text-muted-foreground">
                    <span>{historyError}</span>
                    <button
                      type="button"
                      onClick={retryHistory}
                      className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-muted"
                    >
                      <RotateCcw className="size-3" />
                      重试
                    </button>
                  </div>
                ) : series.length === 0 ? (
                  <div className="flex h-[300px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-xs text-muted-foreground">
                    <span>该指标暂无历史序列</span>
                    <button
                      type="button"
                      onClick={retryHistory}
                      className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-muted"
                    >
                      <RotateCcw className="size-3" />
                      重试
                    </button>
                  </div>
                ) : priceOption ? (
                  <EChart option={priceOption} style={{ height: 300, width: "100%" }} />
                ) : (
                  <PeBandChart
                    key={metric + window + mode + sigma}
                    series={series}
                    stats={chartStats}
                    metric={metric}
                    mode={mode}
                    sigma={sigma}
                    frequency="周线"
                  />
                )}
                {historyError && series.length > 0 ? (
                  <p className="mt-1 text-[10px] text-warning">{historyError}（展示上次加载结果）</p>
                ) : null}
              </div>
            </section>

            {/* 描述统计（v3：日收益分布 + Beta/相关系数） */}
            <DetailStats indexCode={detail.index_code} />

            {/* 收益风险 */}
            <section className="rounded-xl border border-border bg-card p-4">
              <SectionHeading title="收益风险" hint="基于原始行情收盘计算（未扣无风险利率）" />
              {riskRows.length > 0 ? (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[520px] border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-border text-[11px] text-muted-foreground">
                        <th className="py-2 text-left font-medium">区间</th>
                        {RISK_ROWS.map((row) => (
                          <th key={row.key} className="py-2 text-right font-medium">
                            {row.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {riskRows.map((key) => {
                        const statsRow = detail.risk[key]!;
                        return (
                          <tr key={key} className="border-b border-border/50 last:border-0">
                            <td className="py-2 text-xs text-muted-foreground">{WINDOW_LABEL[key]}</td>
                            {RISK_ROWS.map((row) => {
                              const value = statsRow[row.key];
                              return (
                                <td
                                  key={row.key}
                                  className={cn(
                                    "py-2 text-right font-mono text-xs tabular-nums",
                                    row.key === "annualized_return_pct" && typeof value === "number"
                                      ? value >= 0
                                        ? "text-up"
                                        : "text-down"
                                      : "",
                                  )}
                                >
                                  {value == null
                                    ? "—"
                                    : row.isPct
                                      ? formatPlainPct(value)
                                      : formatNumber(value, 2)}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <DataEmptyState
                  className="mt-2"
                  title="收益风险数据建设中"
                  description="后端尚未落库该指数的区间收益/波动/回撤统计。"
                />
              )}
            </section>

            {/* 成分股 */}
            <section className="rounded-xl border border-border bg-card p-4">
              <SectionHeading
                title="成分股"
                hint={disclosure ? "披露日 " + disclosure + " · 前 " + constituents.length + " 大权重" : "暂无成分数据"}
              />
              {constituents.length > 0 ? (
                <>
                  <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <div className="flex flex-wrap gap-4">
                      <span>CR10 集中度 {cr10.toFixed(1)}%</span>
                      <span>权重合计 {disclosedWeight.toFixed(1)}%</span>
                    </div>
                    {/* 2026-11-27 第二轮反馈：默认隐藏非前 10 大权重股（其余 = 其他权重聚合片）。 */}
                    <button
                      type="button"
                      onClick={() => setHideNonTop10((value) => !value)}
                      aria-pressed={hideNonTop10}
                      className={cn(
                        "h-7 rounded-md border px-2 text-[11px] transition-colors",
                        hideNonTop10
                          ? "border-foreground bg-foreground text-background"
                          : "border-border text-muted-foreground hover:bg-muted",
                      )}
                    >
                      隐藏非前10大权重股
                    </button>
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-3 lg:grid-cols-[260px_minmax(0,1fr)]">
                    <div className="rounded-lg border border-border/60 px-2 pb-1 pt-2">
                      <div className="px-1 text-[10px] text-muted-foreground">
                        {hideNonTop10 ? "前 10 大权重 + 其他（%）" : "全部已披露成分权重（%）"}
                      </div>
                      <EChart option={pieOption} style={{ height: 220, width: "100%" }} />
                    </div>
                    <div className="max-h-[360px] overflow-auto">
                    <table className="w-full min-w-[640px] border-collapse text-sm">
                      <thead className="sticky top-0 z-10">
                        <tr className="border-b border-border bg-card text-[11px] text-muted-foreground">
                          <th className="py-2 text-right font-medium">排名</th>
                          <th className="py-2 text-left font-medium">代码</th>
                          <th className="py-2 text-left font-medium">名称</th>
                          <th className="py-2 text-left font-medium">行业</th>
                          <th className="py-2 text-right font-medium">权重</th>
                        </tr>
                      </thead>
                      <tbody>
                        {constituents.map((item) => (
                          <tr key={item.stock_code} className="border-b border-border/50 last:border-0">
                            <td className="py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                              {item.rank ?? "—"}
                            </td>
                            <td className="py-1.5 font-mono text-xs">{item.stock_code}</td>
                            <td className="py-1.5 text-xs">{item.name}</td>
                            <td className="py-1.5 text-xs text-muted-foreground">
                              {item.industry_l1?.trim() ? item.industry_l1 : EMPTY_DISPLAY}
                            </td>
                            <td className="py-1.5 text-right font-mono text-xs tabular-nums">
                              {item.weight == null ? "—" : item.weight.toFixed(2) + "%"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    </div>
                  </div>
                </>
              ) : (
                <DataEmptyState
                  className="mt-2"
                  title="成分股数据建设中"
                  description="港股成分权重数据正在接入；当前不影响估值指标与跟踪基金模块使用。"
                />
              )}
            </section>
          </div>

          {/* 右栏 */}
          <div className="space-y-4">
            <section className="rounded-xl border border-border bg-card p-4">
              <h2 className="text-sm font-medium">指数简介</h2>
              <p className="mt-2 text-[13px] leading-6 text-muted-foreground">
                {detail.intro ?? "暂无简介数据。"}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
                {detail.base_date ? (
                  <span className="rounded border border-border px-1.5 py-0.5">基日 {detail.base_date}</span>
                ) : null}
                {detail.base_point ? (
                  <span className="rounded border border-border px-1.5 py-0.5">
                    基点 {formatNumber(detail.base_point, 0)}
                  </span>
                ) : null}
                {detail.income_method ? (
                  <span className="rounded border border-border px-1.5 py-0.5">{detail.income_method}</span>
                ) : null}
                {detail.weight_method ? (
                  <span className="rounded border border-border px-1.5 py-0.5">加权：{detail.weight_method}</span>
                ) : null}
                {detail.publisher ? (
                  <span className="rounded border border-border px-1.5 py-0.5">{detail.publisher}</span>
                ) : null}
              </div>
            </section>

            <section className="rounded-xl border border-border bg-card p-4">
              <SectionHeading title="分位矩阵" hint="点击单元格切换上方指标与窗口" />
              <div className="mt-2 overflow-x-auto">
                <table className="w-full border-collapse text-[11px]">
                  <thead>
                    <tr>
                      <th className="py-1.5 text-left font-medium text-muted-foreground">指标</th>
                      {WINDOWS.map((item) => (
                        <th key={item.value} className="py-1.5 text-right font-medium text-muted-foreground">
                          {item.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {METRICS.map((rowMetric) => (
                      <tr key={rowMetric.value}>
                        <td className="py-1 text-muted-foreground">{rowMetric.label}</td>
                        {WINDOWS.map((rowWindow) => {
                          const cell = findPct(detail.percentiles, rowMetric.value, rowWindow.value);
                          const active = rowMetric.value === metric && rowWindow.value === window;
                          return (
                            <td key={rowWindow.value} className="py-1 text-right">
                              <button
                                type="button"
                                onClick={() =>
                                  selectMetricWindow(rowMetric.value, rowWindow.value)
                                }
                                className={cn(
                                  "w-12 rounded px-1 py-0.5 font-mono tabular-nums transition-colors",
                                  active ? "bg-foreground text-background" : percentileTone(cell?.pct ?? null),
                                  !active && "hover:bg-muted",
                                )}
                              >
                                {cell?.pct == null ? "—" : cell.pct.toFixed(0) + "%"}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="rounded-xl border border-border bg-card p-4">
              <SectionHeading title="行业分布" hint="按最新成分权重聚合" />
              <div className="mt-2 space-y-1.5">
                {industryWeights.length > 0 ? (
                  industryWeights.map((item) => (
                    <div key={item.industry} className="flex items-center gap-2 text-[11px]">
                      <span className="w-16 truncate text-muted-foreground">{item.industry}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary" style={{ width: item.ratio + "%" }} />
                      </div>
                      <span className="w-10 text-right font-mono tabular-nums">{item.weight.toFixed(1)}%</span>
                    </div>
                  ))
                ) : (
                  <DataEmptyState
                    title="行业权重数据建设中"
                    description="成分权重就绪后此处展示前 8 大行业分布。"
                  />
                )}
              </div>
            </section>
          </div>
        </div>

        {/* 跟踪基金 */}
        <section className="mt-4 rounded-xl border border-border bg-card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-sm font-medium">跟踪基金</h2>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {funds.length > 0
                  ? "默认按最新规模排序 · 表头可升/降序排序（空值恒垫底）· Top10 规模条形图 + 明细表"
                  : "暂无跟踪基金数据"}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1.5">
              <p className="text-right text-[11px] tabular-nums text-muted-foreground">
                {funds.length > 0 ? trackerMeta : "规模合计 — · 数据截至 — · 更新于 —"}
              </p>
              <CompareFundsDialog funds={funds} benchmark={detail.index_code} />
            </div>
          </div>

          {funds.length === 0 ? (
            <DataEmptyState
              className="mt-3"
              title="跟踪基金数据建设中"
              description="接口暂未返回该指数的 ETF / 联接基金快照；数据就绪后自动展示规模、费率与跟踪误差。"
            />
          ) : (
            <>
              {fundBars.length > 0 ? (
                <div className="mt-3 rounded-lg border border-border/60 px-2 pb-1 pt-2">
                  <div className="px-1 text-[10px] text-muted-foreground">Top 10 规模（亿元）</div>
                  <EChart option={fundOption} style={{ height: 220, width: "100%" }} />
                </div>
              ) : null}
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse text-[11px]">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground">
                      <th className="py-1.5 text-left font-medium">基金</th>
                      <FundSortHeader label="规模" columnKey="scale" sort={fundSort} onSort={toggleFundSort} />
                      <FundSortHeader label="管理费" columnKey="management_fee" sort={fundSort} onSort={toggleFundSort} />
                      <FundSortHeader label="托管费" columnKey="custody_fee" sort={fundSort} onSort={toggleFundSort} />
                      <FundSortHeader label="年化波动" columnKey="ann_vol_1y" sort={fundSort} onSort={toggleFundSort} />
                      <th className="py-1.5 text-right font-medium">最大回撤</th>
                      <FundSortHeader label="跟踪误差" columnKey="tracking_error_1y" sort={fundSort} onSort={toggleFundSort} />
                      <th className="py-1.5 text-right font-medium">信息比率</th>
                      <th className="py-1.5 text-right font-medium">近1月</th>
                      <th className="py-1.5 text-right font-medium">近3月</th>
                      <th className="py-1.5 text-right font-medium">近6月</th>
                      <FundSortHeader label="近1年" columnKey="ret_12m" sort={fundSort} onSort={toggleFundSort} />
                      <th className="py-1.5 text-right font-medium">近3年</th>
                      <th className="py-1.5 text-right font-medium">近5年</th>
                      <th className="py-1.5 text-right font-medium">今年以来</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedFunds.slice(0, 8).map((fund) => {
                      const scale = trackerFundScale(fund);
                      const te = fund.tracking_error_1y;
                      const teTone = trackingErrorTone(te);
                      const returns: Array<{ key: string; value: number | null }> = [
                        { key: "1m", value: fund.ret_1m },
                        { key: "3m", value: fund.ret_3m },
                        { key: "6m", value: fund.ret_6m },
                        { key: "12m", value: fund.ret_12m },
                        { key: "3y", value: fund.ret_3y },
                        { key: "5y", value: fund.ret_5y },
                        { key: "ytd", value: fund.ytd },
                      ];
                      return (
                        <tr key={fund.fund_code} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                          <td className="py-1.5">
                            <div className="truncate">
                              <span className="font-mono text-muted-foreground">{fund.fund_code}</span>{" "}
                              {fund.name}
                            </div>
                            <div className="truncate text-[10px] text-muted-foreground">
                              {[fund.company_name, fund.manager, fund.fund_type].filter(Boolean).join(" · ") ||
                                "—"}
                            </div>
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {scale == null ? "—" : formatAumYi(scale) + " 亿"}
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {fund.management_fee == null ? "—" : fund.management_fee.toFixed(2) + "%"}
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {fund.custody_fee == null ? "—" : fund.custody_fee.toFixed(2) + "%"}
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {fund.ann_vol_1y == null ? "—" : fund.ann_vol_1y.toFixed(2) + "%"}
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {fund.max_dd_1y == null ? "—" : fund.max_dd_1y.toFixed(2) + "%"}
                          </td>
                          <td
                            className={cn("py-1.5 text-right font-mono tabular-nums", trackingErrorClass(te))}
                            title={
                              teTone === "warning"
                                ? "跟踪误差 " + te!.toFixed(2) + "% > " + TE_WARNING_THRESHOLD_PCT + "%，跟踪质量偏弱"
                                : undefined
                            }
                          >
                            {te == null ? (
                              "—"
                            ) : (
                              <span className="inline-flex items-center justify-end gap-1">
                                {teTone === "warning" ? <AlertTriangle className="size-3" aria-hidden="true" /> : null}
                                {te.toFixed(2)}%
                              </span>
                            )}
                          </td>
                          <td className="py-1.5 text-right font-mono tabular-nums">
                            {fund.info_ratio_1y == null ? "—" : fund.info_ratio_1y.toFixed(2)}
                          </td>
                          {returns.map((item) => (
                            <td
                              key={item.key}
                              className={cn(
                                "py-1.5 text-right font-mono tabular-nums",
                                item.value == null
                                  ? "text-muted-foreground"
                                  : item.value >= 0
                                    ? "text-up"
                                    : "text-down",
                              )}
                            >
                              {item.value == null ? "—" : item.value.toFixed(2) + "%"}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {funds.length > 8 ? (
                <div className="mt-1 text-[11px] text-muted-foreground">另有 {funds.length - 8} 只未展示</div>
              ) : null}
              {funds.some((fund) => trackingErrorTone(fund.tracking_error_1y) === "warning") ? (
                <p className="mt-2 text-[10px] text-warning">
                  · 标记 {TE_WARNING_THRESHOLD_PCT}% 以上跟踪误差的基金，跟踪质量偏弱，仅作风险提示。
                </p>
              ) : null}
            </>
          )}
        </section>

        <p className="mt-6 text-[11px] leading-5 text-muted-foreground">
          口径：估值来自平安 / 中证官网 PiT（PE-TTM 整体法），分位为当前值在所选窗口内的序位（0~100），
          样本不足统一显示「—」。基金净值优先累计净值（acc_nav），缺失回退 ETF 后复权；TE 为近 1 年滚动
          日收益差年化波动率；
          {detail.index_code === "HSI"
            ? "基准为恒生指数（价格指数）× 港币兑人民币（库内无全收益源，非全收益口径）。"
            : "基准口径以后端基金风险指标说明为准。"}
          基金数据截至 {detail.tracker_funds_as_of ?? "—"}，更新于{" "}
          {detail.tracker_funds_updated_at ? formatUpdatedAtCompact(detail.tracker_funds_updated_at) : "—"}。
          收益风险未扣无风险利率，仅供横向比较。
        </p>
    </>
  );
}
