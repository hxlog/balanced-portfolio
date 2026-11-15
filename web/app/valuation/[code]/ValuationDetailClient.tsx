"use client";

/**
 * 指数详情（F9 级分析视图）。
 *
 * 自上而下的分析路径：
 *   1) 头部：名称/代码/类型/行业 + 收盘涨跌 + 数据日期 + 成分披露日
 *   2) 控制器：指标(PE/PB/股息率/ERP) x 统计口径(分位带/1-3σ) x 窗口(1/3/5/10 年/全历史)
 *      —— 下方所有图表与数据卡片都随控制器联动
 *   3) 左栏：估值 Band 图 -> 关键分位指标 -> 收益风险 -> 成分股（含披露日）
 *   4) 右栏：指数简介 -> 分位矩阵(4x5) -> 行业分布 -> 跟踪基金
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { mapValuationHistory } from "@/lib/valuation-detail-api-map";
import { formatNumber, formatPlainPct, formatSignedPct } from "@/lib/valuation-detail-format";
import type {
  DetailPercentile,
  DetailRiskStats,
  ValuationDetailData,
  ValuationHistoryData,
} from "@/lib/valuation-detail-types";
import type { HistoryPoint, PercentileStats, PercentileWindow, ValuationMetric } from "@/lib/valuation-types";
import { PercentileBar, percentileTone, SectionHeading } from "../_components/valuation-ui";
import { CompareFundsDialog, DetailStats } from "./DetailStats";
import { METRIC_LABEL, type BandMode, PeBandChart } from "../_components/revamp-charts";

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

function findPct(
  percentiles: DetailPercentile[],
  metric: ValuationMetric,
  window: PercentileWindow,
): DetailPercentile | null {
  return (
    percentiles.find((item) => item.metric === metric && item.window_key === window) ?? null
  );
}

function toChartStats(row: DetailPercentile | null, metric: ValuationMetric, window: PercentileWindow): PercentileStats | null {
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

const METRIC_UNIT: Record<ValuationMetric, string> = {
  pe_ttm: "x",
  pb: "x",
  dividend_yield_ttm: "%",
  erp: "%",
};

export function ValuationDetailClient({
  code,
  detail,
  history,
}: {
  code: string;
  detail: ValuationDetailData | null;
  history: ValuationHistoryData | null;
}) {
  const [metric, setMetric] = useState<ValuationMetric>("pe_ttm");
  const [window, setWindow] = useState<PercentileWindow>("5y");
  const [mode, setMode] = useState<BandMode>("pct");
  const [sigma, setSigma] = useState(1);
  const [historyData, setHistoryData] = useState<ValuationHistoryData | null>(history);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (metric === "pe_ttm" && window === "5y" && historyData) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    fetch(
      "/api/valuation/" + encodeURIComponent(code) + "/history?metric=" + metric + "&window=" + window,
      { signal: controller.signal },
    )
      .then((response) => response.json())
      .then((payload) => {
        if (!active) return;
        setHistoryData(mapValuationHistory(payload.data ?? {}));
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [code, metric, window]); // eslint-disable-line react-hooks/exhaustive-deps

  const stats = findPct(detail?.percentiles ?? [], metric, window);
  const series: HistoryPoint[] = useMemo(
    () => (historyData?.series ?? []).map((point) => ({ trade_date: point.trade_date, value: point.value })),
    [historyData],
  );
  const chartStats = toChartStats(stats, metric, window);
  const unit = METRIC_UNIT[metric];

  const disclosure = detail?.constituents[0]?.effective_date ?? null;
  const funds = detail?.tracker_funds ?? [];
  const totalAum = funds.reduce((sum, fund) => sum + (fund.fund_scale ?? fund.aum ?? 0), 0);
  const constituents = detail?.constituents ?? [];
  const cr10 = constituents.slice(0, 10).reduce((sum, item) => sum + (item.weight ?? 0), 0);

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

  if (!detail) {
    return (
      <div className="mx-auto flex min-h-[60vh] w-full max-w-3xl flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="size-8 text-warning" />
        <h1 className="text-lg font-semibold">未能加载指数 {code} 的估值数据</h1>
        <p className="text-sm text-muted-foreground">请稍后重试，或返回指数列表另选标的。</p>
        <Link href="/valuation" className="text-sm text-primary underline-offset-4 hover:underline">
          返回指数估值列表
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-6 sm:px-6 sm:pt-8 lg:px-8">
        <Link
          href="/valuation"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          指数估值
        </Link>

        {/* 头部 */}
        <header className="mt-2 flex flex-wrap items-end justify-between gap-4 border-b border-border pb-4">
          <div>
            <div className="flex flex-wrap items-baseline gap-3">
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{detail.name}</h1>
              <span className="font-mono text-sm text-muted-foreground">{detail.index_code}</span>
              <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                {detail.index_type}
              </span>
              {detail.industry ? (
                <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  {detail.industry}
                </span>
              ) : null}
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>估值日期 {detail.trade_date ?? "—"}</span>
              <span>·</span>
              <span>成分披露 {disclosure ?? "—"}</span>
              <span>·</span>
              <span>跟踪基金 {funds.length} 只</span>
              <span>·</span>
              <span>数据源 平安 / 中证官网</span>
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

        {/* 控制器 */}
        <div className="sticky top-0 z-20 -mx-4 mt-3 border-b border-border/60 bg-background/95 px-4 py-2.5 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="inline-flex overflow-hidden rounded-lg border border-border text-xs">
              {METRICS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setMetric(item.value)}
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
                  onClick={() => setWindow(item.value)}
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
            {loading ? <span className="text-[11px] text-muted-foreground">加载中…</span> : null}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          {/* 左栏 */}
          <div className="space-y-4 xl:col-span-2">
            <section className="rounded-xl border border-border bg-card p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 className="text-sm font-medium">
                    {METRIC_LABEL[metric]} · {WINDOW_LABEL[window]}估值带
                  </h2>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {mode === "pct"
                      ? "虚线为 P20 / P50 / P80 分位带"
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
                    均值 {stats?.mean == null ? "—" : formatNumber(stats.mean, 2) + unit}
                  </div>
                </div>
              </div>
              {series.length > 0 ? (
                <div className="mt-2">
                  <PeBandChart
                    key={metric + window + mode + sigma}
                    series={series}
                    stats={chartStats}
                    metric={metric}
                    mode={mode}
                    sigma={sigma}
                    frequency="周线"
                  />
                </div>
              ) : (
                <div className="mt-6 rounded-lg border border-dashed border-border p-8 text-center text-xs text-muted-foreground">
                  该指标暂无历史序列
                </div>
              )}
            </section>

            {/* 描述统计（v3：日收益分布 + Beta/相关系数） */}
            <DetailStats indexCode={detail.index_code} />

            {/* 收益风险 */}
            <section className="rounded-xl border border-border bg-card p-4">
              <SectionHeading title="收益风险" hint="基于原始行情收盘计算（未扣无风险利率）" />
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
                    {(["1y", "3y", "5y", "all"] as const).map((key) => {
                      const statsRow = detail.risk?.[key];
                      if (!statsRow) return null;
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
            </section>

            {/* 成分股 */}
            <section className="rounded-xl border border-border bg-card p-4">
              <SectionHeading
                title="成分股"
                hint={disclosure ? "披露日 " + disclosure + " · 前 " + constituents.length + " 大权重" : "暂无成分数据"}
              />
              {constituents.length > 0 ? (
                <>
                  <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-muted-foreground">
                    <span>CR10 集中度 {cr10.toFixed(1)}%</span>
                    <span>权重合计 {constituents.reduce((sum, item) => sum + (item.weight ?? 0), 0).toFixed(1)}%</span>
                  </div>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full min-w-[640px] border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-border text-[11px] text-muted-foreground">
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
                            <td className="py-1.5 text-xs text-muted-foreground">{item.industry_l1 ?? "—"}</td>
                            <td className="py-1.5 text-right font-mono text-xs tabular-nums">
                              {item.weight == null ? "—" : item.weight.toFixed(2) + "%"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <p className="mt-3 text-xs text-muted-foreground">该指数暂无成分披露数据。</p>
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
                {detail.base_date ? <span className="rounded border border-border px-1.5 py-0.5">基日 {detail.base_date}</span> : null}
                {detail.base_point ? <span className="rounded border border-border px-1.5 py-0.5">基点 {formatNumber(detail.base_point, 0)}</span> : null}
                {detail.income_method ? <span className="rounded border border-border px-1.5 py-0.5">{detail.income_method}</span> : null}
                {detail.weight_method ? <span className="rounded border border-border px-1.5 py-0.5">加权：{detail.weight_method}</span> : null}
                {detail.publisher ? <span className="rounded border border-border px-1.5 py-0.5">{detail.publisher}</span> : null}
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
                                onClick={() => {
                                  setMetric(rowMetric.value);
                                  setWindow(rowWindow.value);
                                }}
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
                  <p className="text-xs text-muted-foreground">暂无行业分布数据。</p>
                )}
              </div>
            </section>


          </div>
        </div>

        <section className="rounded-xl border border-border bg-card p-4">
          <SectionHeading
            title="跟踪基金"
            hint={funds.length > 0 ? "规模合计 " + (totalAum / 1e8).toFixed(0) + " 亿" : "暂无跟踪基金"}
          />
          <div className="mt-2 flex justify-end">
            <CompareFundsDialog funds={funds} benchmark={detail?.index_code ?? "000300"} />
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">基金</th>
                  <th className="py-1.5 text-right font-medium">规模</th>
                  <th className="py-1.5 text-right font-medium">管理费</th>
                  <th className="py-1.5 text-right font-medium">托管费</th>
                  <th className="py-1.5 text-right font-medium">成立日期</th>
                  <th className="py-1.5 text-right font-medium">年化波动</th>
                  <th className="py-1.5 text-right font-medium">最大回撤</th>
                  <th className="py-1.5 text-right font-medium">跟踪误差</th>
                  <th className="py-1.5 text-right font-medium">信息比率</th>
                  <th className="py-1.5 text-right font-medium">近1月</th>
                  <th className="py-1.5 text-right font-medium">近3月</th>
                  <th className="py-1.5 text-right font-medium">近6月</th>
                  <th className="py-1.5 text-right font-medium">近1年</th>
                  <th className="py-1.5 text-right font-medium">近3年</th>
                  <th className="py-1.5 text-right font-medium">近5年</th>
                  <th className="py-1.5 text-right font-medium">今年以来</th>
                </tr>
              </thead>
              <tbody>
                {funds.slice(0, 8).map((fund) => {
                  const scale = fund.fund_scale ?? fund.aum;
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
                    <tr key={fund.fund_code} className="border-b border-border/50 last:border-0">
                      <td className="py-1.5">
                        <div className="truncate">
                          <span className="font-mono text-muted-foreground">{fund.fund_code}</span>{" "}
                          {fund.name}
                        </div>
                        <div className="truncate text-[10px] text-muted-foreground">
                          {[fund.company_name, fund.manager, fund.fund_type].filter(Boolean).join(" · ") || "—"}
                        </div>
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {scale == null ? "—" : (scale / 1e8).toFixed(2) + " 亿"}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {fund.management_fee == null ? "—" : fund.management_fee.toFixed(2) + "%"}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {fund.custody_fee == null ? "—" : fund.custody_fee.toFixed(2) + "%"}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                        {fund.established_date ?? "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {fund.ann_vol_1y == null ? "—" : fund.ann_vol_1y.toFixed(2) + "%"}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {fund.max_dd_1y == null ? "—" : fund.max_dd_1y.toFixed(2) + "%"}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {fund.tracking_error_1y == null ? "—" : fund.tracking_error_1y.toFixed(2) + "%"}
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
            {funds.length > 8 ? (
              <div className="mt-1 text-[11px] text-muted-foreground">另有 {funds.length - 8} 只未展示</div>
            ) : null}
          </div>
        </section>

        <p className="mt-6 text-[11px] leading-5 text-muted-foreground">
          数据口径：估值序列来自平安（周频，2021-11 起）；成分权重与披露日来自中证官网；行情来自东财/雪球。
          分位为当前值在所选窗口内的序位（0~100）；样本不足统一显示「—」。收益风险未扣无风险利率，仅供横向比较。
        </p>
      </div>
    </div>
  );
}
