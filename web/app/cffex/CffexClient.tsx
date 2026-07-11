"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import {
  ArrowUpRight, ArrowDownRight, Info, Filter, BarChart3, Activity,
} from "lucide-react";
import { useTheme } from "next-themes";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { EChart } from "@/components/EChart";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IndexSpot {
  variety: string;
  name: string;
  current_point: number | null;
  change_pct: number | null;
  prev_close: number | null;
}

interface ContractSpot {
  symbol: string;
  raw_symbol: string;
  variety: string;
  contract_type: string;
  current_price: number | null;
  settle: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  hold: number | null;
  amount: number | null;
  days_to_expiry: number;
  basis: number | null;
  premium_rate: number | null;
  ann_premium_rate: number | null;
}

interface SpotResponse {
  trading_status: "closed";
  indices: IndexSpot[];
  contracts: ContractSpot[];
  fetched_at: string;
  data_date?: string;  // e.g. "2026-07-03" — 期货与现货同日对齐日
  futures_latest?: string;
  spot_latest?: string | null;
  is_synced?: boolean;
  source?: string;
}

interface SeriesData {
  name: string;
  ann_premium_rates: (number | null)[];
  index_prices: (number | null)[];
}

interface HistoryResponse {
  dates: string[];
  series: Record<string, SeriesData>;
}

interface StatEntry {
  variety: string;
  name: string;
  count: number;
  min: number;
  max: number;
  p10: number;
  p30: number;
  p50: number;
  p70: number;
  p90: number;
  mean: number;
  std: number;
}

interface StatResponse {
  period: string;
  statistics: StatEntry[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VARIETIES = ["IF", "IH", "IC", "IM"] as const;

const VARIETY_NAMES: Record<string, string> = {
  IF: "沪深300",
  IH: "上证50",
  IC: "中证500",
  IM: "中证1000",
};

const CONTRACT_TYPE_ORDER: Record<string, number> = {
  "当月": 0,
  "次月": 1,
  "当季": 2,
  "次季": 3,
};

const STAT_PERIODS = [
  { value: "3M", label: "近三月" },
  { value: "6M", label: "近半年" },
  { value: "1Y", label: "近一年" },
  { value: "3Y", label: "近三年" },
  { value: "5Y", label: "近五年" },
] as const;

// ---------------------------------------------------------------------------
// API helpers (inline fetch, no auth needed for public page)
// ---------------------------------------------------------------------------

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// CffexClient
// ---------------------------------------------------------------------------

export function CffexClient() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  // --- State ---
  const [spotData, setSpotData] = useState<SpotResponse | null>(null);
  const [historyData, setHistoryData] = useState<HistoryResponse | null>(null);
  const [statData, setStatData] = useState<StatResponse | null>(null);
  const [selectedIndices, setSelectedIndices] = useState<string[]>([...VARIETIES]);
  const [statPeriod, setStatPeriod] = useState("3Y");
  const [spotError, setSpotError] = useState<string | null>(null);
  const [indexSeries, setIndexSeries] = useState<string>("none");
  const historyKeyRef = useRef<string>("");

  // --- Fetch spot (latest close snapshot, single fetch on mount) ---
  const fetchSpot = useCallback(async () => {
    try {
      setSpotError(null);
      const data = await fetchJSON<SpotResponse>("/api/cffex/spot");
      setSpotData(data);
    } catch (e) {
      setSpotError(e instanceof Error ? e.message : "获取行情失败");
    }
  }, []);

  // 挂载即拉取一次 (数据每日收盘后由 ingest 更新, 无需轮询)
  useEffect(() => {
    fetchSpot();
  }, [fetchSpot]);

  // --- Fetch history (full data for dataZoom) ---
  useEffect(() => {
    fetchJSON<HistoryResponse>("/api/cffex/history?days=0")
      .then(setHistoryData)
      .catch(() => {});
  }, []);

  // --- Fetch statistics (on period change) ---
  useEffect(() => {
    fetchJSON<StatResponse>(`/api/cffex/statistics?period=${statPeriod}`)
      .then(setStatData)
      .catch(() => {});
  }, [statPeriod]);

  // --- Filtering ---
  const toggleIndex = (id: string) => {
    setSelectedIndices(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const filteredIndices = useMemo(
    () => (spotData?.indices ?? []).filter(i => selectedIndices.includes(i.variety)),
    [spotData, selectedIndices]
  );

  const filteredContracts = useMemo(() => {
    const contracts = spotData?.contracts ?? [];
    return contracts
      .filter(c => selectedIndices.includes(c.variety))
      .sort((a, b) => {
        const vi = VARIETIES.indexOf(a.variety as typeof VARIETIES[number]) -
                   VARIETIES.indexOf(b.variety as typeof VARIETIES[number]);
        if (vi !== 0) return vi;
        return (CONTRACT_TYPE_ORDER[a.contract_type] ?? 99) -
               (CONTRACT_TYPE_ORDER[b.contract_type] ?? 99);
      });
  }, [spotData, selectedIndices]);

  // 主力合约: 每个品种持仓量最大的合约
  const dominantContract = useMemo(() => {
    const result: Record<string, string> = {};
    if (!spotData) return result;
    for (const v of VARIETIES) {
      const contracts = spotData.contracts.filter(c => c.variety === v && c.hold != null);
      if (contracts.length === 0) continue;
      contracts.sort((a, b) => (b.hold ?? 0) - (a.hold ?? 0));
      result[v] = contracts[0].symbol;
    }
    return result;
  }, [spotData]);

  const formatVolume = (v: number | null) => {
    if (v == null) return "--";
    if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
    return v.toLocaleString();
  };

  // --- ECharts theme colors ---
  const cardBg = isDark ? "rgba(22,22,22,0.9)" : "#fff";
  const fg = isDark ? "#EDEDED" : "#171717";
  const textCol = isDark ? "#A1A1A1" : "#666";
  const axisLineCol = isDark ? "#333" : "#ddd";
  const splitLineCol = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";

  const chartColors: Record<string, string> = {
    IF: isDark ? "#6C8EEF" : "#3B82F6",
    IH: isDark ? "#F59E0B" : "#D97706",
    IC: isDark ? "#EF4444" : "#E5484D",
    IM: isDark ? "#10B981" : "#059669",
  };

  // --- Chart option ---
  const chartOption = useMemo(() => {
    if (!historyData) return {};
    const isNewHistory = historyData.dates[0] !== historyKeyRef.current;
    if (isNewHistory) historyKeyRef.current = historyData.dates[0];

    const availVarieties = VARIETIES.filter(v => selectedIndices.includes(v) && historyData.series[v]);
    const dates = historyData.dates || [];

    const series: any[] = availVarieties.map(v => ({
      name: `${v} ${VARIETY_NAMES[v]}`,
      type: "line",
      smooth: true,
      yAxisIndex: 0,
      symbol: "none",
      itemStyle: { color: chartColors[v] },
      lineStyle: { width: 2, color: chartColors[v] },
      data: historyData.series[v]?.ann_premium_rates ?? [],
    }));

    // 右轴指数价格系列 (用户可选)
    const idxVar = VARIETIES.includes(indexSeries as any) ? indexSeries : null;
    const hasIdxSeries = idxVar && historyData.series[idxVar]?.index_prices?.some((p: any) => p != null);
    if (hasIdxSeries && idxVar) {
      series.push({
        name: `${VARIETY_NAMES[idxVar]} 指数`,
        type: "line",
        smooth: true,
        yAxisIndex: 1,
        symbol: "none",
        lineStyle: { width: 1, type: "dashed", color: isDark ? "#888" : "#999" },
        data: historyData.series[idxVar]?.index_prices ?? [],
      });
    }

    const legendData = [
      ...availVarieties.map(v => `${v} ${VARIETY_NAMES[v]}`),
      ...(hasIdxSeries && idxVar ? [`${VARIETY_NAMES[idxVar]} 指数`] : []),
    ];

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: cardBg,
        borderColor: isDark ? "#333" : "#e5e5e5",
        textStyle: { color: fg, fontSize: 12 },
        formatter: (params: any) => {
          if (!Array.isArray(params)) return "";
          let html = `<div style="font-size:11px;margin-bottom:4px">${params[0].axisValue}</div>`;
          for (const p of params) {
            const val = p.value;
            if (val == null || val === "-") continue;
            const marker = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>`;
            if (p.seriesName.includes("指数")) {
              html += `<div style="margin:2px 0">${marker}${p.seriesName}: <b>${Number(val).toFixed(2)}</b></div>`;
            } else {
              html += `<div style="margin:2px 0">${marker}${p.seriesName}: <b>${Number(val).toFixed(4)}%</b></div>`;
            }
          }
          return html;
        },
      },
      legend: {
        type: "scroll",
        bottom: 30,
        textStyle: { color: textCol, fontSize: 11 },
        data: legendData,
      },
      dataZoom: [
        ...(isNewHistory
          ? [{ type: "slider", bottom: 0, start: 60, end: 100, height: 22,
               textStyle: { color: textCol, fontSize: 10 } }]
          : [{ type: "slider", bottom: 0, height: 22,
               textStyle: { color: textCol, fontSize: 10 } }]
        ),
        { type: "inside" },
      ],
      grid: { left: 60, right: 60, top: 15, bottom: 75 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: dates,
        axisLine: { lineStyle: { color: axisLineCol } },
        axisLabel: { color: textCol, fontSize: 10 },
      },
      yAxis: [
        {
          type: "value",
          name: "年化升贴水率 (%)",
          nameTextStyle: { color: textCol, fontSize: 11 },
          axisLabel: {
            color: textCol,
            fontSize: 10,
            formatter: (v: number) => `${v.toFixed(1)}%`,
          },
          splitLine: { lineStyle: { color: splitLineCol, type: "dashed" } },
        },
        {
          type: "value",
          name: "指数价格",
          nameTextStyle: { color: textCol, fontSize: 11 },
          axisLabel: { color: textCol, fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series,
    };
  }, [historyData, selectedIndices, indexSeries, isDark, cardBg, fg, textCol, axisLineCol, splitLineCol, chartColors]);

  // --- Trading status badge: 始终「已收盘」+ 同日对齐 data_date ---
  const dataDate = spotData?.data_date || (spotData?.fetched_at ? new Date(spotData.fetched_at).toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" }) : null);
  const dataTimeStr = dataDate ? `${dataDate} 15:00:00` : null;

  const statusBadge = (
    <div className="flex flex-col items-start sm:items-end gap-0.5">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-muted-foreground text-xs">
          已收盘
        </Badge>
      </div>
      {dataTimeStr && (
        <span className="text-xs text-muted-foreground tabular-nums">
          {dataTimeStr}
        </span>
      )}
    </div>
  );

  // --- Current composite rate per variety (from spot contracts) ---
  const currentComposite = useMemo(() => {
    const result: Record<string, number | null> = {};
    if (!spotData) return result;
    for (const v of VARIETIES) {
      const contracts = spotData.contracts.filter(c => c.variety === v);
      const ciYue = contracts.find(c => c.contract_type === "次月");
      const dangJi = contracts.find(c => c.contract_type === "当季");
      if (ciYue?.ann_premium_rate != null && dangJi?.ann_premium_rate != null) {
        result[v] = 0.6 * ciYue.ann_premium_rate + 0.4 * dangJi.ann_premium_rate;
      } else {
        result[v] = null;
      }
    }
    return result;
  }, [spotData]);

  // --- Current percentile in historical distribution ---
  const currentPercentile = useCallback((variety: string, histValues: number[]) => {
    const cur = currentComposite[variety];
    if (cur == null || histValues.length === 0) return null;
    let countBelow = 0;
    for (const v of histValues) {
      if (v < cur) countBelow++;
    }
    return countBelow / histValues.length;
  }, [currentComposite]);

  // -------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------
  return (
    <div className="min-h-screen bg-background text-foreground pb-24">
      {/* Page Header */}
      <div className="border-b border-border/40 bg-card/30 backdrop-blur-sm">
        <div className="container mx-auto max-w-7xl px-4 sm:px-6 py-6 sm:py-8">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2">
                股指期货看板
              </h1>
              <p className="text-muted-foreground text-sm">
                中金所股指期货收盘数据监控与历史升贴水分析
              </p>
            </div>
            <div className="flex items-center gap-2">
              {statusBadge}
            </div>
          </div>
        </div>
      </div>

      <div className="container mx-auto max-w-7xl px-4 sm:px-6 py-6 sm:py-8 space-y-8">
        {/* Spot Error Banner */}
        {spotError && (
          <div className="bg-destructive/10 border border-destructive/20 rounded-lg px-4 py-3 text-sm text-destructive">
            行情加载异常: {spotError} (显示缓存数据)
          </div>
        )}

        {/* Section 1: Index Overview */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {filteredIndices.map(idx => (
            <Card
              key={idx.variety}
              className="bg-card/50 shadow-none border-border/50 transition-all hover:bg-card/80"
            >
              <CardContent className="p-4 sm:p-5">
                <div className="text-xs text-muted-foreground mb-1">
                  {idx.name} <span className="font-mono text-[10px] opacity-60">{idx.variety}</span>
                </div>
                <div className="flex items-end justify-between gap-2">
                  <div
                    className="text-xl sm:text-2xl font-bold tabular-nums"
                  >
                    {idx.current_point != null ? idx.current_point.toFixed(2) : "--"}
                  </div>
                  <div
                    className={`flex items-center text-sm font-medium pb-0.5 ${
                      idx.change_pct != null
                        ? (idx.change_pct >= 0 ? "text-up" : "text-down")
                        : "text-muted-foreground"
                    }`}
                  >
                    {idx.change_pct != null && idx.change_pct >= 0 ? (
                      <ArrowUpRight className="w-3.5 h-3.5 mr-0.5" />
                    ) : (
                      <ArrowDownRight className="w-3.5 h-3.5 mr-0.5" />
                    )}
                    {idx.change_pct != null ? `${Math.abs(idx.change_pct).toFixed(2)}%` : "--"}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Section 2: Live Contract Table */}
        <Card className="border-border/50 shadow-sm bg-card/30 backdrop-blur-sm">
          <CardHeader className="border-b border-border/40 pb-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-muted-foreground" />
                <CardTitle className="text-lg">合约监控</CardTitle>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Filter className="w-4 h-4 text-muted-foreground" />
                {VARIETIES.map(v => (
                  <Button
                    key={v}
                    variant={selectedIndices.includes(v) ? "default" : "outline"}
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => toggleIndex(v)}
                  >
                    {v}
                  </Button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0 overflow-x-auto">
            <Table>
              <TableHeader className="bg-muted/30">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[80px] sm:w-[100px]">品种</TableHead>
                  <TableHead>合约名</TableHead>
                  <TableHead className="text-right">最新点位</TableHead>
                  <TableHead className="text-right hidden md:table-cell">持仓量</TableHead>
                  <TableHead className="text-right hidden md:table-cell">结算价</TableHead>
                  <TableHead className="text-right hidden sm:table-cell">距交割</TableHead>
                  <TableHead className="text-right">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger className="flex items-center justify-end w-full gap-1 underline underline-offset-2 decoration-muted-foreground/50 decoration-dotted">
                          基差 <Info className="w-3 h-3" />
                        </TooltipTrigger>
                        <TooltipContent>现货指数 - 期货价。正值=现货高于期货(贴水)</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </TableHead>
                  <TableHead className="text-right">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger className="flex items-center justify-end w-full gap-1 underline underline-offset-2 decoration-muted-foreground/50 decoration-dotted">
                          升贴水率 <Info className="w-3 h-3" />
                        </TooltipTrigger>
                        <TooltipContent>(期货价 - 现货指数) / 现货指数。正值=升水, 负值=贴水</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </TableHead>
                  <TableHead className="text-right">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger className="flex items-center justify-end w-full gap-1 font-semibold underline underline-offset-2 decoration-muted-foreground/50 decoration-dotted">
                          年化升贴水率 <Info className="w-3 h-3" />
                        </TooltipTrigger>
                        <TooltipContent>按距离交割剩余天数折算的年化收益率</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredContracts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center text-muted-foreground py-12">
                      {spotError
                        ? `行情加载异常: ${spotError}`
                        : spotData?.source?.startsWith("db_close")
                          ? `显示最新收盘数据 (${spotData.source.replace("db_close_", "")})`
                          : "数据加载中..."}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredContracts.map(c => (
                    <TableRow key={c.symbol} className="transition-colors hover:bg-muted/20">
                      <TableCell className="font-medium">
                        <div className="flex flex-col">
                          <span>{c.variety}</span>
                          <span className="text-xs text-muted-foreground">{VARIETY_NAMES[c.variety]}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className={`font-mono ${dominantContract[c.variety] === c.symbol ? "font-bold" : ""}`}>
                            {c.symbol}
                          </span>
                          <span className="text-xs text-muted-foreground">{c.contract_type}合约</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        <span>
                          {c.current_price != null ? c.current_price.toFixed(2) : "--"}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-muted-foreground text-xs hidden md:table-cell">
                        {formatVolume(c.hold)}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-muted-foreground hidden md:table-cell">
                        {c.settle != null ? c.settle.toFixed(2) : "--"}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-muted-foreground hidden sm:table-cell">
                        {c.days_to_expiry} 天
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        <span className={c.basis != null && c.basis > 0 ? "text-down" : c.basis != null && c.basis < 0 ? "text-up" : ""}>
                          {c.basis != null ? c.basis.toFixed(2) : "--"}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        <span className={c.premium_rate != null && c.premium_rate > 0 ? "text-up" : c.premium_rate != null && c.premium_rate < 0 ? "text-down" : ""}>
                          {c.premium_rate != null ? `${c.premium_rate.toFixed(2)}%` : "--"}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums font-semibold">
                        <span className={c.ann_premium_rate != null && c.ann_premium_rate > 0 ? "text-up" : c.ann_premium_rate != null && c.ann_premium_rate < 0 ? "text-down" : ""}>
                          {c.ann_premium_rate != null ? `${c.ann_premium_rate.toFixed(2)}%` : "--"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Section 3: Historical Chart */}
        <Card className="border-border/50 shadow-sm bg-card/30 backdrop-blur-sm">
          <CardHeader className="border-b border-border/40 pb-4">
            <div className="flex flex-col gap-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-muted-foreground" />
                  <CardTitle className="text-lg">年化升贴水率走势</CardTitle>
                </div>
                <div className="text-xs text-muted-foreground">
                  综合年化升贴水率计算公式 = 0.6 * 次月 + 0.4 * 当季
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>叠加指数:</span>
                <Select value={indexSeries} onValueChange={setIndexSeries}>
                  <SelectTrigger className="h-7 w-[130px] text-xs">
                    <SelectValue placeholder="不显示" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">不显示</SelectItem>
                    {VARIETIES.map(v => (
                      <SelectItem key={v} value={v}>{v} {VARIETY_NAMES[v]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-4 pb-2">
            {historyData ? (
              <EChart option={chartOption} style={{ height: 440, width: "100%" }} />
            ) : (
              <div className="flex items-center justify-center h-[440px] text-muted-foreground text-sm">
                历史数据加载中...
              </div>
            )}
          </CardContent>
        </Card>

        {/* Section 4: Statistics Table */}
        <Card className="border-border/50 shadow-sm bg-card/30 backdrop-blur-sm">
          <CardHeader className="border-b border-border/40 pb-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <CardTitle className="text-lg">历史升贴水统计分位</CardTitle>
              <Tabs value={statPeriod} onValueChange={setStatPeriod}>
                <TabsList className="w-full grid grid-cols-3 sm:grid-cols-5">
                  {STAT_PERIODS.map(sp => (
                    <TabsTrigger key={sp.value} value={sp.value} className="text-xs px-2 sm:px-3">
                      {sp.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>
          </CardHeader>
          <CardContent className="p-0 overflow-x-auto">
            <Table>
              <TableHeader className="bg-muted/30">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[80px]">品种</TableHead>
                  <TableHead className="text-center font-semibold">综合年化升贴水率</TableHead>
                  <TableHead className="text-right">当前分位值</TableHead>
                  <TableHead className="text-right hidden md:table-cell">10%分位</TableHead>
                  <TableHead className="text-right hidden md:table-cell">30%分位</TableHead>
                  <TableHead className="text-right font-semibold">50%分位</TableHead>
                  <TableHead className="text-right hidden md:table-cell">70%分位</TableHead>
                  <TableHead className="text-right hidden md:table-cell">90%分位</TableHead>
                  <TableHead className="text-right hidden lg:table-cell">均值</TableHead>
                  <TableHead className="text-right hidden lg:table-cell">+1σ</TableHead>
                  <TableHead className="text-right hidden lg:table-cell">-1σ</TableHead>
                  <TableHead className="text-right hidden lg:table-cell">+2σ</TableHead>
                  <TableHead className="text-right hidden lg:table-cell">-2σ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(statData?.statistics ?? [])
                  .filter(s => selectedIndices.includes(s.variety))
                  .map(s => (
                    <TableRow key={s.variety} className="transition-colors hover:bg-muted/20">
                      <TableCell className="font-medium">{s.variety}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums font-semibold">
                        {currentComposite[s.variety] != null
                          ? `${currentComposite[s.variety]!.toFixed(2)}%`
                          : "--"}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {(() => {
                          const pct = currentPercentile(s.variety, []);
                          // Need actual values array; use stats API data approximation
                          const cur = currentComposite[s.variety];
                          if (cur == null || s.count === 0) return "--";
                          // Estimate percentile from mean and std
                          const normalizedPct = (() => {
                            if (s.std === 0) return 0.5;
                            const z = (cur - s.mean) / s.std;
                            return Math.max(0, Math.min(1, 0.5 + z / 6));
                          })();
                          const isLowPct = normalizedPct < 0.5;
                          return (
                            <span className="inline-flex items-center gap-1.5">
                              <span className={isLowPct ? "text-down" : "text-up"}>
                                {(normalizedPct * 100).toFixed(0)}%
                              </span>
                              <span className="w-12 h-2 rounded-full bg-muted/30 overflow-hidden" dir="ltr">
                                <span
                                  className={`block h-full rounded-full ${isLowPct ? "bg-down" : "bg-up"}`}
                                  style={{ width: `${Math.max(2, normalizedPct * 100)}%`, minWidth: 2 }}
                                />
                              </span>
                            </span>
                          );
                        })()}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums hidden md:table-cell">{s.p10}%</TableCell>
                      <TableCell className="text-right font-mono tabular-nums hidden md:table-cell">{s.p30}%</TableCell>
                      <TableCell className="text-right font-mono tabular-nums font-semibold bg-muted/10">
                        {s.p50}%
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums hidden md:table-cell">{s.p70}%</TableCell>
                      <TableCell className="text-right font-mono tabular-nums hidden md:table-cell">{s.p90}%</TableCell>
                      <TableCell className="text-right font-mono tabular-nums hidden lg:table-cell">{s.mean}%</TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-up hidden lg:table-cell">
                        {(s.mean + s.std).toFixed(2)}%
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-down hidden lg:table-cell">
                        {(s.mean - s.std).toFixed(2)}%
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-up hidden lg:table-cell">
                        {(s.mean + 2 * s.std).toFixed(2)}%
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-down hidden lg:table-cell">
                        {(s.mean - 2 * s.std).toFixed(2)}%
                      </TableCell>
                    </TableRow>
                  ))}
                {(statData === null) && (
                  <TableRow>
                    <TableCell colSpan={13} className="text-center text-muted-foreground py-12">
                      统计数据加载中...
                    </TableCell>
                  </TableRow>
                )}
                {statData?.statistics?.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={13} className="text-center text-muted-foreground py-12">
                      暂无历史统计数据 (请先运行数据回填)
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
