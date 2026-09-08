"use client";

import { useState, useMemo } from "react";
import { Activity, TrendingUp } from "lucide-react";
import { useTheme } from "next-themes";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EChart } from "@/components/EChart";
import { getChartTheme, withAlpha } from "@/lib/chart-theme";

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
// Helpers
// ---------------------------------------------------------------------------

function fmtPrice(v: number | null): string {
  if (v == null) return "--";
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(2)}`;
}

function fmtCorr(v: number | null): string {
  if (v == null) return "--";
  return v.toFixed(4);
}

function fmtTz(iso: string, tz: string, suffix: string): string {
  try {
    return (
      new Intl.DateTimeFormat("zh-CN", {
        timeZone: tz,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(iso)) + suffix
    );
  } catch {
    return new Date(iso).toLocaleString("zh-CN", { timeZone: tz }) + suffix;
  }
}

// ---------------------------------------------------------------------------
// CryptoClient
// ---------------------------------------------------------------------------

export function CryptoClient({ data: initialData }: { data: CorrelationResponse | null }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  // SSR 注入: page.tsx 经 getCachedCryptoCorrelation() (cacheTag "crypto") 预取后传入;
  // 后端读预计算表 (bp_crypto_corr_daily 等), 请求路径永不计算。无客户端 fetch。
  const [data] = useState<CorrelationResponse | null>(initialData);
  const error = !data ? "获取数据失败" : null;
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
  // 优先用后端预算好的 as_of_et / as_of_cn (确定性), 缺失则用 Intl 从 as_of (tz-aware ISO) 格式化。
  const asOfEt = meta?.as_of_et ?? (meta?.as_of ? fmtTz(meta.as_of, "America/New_York", " ET") : null);
  const asOfCn = meta?.as_of_cn ?? (meta?.as_of ? fmtTz(meta.as_of, "Asia/Shanghai", " 北京时间") : null);
  const methodLabel = METHODS.find((m) => m.value === corrMethod)?.label ?? corrMethod;
  const windowLabel = WINDOWS.find((w) => w.value === windowMonths)?.label ?? windowMonths;

  return (
    <div className="min-h-screen bg-background text-foreground pb-24">
      {/* Page Header */}
      <div className="border-b border-border/40 bg-card/30 backdrop-blur-sm">
        <div className="container mx-auto max-w-[1440px] px-4 sm:px-6 py-6 sm:py-8">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2">加密货币看板</h1>
              <p className="text-muted-foreground text-sm">
                比特币相关性分析 — 对数日收益率滚动相关系数与美元指数远期相关性
              </p>
            </div>
            <div className="flex items-center gap-2">
              {asOfEt && asOfCn && <Badge variant="outline" className="text-muted-foreground text-xs">数据截至: {asOfEt} / {asOfCn}</Badge>}
              {meta?.is_synced === false && meta?.effective_td && (
                <Badge variant="outline" className="text-amber-700/80 dark:text-amber-400/80 text-xs border-amber-500/30">
                  数据待齐 · 展示至 {meta.effective_td}
                </Badge>
              )}
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-4 mt-4">
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
      </div>

      <div className="container mx-auto max-w-[1440px] px-4 sm:px-6 py-6 sm:py-8 space-y-8">
        {error && (
          <div className="bg-destructive/10 border border-destructive/20 rounded-lg px-4 py-3 text-sm text-destructive">
            数据加载异常: {error}
          </div>
        )}

        {/* Snapshot Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
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
            ) : (
              <div className="flex items-center justify-center h-[440px] text-muted-foreground text-sm">
                {error ? "数据加载失败" : "数据加载中..."}
              </div>
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
            ) : (
              <div className="flex items-center justify-center h-[440px] text-muted-foreground text-sm">
                {error ? "数据加载失败" : "数据加载中..."}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
