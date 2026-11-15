"use client";

/**
 * /valuation v2 内容区（纯展示，不发起数据请求）。
 *
 * 窗口/指标已由 URL 驱动、服务端 Suspense 加载；本组件只负责本地交互
 * （搜索、排序、列设置、类别/行业筛选、图表口径切换）。
 */
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type {
  BroadProxyCard,
  IndexQuoteRow,
  MarketValuationCard,
  MviInfo,
  PercentileWindow,
  ValuationHistory,
  ValuationMetric,
} from "@/lib/valuation-types";
import { changeClass, formatSignedPct } from "@/lib/valuation-mock";
import {
  mapBroadProxy,
  mapIndexRow,
  mapMarketCard,
  mapValuationHistory,
} from "@/lib/valuation-api-map";
import {
  METRIC_LABEL,
  type BandMode,
  IndustryHeatmap,
  PeBandChart,
  ProxyCard,
} from "./_components/revamp-charts";
import {
  ChartCard,
  DividendValueChart,
  MviPanel,
  PbDividendMatrix,
  RoePeMatrix,
  V2_METRICS,
  V2_WINDOWS,
} from "./_components/valuation-v2";
import { PercentileBar, percentileTone, SectionHeading } from "./_components/valuation-ui";

const CATEGORIES = ["全部", "宽基", "行业", "主题", "策略"] as const;
type CategoryFilter = (typeof CATEGORIES)[number];

type ColumnKey =
  | "close"
  | "change_pct"
  | "change_52w"
  | "pe"
  | "pe_pct"
  | "pb"
  | "pb_pct"
  | "dividend"
  | "erp"
  | "dividend_pct"
  | "erp_pct"
  | "position"
  | "fund";

const COLUMNS: ReadonlyArray<{ key: ColumnKey; label: string }> = [
  { key: "close", label: "收盘" },
  { key: "change_pct", label: "今日" },
  { key: "change_52w", label: "52 周" },
  { key: "pe", label: "PE" },
  { key: "pe_pct", label: "PE 分位" },
  { key: "pb", label: "PB" },
  { key: "pb_pct", label: "PB 分位" },
  { key: "dividend", label: "股息率" },
  { key: "erp", label: "ERP" },
  { key: "dividend_pct", label: "股息率分位" },
  { key: "erp_pct", label: "ERP 分位" },
  { key: "position", label: "52 周位置" },
  { key: "fund", label: "ETF/基金规模" },
];

const DEFAULT_COLUMNS: ColumnKey[] = [
  "close",
  "change_pct",
  "change_52w",
  "pe",
  "pe_pct",
  "pb",
  "pb_pct",
  "dividend",
  "erp",
  "fund",
  "position",
];

const PAGE_SIZE = 60;

function cellValue(row: IndexQuoteRow, key: ColumnKey): number | null {
  switch (key) {
    case "close":
      return row.close;
    case "change_pct":
      return row.change_pct;
    case "change_52w":
      return row.change_52w_pct;
    case "pe":
      return row.pe_ttm;
    case "pe_pct":
      return row.pe_percentile;
    case "pb":
      return row.pb;
    case "pb_pct":
      return row.pb_percentile;
    case "dividend":
      return row.dividend_yield_pct;
    case "erp":
      return row.risk_premium_pct;
    case "dividend_pct":
      return row.dividend_percentile ?? null;
    case "erp_pct":
      return row.erp_percentile ?? null;
    case "position":
      return row.position_52w_pct ?? null;
    case "fund":
      return row.fund_aum ?? null;
    default:
      return null;
  }
}

function formatYi(value: number | null): string {
  if (value == null) return "—";
  return (value / 1e8).toFixed(2) + " 亿";
}

export interface ValuationHomeV2Props {
  rows: IndexQuoteRow[];
  boards: MarketValuationCard[];
  proxies: BroadProxyCard[];
  history: ValuationHistory | null;
  mvi: MviInfo | null;
  window: PercentileWindow;
  metric: ValuationMetric;
}

export function ValuationHomeV2({
  rows: initialRows,
  boards: initialBoards,
  proxies: initialProxies,
  history: initialHistory,
  mvi,
  window: initialWindow,
  metric: initialMetric,
}: ValuationHomeV2Props) {
  const router = useRouter();
  const [rows, setRows] = useState(initialRows);
  const [boards, setBoards] = useState(initialBoards);
  const [proxies, setProxies] = useState(initialProxies);
  const [history, setHistory] = useState(initialHistory);
  const [window, setWindow] = useState<PercentileWindow>(initialWindow);
  const [metric, setMetric] = useState<ValuationMetric>(initialMetric);
  const [pending, startTransition] = useTransition();
  const [switching, setSwitching] = useState(false);
  const firstRender = useRef(true);

  // 切换窗口/指标：客户端取数 + 保留旧图（半透明），不整页闪。
  const applyFilter = useCallback(
    (nextWindow: PercentileWindow, nextMetric: ValuationMetric) => {
      if (nextWindow === window && nextMetric === metric) return;
      setWindow(nextWindow);
      setMetric(nextMetric);
      setSwitching(true);
      const base = nextWindow + ":" + nextMetric;
      void Promise.all([
        fetch("/api/valuation/indices?limit=1000&window=" + nextWindow + "&metric=" + nextMetric)
          .then((response) => (response.ok ? response.json() : null))
          .then((payload) => {
            if (payload?.data) setRows((payload.data as Record<string, unknown>[]).map(mapIndexRow));
          })
          .catch(() => {}),
        fetch("/api/valuation/overview?window=" + nextWindow)
          .then((response) => (response.ok ? response.json() : null))
          .then((payload) => {
            if (!payload) return;
            if (payload.data) setBoards((payload.data as Record<string, unknown>[]).map(mapMarketCard));
            const proxyList = payload.meta?.proxies;
            if (Array.isArray(proxyList)) {
              setProxies(proxyList.map((item) => mapBroadProxy(item as Record<string, unknown>)));
            }
          })
          .catch(() => {}),
        fetch("/api/valuation/000300/history?metric=" + nextMetric + "&window=" + nextWindow)
          .then((response) => (response.ok ? response.json() : null))
          .then((payload) => {
            if (payload) setHistory(mapValuationHistory("000300", payload, nextMetric, nextWindow));
          })
          .catch(() => {}),
      ]).finally(() => {
        setSwitching(false);
        startTransition(() => {
          router.replace("/valuation?window=" + nextWindow + "&metric=" + nextMetric, { scroll: false });
        });
      });
    },
    [window, metric, router],
  );

  useEffect(() => {
    firstRender.current = false;
  }, []);

  const [category, setCategory] = useState<CategoryFilter>("全部");
  const [industry, setIndustry] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [hasFund, setHasFund] = useState(true);
  const [sortKey, setSortKey] = useState<ColumnKey | null>("fund");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [columns, setColumns] = useState<ColumnKey[]>(DEFAULT_COLUMNS);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [bandMode, setBandMode] = useState<BandMode>("pct");
  const [sigma, setSigma] = useState(1);

  const industries = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) if (row.industry) set.add(row.industry);
    return [...set].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [rows]);

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    let list = rows.filter((row) => {
      if (hasFund && (row.fund_count ?? 0) === 0) return false;
      if (category !== "全部" && row.category !== category) return false;
      if (industry && row.industry !== industry) return false;
      if (keyword) {
        const text = (row.name + " " + row.index_code).toLowerCase();
        if (!text.includes(keyword)) return false;
      }
      return true;
    });
    if (sortKey) {
      list = [...list].sort((a, b) => {
        const left = cellValue(a, sortKey);
        const right = cellValue(b, sortKey);
        if (left == null && right == null) return 0;
        if (left == null) return 1;
        if (right == null) return -1;
        return sortDir === "asc" ? left - right : right - left;
      });
    }
    return list;
  }, [rows, category, industry, search, hasFund, sortKey, sortDir]);

  const visibleRows = filtered.slice(0, pageSize);
  const proxyName = proxies.find((item) => item.index_code === "000300")?.name ?? "沪深300";

  const toggleColumn = useCallback((key: ColumnKey) => {
    setColumns((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }, []);

  const toggleSort = useCallback(
    (key: ColumnKey) => {
      if (sortKey === key) {
        setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("desc");
      }
    },
    [sortKey],
  );

  return (
    <div className="relative mx-auto w-full max-w-[1600px] px-4 pb-16 sm:px-6 lg:px-8">
      {(switching || pending) && (
        <div className="fixed left-0 right-0 top-0 z-[60] h-0.5 overflow-hidden bg-primary/20">
          <div className="h-full w-1/3 animate-[loadingbar_1.2s_ease-in-out_infinite] bg-primary" />
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="muted text-xs">切换窗口/指标即时更新，不整页刷新</div>
        <div className="flex flex-wrap items-center gap-1.5">
          {V2_WINDOWS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => applyFilter(item.value, metric)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                window === item.value
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <div className={cn("transition-opacity", switching || pending ? "pointer-events-none opacity-50" : "opacity-100")}>
      {/* 代表性宽基 */}
      <section className="mt-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {proxies.map((card) => (
            <ProxyCard key={card.index_code} card={card} />
          ))}
        </div>
      </section>

      {/* 主图 + 行业热力 */}
      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title={proxyName + " · Valuation Band"}
          desc={METRIC_LABEL[metric] + " · " + (V2_WINDOWS.find((w) => w.value === window)?.label ?? "")}
          className="xl:col-span-2"
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
              {V2_METRICS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => applyFilter(window, item.value)}
                  className={cn(
                    "px-2.5 py-1 transition-colors",
                    metric === item.value ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
              <button
                type="button"
                onClick={() => setBandMode("pct")}
                className={cn(
                  "px-2 py-1",
                  bandMode === "pct" ? "bg-foreground text-background" : "text-muted-foreground",
                )}
              >
                分位带
              </button>
              <button
                type="button"
                onClick={() => setBandMode("sd")}
                className={cn(
                  "px-2 py-1",
                  bandMode === "sd" ? "bg-foreground text-background" : "text-muted-foreground",
                )}
              >
                标准差
              </button>
            </div>
            {bandMode === "sd" ? (
              <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
                {[1, 2, 3].map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSigma(value)}
                    className={cn(
                      "px-2 py-1",
                      sigma === value ? "bg-foreground text-background" : "text-muted-foreground",
                    )}
                  >
                    {value}σ
                  </button>
                ))}
              </div>
            ) : null}
            </div>
          </div>
          {history && history.series.length > 0 ? (
            <PeBandChart
              series={history.series}
              stats={history.stats}
              metric={metric}
              mode={bandMode}
              sigma={sigma}
              frequency="周线"
            />
          ) : (
            <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
              该指标暂无历史序列
            </div>
          )}
        </ChartCard>

        <ChartCard title="行业估值热力" desc="PE 分位均值，颜色越高表示越贵">
          <IndustryHeatmap rows={rows} onSelect={(value) => setIndustry(value)} />
        </ChartCard>
      </section>

      {/* 红利指数吸引力 + 全市场截面 */}
      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title="红利指数吸引力"
          desc="股息率 × PB，气泡=跟踪基金规模；左上（低 PB + 高股息）最具吸引力"
          className="xl:col-span-2"
        >
          <DividendValueChart rows={rows} />
        </ChartCard>
        <ChartCard
          title="市场估值指数 MVI"
          desc="双仪表盘 · 0=极度低估 / 100=极度高估 · 每日 17:05 刷新"
        >
          <MviPanel mvi={mvi} />
        </ChartCard>
      </section>

      {/* 两张估值矩阵 */}
      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="估值矩阵 · PB 分位 × 股息率"
          desc={"PB 分位窗口：" + (V2_WINDOWS.find((w) => w.value === window)?.label ?? "5 年") + " · 回归线 + 方程 + R²；气泡=基金规模"}
        >
          <PbDividendMatrix rows={rows} />
        </ChartCard>
        <ChartCard
          title="估值矩阵 · ROE × PE"
          desc={"ROE 当前值 · PE 窗口：" + (V2_WINDOWS.find((w) => w.value === window)?.label ?? "5 年") + " · log 轴；回归线 + 方程 + R²"}
        >
          <RoePeMatrix rows={rows} />
        </ChartCard>
      </section>

      {/* 指数列表 */}
      <section className="mt-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <SectionHeading title="指数列表" hint={"共 " + filtered.length + " 只"} />
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索指数 / 代码"
                className="h-8 w-44 pl-7 text-xs"
              />
            </div>
            <select
              value={industry ?? ""}
              onChange={(event) => setIndustry(event.target.value || null)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs"
            >
              <option value="">全部行业</option>
              {industries.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-8 gap-1 text-xs">
                  <SlidersHorizontal className="size-3.5" />
                  列设置
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-56 p-2">
                <div className="max-h-72 space-y-1 overflow-auto">
                  {COLUMNS.map((column) => (
                    <label
                      key={column.key}
                      className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted"
                    >
                      <Checkbox
                        checked={columns.includes(column.key)}
                        onCheckedChange={() => toggleColumn(column.key)}
                      />
                      {column.label}
                    </label>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setHasFund((value) => !value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              hasFund
                ? "border-foreground bg-foreground text-background"
                : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            有 ETF/基金
          </button>
          {CATEGORIES.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setCategory(item)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                category === item
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {item}
            </button>
          ))}
          {industry ? (
            <button
              type="button"
              onClick={() => setIndustry(null)}
              className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-xs text-primary"
            >
              {industry}
              <X className="size-3" />
            </button>
          ) : null}
        </div>

        <div className="mt-3 overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[1080px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                <th className="sticky left-0 z-10 bg-muted/40 px-2.5 py-2 text-left font-medium">指数</th>
                {COLUMNS.filter((column) => columns.includes(column.key)).map((column) => (
                  <th key={column.key} className="px-2 py-2 text-right font-medium">
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className="inline-flex items-center gap-1 hover:text-foreground"
                    >
                      {column.label}
                      {sortKey === column.key ? (
                        sortDir === "asc" ? (
                          <ArrowUp className="size-3" />
                        ) : (
                          <ArrowDown className="size-3" />
                        )
                      ) : (
                        <ArrowUpDown className="size-3 opacity-40" />
                      )}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr
                  key={row.index_code}
                  className="border-b border-border/50 last:border-0 hover:bg-muted/40"
                >
                  <td className="sticky left-0 z-10 bg-background px-2.5 py-2">
                    <Link href={"/valuation/" + row.index_code} className="group block">
                      <span className="text-sm font-medium group-hover:text-primary">{row.name}</span>
                      <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                        {row.index_code}
                      </span>
                      <span className="ml-2 text-[10px] text-muted-foreground">
                        {row.category}
                        {row.industry ? " · " + row.industry : ""}
                      </span>
                      {row.quote_lag_days != null && row.quote_lag_days > 0 ? (
                        <span
                          className="ml-1.5 rounded bg-warning/20 px-1 py-0.5 text-[10px] text-warning-foreground"
                          title={"行情落后最新交易日 " + row.quote_lag_days + " 个交易日"}
                        >
                          行情滞后 {row.quote_lag_days} 日
                        </span>
                      ) : row.quote_status === "missing" ? (
                        <span
                          className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground"
                          title="该指数暂无行情数据源"
                        >
                          无行情
                        </span>
                      ) : null}
                    </Link>
                  </td>
                  {COLUMNS.filter((column) => columns.includes(column.key)).map((column) => {
                    const value = cellValue(row, column.key);
                    if (column.key === "position") {
                      const reason =
                        row.position_52w_pct == null
                          ? (row.close == null ? "该指数暂无行情数据" : "K 线历史不足 251 个交易日")
                          : null;
                      return (
                        <td key={column.key} className="px-2 py-2" title={reason ?? undefined}>
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16">
                              <PercentileBar value={row.position_52w_pct ?? null} showLabels={false} />
                            </div>
                            <span className="w-9 text-right font-mono text-xs tabular-nums text-muted-foreground">
                              {value == null ? "—" : value.toFixed(0) + "%"}
                            </span>
                          </div>
                        </td>
                      );
                    }
                    if (column.key === "pe_pct" || column.key === "pb_pct" || column.key === "dividend_pct" || column.key === "erp_pct") {
                      return (
                        <td key={column.key} className="px-2 py-2 text-right">
                          <span className={cn("font-mono text-xs tabular-nums", percentileTone(value))}>
                            {value == null ? "—" : value.toFixed(1) + "%"}
                          </span>
                        </td>
                      );
                    }
                    if (column.key === "change_pct" || column.key === "change_52w") {
                      return (
                        <td
                          key={column.key}
                          className={cn("px-2 py-2 text-right font-mono text-xs tabular-nums", changeClass(value))}
                        >
                          {formatSignedPct(value)}
                        </td>
                      );
                    }
                    if (column.key === "dividend" || column.key === "erp") {
                      return (
                        <td key={column.key} className="px-2 py-2 text-right font-mono text-xs tabular-nums">
                          {value == null ? "—" : value.toFixed(2) + "%"}
                        </td>
                      );
                    }
                    if (column.key === "fund") {
                      return (
                        <td key={column.key} className="px-2 py-2 text-right font-mono text-xs tabular-nums">
                          {formatYi(value)}
                          <span className="ml-1 text-[10px] text-muted-foreground">
                            {row.fund_count ? "(" + row.fund_count + ")" : ""}
                          </span>
                        </td>
                      );
                    }
                    return (
                      <td key={column.key} className="px-2 py-2 text-right font-mono text-xs tabular-nums">
                        {value == null ? "—" : value.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
          <span>
            显示 {visibleRows.length} / {filtered.length} 只（默认仅含有 ETF/基金，按规模降序）
          </span>
          {visibleRows.length < filtered.length ? (
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => setPageSize((size) => size + PAGE_SIZE)}
            >
              显示更多
              <ChevronDown className="ml-1 size-3.5" />
            </Button>
          ) : null}
        </div>
      </section>
      </div>
    </div>
  );
}
