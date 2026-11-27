"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, TrendingUp } from "lucide-react";
import { useTheme } from "next-themes";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChartSkeleton, TableSkeleton } from "@/components/ui/loading";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineErrorState } from "@/components/ui/error-state";
import { REVEAL_CLASS, revealStyle } from "@/components/ui/reveal";
import { EChart } from "@/components/EChart";
import { getChartTheme, withAlpha } from "@/lib/chart-theme";
import { fmtCorr, fmtCryptoAsOf, fmtPrice } from "@/lib/crypto-format";
import { cn } from "@/lib/utils";

import type {
  CryptoCorrelationResponse as CorrelationResponse,
  CryptoPairData as PairData,
  CryptoShiftedPrice as ShiftedPrice,
  CryptoSnapshot as Snapshot,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WINDOWS = [
  { value: "3M", label: "3 个月" },
  { value: "6M", label: "6 个月" },
  { value: "9M", label: "9 个月" },
  { value: "12M", label: "12 个月" },
] as const;

const METHODS = [
  { value: "pearson", label: "Pearson" },
  { value: "spearman", label: "Spearman" },
  { value: "kendall", label: "Kendall τ" },
  { value: "hoeffding", label: "Hoeffding D" },
] as const;

const LAG_OPTIONS = [
  { value: "3M", label: "3 个月" },
  { value: "6M", label: "6 个月" },
  { value: "9M", label: "9 个月" },
  { value: "12M", label: "12 个月" },
] as const;

const CHART1_DEFAULT_ACTIVE = new Set(["COMEX黄金", "纳斯达克100", "BTC 价格 (USD)"]);

// ---------------------------------------------------------------------------
// CryptoClient
// ---------------------------------------------------------------------------

export function CryptoClient({ data }: { data: CorrelationResponse | null }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const router = useRouter();

  // SSR 注入: page.tsx 经 getCachedCryptoCorrelation() (cacheTag "crypto") 预取后传入;
  // 后端读预计算表 (bp_crypto_corr_daily 等), 请求路径永不计算。无客户端 fetch。
  // 直接用 props 而非 useState 快照: router.refresh() 重取后可原地更新（错误重试场景）。
  const error = !data ? "预计算相关性数据暂不可用" : null;
  const [windowMonths, setWindowMonths] = useState("3M");
  const [corrMethod, setCorrMethod] = useState("pearson");
  const [lagHorizon, setLagHorizon] = useState("3M");

  // --- Theme colors ---
  const theme = getChartTheme(isDark);
  const cardBg = theme.tooltipBg;
  const fg = theme.text;
  const textCol = theme.subtext;
  const axisLineCol = theme.axisLine;
  const splitLineCol = theme.splitLine;
  // 主题只有单一 gold 槽: comex 用 gold, au0(沪金) 用同为琥珀色系的 crypto.btc 槽;
  // BTC 价格线保持 palette[0] 蓝 (与既有视觉一致, 避免与 au0 撞色)。
  const corrColors: Record<string, string> = {
    comex_gold: theme.crypto.gold,
    au0_gold: theme.crypto.btc,
    sp500: theme.crypto.sp500,
    nasdaq: theme.crypto.nasdaq,
  };

  const currentRolling = useMemo(() => {
    if (!data) return null;
    return data.rolling[windowMonths]?.[corrMethod] ?? null;
  }, [data, windowMonths, corrMethod]);

  const shiftedPrices = useMemo(() => {
    return data?.lagged_shifted?.[lagHorizon] ?? null;
  }, [data, lagHorizon]);

  const currentRSummary = useMemo(() => {
    if (!currentRolling) return {};
    const result: Record<string, number | null> = {};
    for (const [key, pair] of Object.entries(currentRolling)) {
      const valid = (pair.correlation ?? []).filter((v) => v != null);
      result[key] = valid.length > 0 ? valid[valid.length - 1] : null;
    }
    return result;
  }, [currentRolling]);

  // 相关性数据表：同一方法下，各资产对在 4 个窗口的最新相关系数（取最后一个非空值）
  const corrTable = useMemo(() => {
    if (!data) return [] as Array<{ key: string; label: string; values: Array<number | null> }>;
    const rows = new Map<string, { label: string; values: Array<number | null> }>();
    for (const win of WINDOWS) {
      const byMethod = data.rolling[win.value]?.[corrMethod] ?? {};
      for (const [key, pair] of Object.entries(byMethod)) {
        const entry = rows.get(key) ?? { label: pair.label, values: [null, null, null, null] };
        const valid = (pair.correlation ?? []).filter((v): v is number => v != null);
        const index = WINDOWS.findIndex((item) => item.value === win.value);
        if (index >= 0 && valid.length > 0) entry.values[index] = valid[valid.length - 1];
        rows.set(key, entry);
      }
    }
    return [...rows.entries()]
      .map(([key, entry]) => ({ key, ...entry }))
      .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
  }, [data, corrMethod]);

  // --- Chart 1: 滚动相关性 + BTC 价格 (双 Y 轴, NYSE 日历) ---
  const chart1Option = useMemo(() => {
    if (!data || !currentRolling) return {};
    const pairs = Object.entries(currentRolling);
    if (!pairs.length) return {};

    const dates = data.dates ?? [];
    if (!dates.length) return {};

    const series: any[] = [];
    const legendData: string[] = [];
    const legendSelected: Record<string, boolean> = {};
    const btcAreaColor = theme.palette[0];
    const btcFillColor = theme.fills.primaryFaint;

    // 相关性线 (左轴)
    for (const [key, pair] of pairs) {
      if (!pair.correlation?.length) continue;
      const color = corrColors[key] ?? theme.subtext;
      // dates 已全部对齐到 NYSE 日历, 直接用
      series.push({
        name: pair.label,
        type: "line", smooth: true, yAxisIndex: 0, symbol: "none",
        lineStyle: { width: 2, color },
        itemStyle: { color },
        data: pair.correlation,
      });
      legendData.push(pair.label);
      legendSelected[pair.label] = CHART1_DEFAULT_ACTIVE.has(pair.label);
    }

    // BTC 价格 (右轴, 面积图)
    const btcPrices = data.btc_prices;
    const btcName = "BTC 价格 (USD)";
    if (btcPrices?.some((p) => p != null)) {
      series.push({
        name: btcName, type: "line", smooth: true, yAxisIndex: 1, symbol: "none",
        lineStyle: { width: 1.5, color: btcAreaColor },
        itemStyle: { color: btcAreaColor },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: btcFillColor },
              { offset: 1, color: "rgba(255,255,255,0)" },
            ],
          },
        },
        data: btcPrices,
      });
      legendData.push(btcName);
      legendSelected[btcName] = true;
    }

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis", backgroundColor: cardBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: fg, fontSize: 12 },
        formatter: (params: any) => {
          if (!Array.isArray(params)) return "";
          let html = `<div style="font-size:11px;margin-bottom:4px">${params[0].axisValue}</div>`;
          for (const p of params) {
            const val = p.value;
            if (val == null) continue;
            const marker = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>`;
            if (p.seriesName.includes("BTC")) {
              html += `<div style="margin:2px 0">${marker}${p.seriesName}: <b>$${Number(val).toLocaleString()}</b></div>`;
            } else {
              html += `<div style="margin:2px 0">${marker}${p.seriesName}: <b>${Number(val).toFixed(4)}</b></div>`;
            }
          }
          return html;
        },
      },
      legend: {
        type: "scroll", bottom: 30,
        textStyle: { color: textCol, fontSize: 11 },
        data: legendData, selected: legendSelected,
      },
      dataZoom: [
        { type: "slider", bottom: 0, start: 55, end: 100, height: 22, textStyle: { color: textCol, fontSize: 10 } },
        { type: "inside" },
      ],
      grid: { left: 65, right: 75, top: 15, bottom: 75 },
      xAxis: {
        type: "category", boundaryGap: false, data: dates,
        axisLine: { lineStyle: { color: axisLineCol } },
        axisLabel: { color: textCol, fontSize: 10 },
      },
      yAxis: [
        {
          type: "value", name: "滚动相关系数", min: -1, max: 1,
          nameTextStyle: { color: textCol, fontSize: 11 },
          axisLabel: { color: textCol, fontSize: 10, formatter: (v: number) => v.toFixed(1) },
          splitLine: { lineStyle: { color: splitLineCol, type: "dashed" } },
        },
        {
          type: "value", name: "BTC 价格 (USD)",
          nameTextStyle: { color: textCol, fontSize: 11 },
          axisLabel: { color: textCol, fontSize: 10, formatter: (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)) },
          splitLine: { show: false },
        },
      ],
      series,
    };
  }, [currentRolling, isDark, cardBg, fg, textCol, axisLineCol, splitLineCol, corrColors]);

  // --- Chart 2: BTC vs DXY 滞后平移价格 (双 Y 轴, 自适应刻度) ---
  const chart2Option = useMemo(() => {
    if (!shiftedPrices || !shiftedPrices.dates.length) return {};

    const btcColor = theme.palette[0];
    const dxyColor = theme.crypto.dxy;

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis", backgroundColor: cardBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: fg, fontSize: 12 },
        formatter: (params: any) => {
          if (!Array.isArray(params)) return "";
          const date = params[0]?.axisValue ?? "";
          let html = `<div style="font-size:11px;margin-bottom:4px">${date}</div>`;
          for (const p of params) {
            const val = p.value;
            if (val == null) continue;
            const marker = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>`;
            const formatted = p.seriesName.includes("BTC") ? `$${Number(val).toLocaleString()}` : Number(val).toFixed(2);
            html += `<div style="margin:2px 0">${marker}${p.seriesName}: <b>${formatted}</b></div>`;
          }
          return html;
        },
      },
      legend: {
        bottom: 30,
        textStyle: { color: textCol, fontSize: 11 },
        data: ["BTC 价格 (USD)", `DXY (+${lagHorizon})`],
      },
      dataZoom: [
        { type: "slider", bottom: 0, start: 0, end: 100, height: 22, textStyle: { color: textCol, fontSize: 10 } },
        { type: "inside" },
      ],
      grid: { left: 70, right: 70, top: 15, bottom: 75 },
      xAxis: {
        type: "category", boundaryGap: false, data: shiftedPrices.dates,
        axisLine: { lineStyle: { color: axisLineCol } },
        axisLabel: { color: textCol, fontSize: 10 },
      },
      yAxis: [
        {
          type: "value", name: "BTC (USD)", scale: true,
          nameTextStyle: { color: btcColor, fontSize: 11 },
          axisLabel: { color: textCol, fontSize: 10, formatter: (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)) },
          splitLine: { lineStyle: { color: splitLineCol, type: "dashed" } },
        },
        {
          type: "value", name: "DXY", scale: true,
          nameTextStyle: { color: dxyColor, fontSize: 11 },
          axisLabel: { color: textCol, fontSize: 10, formatter: (v: number) => v.toFixed(1) },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "BTC 价格 (USD)", type: "line", smooth: true, yAxisIndex: 0, symbol: "none",
          lineStyle: { width: 2, color: btcColor },
          itemStyle: { color: btcColor },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: theme.fills.primaryFaint },
                { offset: 1, color: withAlpha(btcColor, 0) },
              ],
            },
          },
          data: shiftedPrices.btc,
        },
        {
          name: `DXY (+${lagHorizon})`, type: "line", smooth: true, yAxisIndex: 1, symbol: "none",
          lineStyle: { width: 2, color: dxyColor },
          itemStyle: { color: dxyColor },
          data: shiftedPrices.dxy,
        },
      ],
    };
  }, [shiftedPrices, lagHorizon, isDark, cardBg, fg, textCol, axisLineCol, splitLineCol]);

  // --- Render helpers ---
  const snap = data?.snapshot;
  const meta = data?.meta;
  // 标准化统一时间 (最近共同 NYSE 交易日 16:00 ET), 双 TZ 带时分;
  // 优先用后端预算好的 as_of_et / as_of_cn (确定性), 缺失则用 Intl 从 as_of 兜底（lib/crypto-format 与首页共用）。
  const { et: asOfEt, cn: asOfCn } = fmtCryptoAsOf(meta);
  const methodLabel = METHODS.find((m) => m.value === corrMethod)?.label ?? corrMethod;
  const windowLabel = WINDOWS.find((w) => w.value === windowMonths)?.label ?? windowMonths;

  return (
    <div className="space-y-6">
      {/* 工具条：数据截至 + 窗口/方法切换。
          H1 与页面说明统一由 app/crypto/page.tsx 提供，本组件不再渲染第二枚 H1。 */}
      <div className="flex flex-col gap-3 rounded-xl border border-border/60 bg-card/40 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {/* 两个时间戳拼起来比 375px 的行宽还长, 故本枚刻意允许折行:
              Badge 基类是 whitespace-nowrap(避免 CJK 标签在窄列里被逐字拆断)。 */}
          {asOfEt && asOfCn && (
            <Badge variant="outline" className="whitespace-normal text-xs font-normal text-muted-foreground">
              数据截至: {asOfEt} / {asOfCn}
            </Badge>
          )}
          {meta?.is_synced === false && meta?.effective_td && (
            <Badge variant="outline" className="border-warning/40 bg-warning/10 text-xs font-normal text-warning">
              数据待齐 · 展示至 {meta.effective_td}
            </Badge>
          )}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">滚动窗口:</span>
            <Tabs value={windowMonths} onValueChange={setWindowMonths}>
              <TabsList className="h-8">
                {WINDOWS.map((w) => (<TabsTrigger key={w.value} value={w.value} className="text-xs px-3 h-7">{w.label}</TabsTrigger>))}
              </TabsList>
            </Tabs>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">相关方法:</span>
            <Tabs value={corrMethod} onValueChange={setCorrMethod}>
              <TabsList className="h-8">
                {METHODS.map((m) => (<TabsTrigger key={m.value} value={m.value} className="text-xs px-3 h-7">{m.label}</TabsTrigger>))}
              </TabsList>
            </Tabs>
          </div>
        </div>
      </div>

      {error && (
        <InlineErrorState
          title="数据加载失败"
          message={`${error}。可以重试，若持续失败说明预计算表正在重算。`}
          onRetry={() => router.refresh()}
        />
      )}

      {/* Snapshot Cards */}
        <div className={cn("grid grid-cols-2 md:grid-cols-5 gap-4", REVEAL_CLASS)} style={revealStyle(0)}>
          {[
            { label: "BTC/USD", value: fmtPrice(snap?.btc ?? null) },
            { label: "DXY 美元指数", value: snap?.dxy?.toFixed(2) ?? "--" },
            { label: "COMEX 黄金", value: fmtPrice(snap?.comex_gold ?? null) },
            { label: "沪金 AU0", value: fmtPrice(snap?.au0_gold ?? null) },
            { label: `${windowLabel} × ${methodLabel}`, value: "" },
          ].map((item) => (
            <Card key={item.label} className="bg-card/50 border-border/50">
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground mb-1">{item.label}</div>
                <div className="text-xl font-bold tabular-nums">
                  {item.value || <span className="text-xs text-muted-foreground font-normal">{meta?.window_sizes?.[windowMonths]} 日窗口 · NYSE</span>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Correlation Summary Cards */}
        <div className={cn("grid grid-cols-2 md:grid-cols-4 gap-4", REVEAL_CLASS)} style={revealStyle(50)}>
          {currentRolling && Object.entries(currentRolling).map(([key, pair]) => (
            <Card key={key} className="bg-card/50 border-border/50 transition-all hover:bg-card/80">
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground mb-1">BTC vs {pair.label}</div>
                <div className="text-2xl font-bold tabular-nums" style={{ color: corrColors[key] ?? fg }}>
                  {fmtCorr(currentRSummary[key] ?? null)}
                </div>
                <div className="text-xs text-muted-foreground mt-1">{windowLabel} {methodLabel} R</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Chart 1: 滚动相关性 */}
        <Card className="border-border/50 bg-card/30 backdrop-blur-sm">
          <CardHeader className="border-b border-border/40 pb-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-muted-foreground" />
              <CardTitle className="text-lg">BTC 滚动相关性 — {windowLabel}窗口 · {methodLabel}</CardTitle>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              基于 NYSE 交易日历（标普500 交易日），比特币对数日收益率与各资产对数日收益率的 {windowLabel} 滚动相关系数。
              右轴为 BTC 价格 (USD)。数据截止: {meta?.btc_data_end ?? "--"}
            </p>
          </CardHeader>
          <CardContent className="pt-4 pb-2 sm:pt-0">
            {data ? (
              <EChart option={chart1Option} style={{ height: 440, width: "100%" }} />
            ) : error ? (
              <div className="flex h-[440px] items-center justify-center px-4">
                <InlineErrorState
                  title="相关性图表不可用"
                  message={error}
                  onRetry={() => router.refresh()}
                />
              </div>
            ) : (
              <ChartSkeleton height={440} />
            )}
          </CardContent>
        </Card>

        {/* 相关性数据表 */}
        <Card className="border-border/50 bg-card/30 backdrop-blur-sm">
          <CardHeader className="border-b border-border/40 pb-4">
            <CardTitle className="text-base">相关性数据表</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              {methodLabel} · 各资产对在不同窗口的最新滚动相关系数（取序列最后一个有效值）
            </p>
          </CardHeader>
          <CardContent className="pt-4">
            {corrTable.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border text-[11px] text-muted-foreground">
                      <th className="py-2 text-left font-medium">资产对</th>
                      {WINDOWS.map((w) => (
                        <th key={w.value} className="py-2 text-right font-medium">
                          {w.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {corrTable.map((row) => (
                      <tr key={row.key} className="border-b border-border/50 last:border-0">
                        <td className="py-2 text-xs">{row.label}</td>
                        {row.values.map((value, index) => (
                          <td
                            key={WINDOWS[index].value}
                            className={cn(
                              "py-2 text-right font-mono text-xs tabular-nums",
                              value == null
                                ? "text-muted-foreground"
                                : value >= 0
                                  ? "text-up"
                                  : "text-down",
                            )}
                          >
                            {value == null ? "—" : value.toFixed(3)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : data ? (
              <EmptyState
                compact
                title="暂无相关性数据"
                description={`${windowLabel} · ${methodLabel} 窗口内没有可用的滚动相关系数。`}
              />
            ) : (
              <TableSkeleton rows={4} columns={5} firstColWidth="w-24" />
            )}
          </CardContent>
        </Card>

        {/* Chart 2: BTC vs DXY 滞后平移价格 */}
        <Card className="border-border/50 bg-card/30 backdrop-blur-sm">
          <CardHeader className="border-b border-border/40 pb-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-muted-foreground" />
                <CardTitle className="text-lg">BTC vs DXY 远期走势</CardTitle>
              </div>
              <Tabs value={lagHorizon} onValueChange={setLagHorizon}>
                <TabsList className="grid grid-cols-4 w-full sm:w-auto h-8">
                  {LAG_OPTIONS.map((lp) => (
                    <TabsTrigger key={lp.value} value={lp.value} className="text-xs px-3 h-7">{lp.label}</TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>
            <div className="mt-3 p-3 rounded-lg bg-muted/30 border border-border/30 text-sm text-muted-foreground leading-relaxed">
              美元指数和加密货币市场呈反向关系，这意味着当美元指数上涨时，加密货币价格往往会下跌，反之亦然。
              这是因为加密货币通常被用作对冲美元的工具，当美元强势时，投资者往往会将资金从加密货币转移到美元或其他传统避险资产上。
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              图表展示 BTC 价格 (左轴, 蓝色面积图) 与 DXY 美元指数向后平移 {lagHorizon} 的价格 (右轴, 金色实线)。
              通过平移 DXY 可直观观察两者的领先-滞后关系。
            </p>
          </CardHeader>
          <CardContent className="pt-4 pb-2 sm:pt-0">
            {data ? (
              <EChart option={chart2Option} style={{ height: 440, width: "100%" }} />
            ) : error ? (
              <div className="flex h-[440px] items-center justify-center px-4">
                <InlineErrorState
                  title="远期走势图不可用"
                  message={error}
                  onRetry={() => router.refresh()}
                />
              </div>
            ) : (
              <ChartSkeleton height={440} />
            )}
          </CardContent>
        </Card>
    </div>
  );
}
