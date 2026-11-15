"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { mapBroadProxy, mapIndexRow, mapValuationHistory } from "@/lib/valuation-api-map";
import type {
  BroadProxyCard,
  IndexQuoteRow,
  MarketValuationCard,
  PercentileWindow,
  ValuationHistory,
  ValuationMetric,
} from "@/lib/valuation-types";
import { changeClass, formatNumber, formatSignedPct } from "@/lib/valuation-mock";
import {
  METRIC_LABEL,
  type BandMode,
  IndustryHeatmap,
  PeBandChart,
  ProxyCard,
  ValuationMatrix,
} from "./_components/revamp-charts";
import { MetricCard, PercentileBar, SectionHeading, Surface, percentileTone } from "./_components/valuation-ui";

const WINDOWS: ReadonlyArray<{ value: PercentileWindow; label: string }> = [
  { value: "1y", label: "1 年" },
  { value: "3y", label: "3 年" },
  { value: "5y", label: "5 年" },
  { value: "10y", label: "10 年" },
  { value: "all", label: "全历史" },
];

const METRICS: ReadonlyArray<{ value: ValuationMetric; label: string }> = [
  { value: "pe_ttm", label: "PE 分位" },
  { value: "pb", label: "PB 分位" },
  { value: "dividend_yield_ttm", label: "股息率分位" },
  { value: "erp", label: "ERP 分位" },
];

const CATEGORIES = ["全部", "宽基", "行业", "主题", "策略"] as const;
type CategoryFilter = (typeof CATEGORIES)[number];

type ColumnKey =
  | "close"
  | "change_pct"
  | "change_52w"
  | "high_all"
  | "pe"
  | "pe_pct"
  | "pb"
  | "pb_pct"
  | "dividend"
  | "erp"
  | "dividend_pct"
  | "erp_pct"
  | "position";

const COLUMNS: ReadonlyArray<{ key: ColumnKey; label: string; numeric: boolean }> = [
  { key: "close", label: "收盘", numeric: true },
  { key: "change_pct", label: "今日", numeric: true },
  { key: "change_52w", label: "52 周", numeric: true },
  { key: "high_all", label: "区间最高", numeric: true },
  { key: "pe", label: "PE", numeric: true },
  { key: "pe_pct", label: "PE 分位", numeric: true },
  { key: "pb", label: "PB", numeric: true },
  { key: "pb_pct", label: "PB 分位", numeric: true },
  { key: "dividend", label: "股息率", numeric: true },
  { key: "erp", label: "ERP", numeric: true },
  { key: "dividend_pct", label: "股息率分位", numeric: true },
  { key: "erp_pct", label: "ERP 分位", numeric: true },
  { key: "position", label: "52 周位置", numeric: true },
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
  "position",
];

const PAGE_SIZE = 60;
const PROXY_ORDER = ["000016", "000300", "000510", "000905", "000852"];
const BOARD_ORDER = ["all", "main", "chinext", "star", "bse"];

export interface ValuationHomeProps {
  rows: IndexQuoteRow[];
  proxies: BroadProxyCard[];
  boards: MarketValuationCard[];
  history: ValuationHistory | null;
  asOf: string;
  total: number;
  defaultWindow: PercentileWindow;
}

function cellValue(row: IndexQuoteRow, key: ColumnKey): number | null {
  switch (key) {
    case "close":
      return row.close;
    case "change_pct":
      return row.change_pct;
    case "change_52w":
      return row.change_52w_pct;
    case "high_all":
      return row.high_all ?? null;
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
    default:
      return null;
  }
}

export function ValuationHome({
  rows: initialRows,
  proxies: initialProxies,
  boards,
  history: initialHistory,
  asOf,
  total,
  defaultWindow,
}: ValuationHomeProps) {
  const [window, setWindow] = useState<PercentileWindow>(defaultWindow);
  const [metric, setMetric] = useState<ValuationMetric>("pe_ttm");
  const [category, setCategory] = useState<CategoryFilter>("全部");
  const [industry, setIndustry] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<ColumnKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [columns, setColumns] = useState<ColumnKey[]>(DEFAULT_COLUMNS);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [bandMode, setBandMode] = useState<BandMode>("pct");
  const [sigma, setSigma] = useState(1);
  const [proxyCode, setProxyCode] = useState("000300");

  const [rows, setRows] = useState<IndexQuoteRow[]>(initialRows);
  const [proxies, setProxies] = useState<BroadProxyCard[]>(initialProxies);
  const [history, setHistory] = useState<ValuationHistory | null>(initialHistory);
  const [loading, setLoading] = useState(false);

  // 窗口/指标变化时重新取数（分位随窗口变化，指标影响分位列语义）
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    Promise.all([
      fetch(
        "/api/valuation/indices?limit=1000&window=" + window + "&metric=" + metric,
        { signal: controller.signal },
      )
        .then((response) => response.json())
        .then((payload) => {
          const data = Array.isArray(payload?.data) ? payload.data : [];
          return data.map((item: Record<string, unknown>) => mapIndexRow(item));
        }),
      fetch("/api/valuation/overview?window=" + window, {
        signal: controller.signal,
      })
        .then((response) => response.json())
        .then((payload) => {
          const raw = payload?.meta?.proxies;
          return Array.isArray(raw)
            ? raw.map((item: Record<string, unknown>) => mapBroadProxy(item))
            : [];
        }),
    ])
      .then(([nextRows, nextProxies]) => {
        if (!active) return;
        setRows(nextRows);
        if (nextProxies.length > 0) setProxies(nextProxies);
      })
      .catch(() => {
        /* 网络失败保留旧数据 */
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [window, metric]);

  // 选中的宽基变化 / 窗口变化 → 重新取历史序列
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetch(
      "/api/valuation/" + proxyCode + "/history?metric=pe_ttm&window=" + window,
      { signal: controller.signal },
    )
      .then((response) => response.json())
      .then((payload) => {
        if (!active) return;
        setHistory(mapValuationHistory(proxyCode, payload, "pe_ttm", window));
      })
      .catch(() => {
        /* 忽略 */
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [proxyCode, window]);

  const industries = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) if (row.industry) set.add(row.industry);
    return [...set].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [rows]);

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    let list = rows.filter((row) => {
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
  }, [rows, category, industry, search, sortKey, sortDir]);

  const visibleRows = filtered.slice(0, pageSize);
  const sortedProxies = useMemo(() => {
    const rank = new Map(PROXY_ORDER.map((code, index) => [code, index]));
    return [...proxies].sort(
      (a, b) => (rank.get(a.index_code) ?? 99) - (rank.get(b.index_code) ?? 99),
    );
  }, [proxies]);
  const sortedBoards = useMemo(() => {
    const rank = new Map(BOARD_ORDER.map((board, index) => [board, index]));
    return [...boards].sort((a, b) => (rank.get(a.board) ?? 99) - (rank.get(b.board) ?? 99));
  }, [boards]);
  const selectedProxy = sortedProxies.find((item) => item.index_code === proxyCode) ?? sortedProxies[0] ?? null;

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

  const toggleColumn = useCallback((key: ColumnKey) => {
    setColumns((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">指数估值</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>更新至 {asOf || "—"}</span>
              <span>·</span>
              <span>{total} 只指数</span>
              <span>·</span>
              <span>数据源 平安 / 中证官网 / 雪球</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-lg border border-border">
              {WINDOWS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setWindow(item.value)}
                  className={cn(
                    "px-2.5 py-1.5 text-xs transition-colors",
                    window === item.value
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* 代表性宽基：真实历史分位 */}
        <section className="mt-5">
          <SectionHeading title="代表性宽基估值" hint="按所选窗口计算真实历史分位" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {sortedProxies.map((card) => (
              <button
                key={card.index_code}
                type="button"
                onClick={() => setProxyCode(card.index_code)}
                className={cn(
                  "text-left",
                  proxyCode === card.index_code ? "ring-2 ring-primary/40 rounded-xl" : "",
                )}
              >
                <ProxyCard card={card} />
              </button>
            ))}
          </div>
        </section>

        {/* 图表区 */}
        <section className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Surface className="p-4 xl:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium">
                  {selectedProxy ? selectedProxy.name : "宽基"} · PE-Band
                </h3>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  估值历史与区间带；切换窗口/口径后虚线与统计同步更新
                </p>
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
                          sigma === value
                            ? "bg-foreground text-background"
                            : "text-muted-foreground",
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
              <div className="mt-2">
                <PeBandChart
                  key={proxyCode + window + bandMode + String(sigma)}
                  series={history.series}
                  stats={history.stats}
                  metric="pe_ttm"
                  mode={bandMode}
                  sigma={sigma}
                  title={WINDOWS.find((item) => item.value === window)?.label ?? ""}
                />
              </div>
            ) : (
              <div className="mt-6 rounded-lg border border-dashed border-border p-8 text-center text-xs text-muted-foreground">
                该指数暂无估值序列
              </div>
            )}
          </Surface>

          <Surface className="p-4">
            <h3 className="text-sm font-medium">行业估值热力</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              PE 分位均值 · 点击色块筛选行业
            </p>
            <div className="mt-3">
              <IndustryHeatmap
                rows={rows}
                onSelect={(value) => {
                  setIndustry(value);
                  setCategory("全部");
                }}
              />
            </div>
            <div className="mt-3 text-[11px] text-muted-foreground">
              共 {industries.length} 个行业 · 按分位从高到低排序
            </div>
          </Surface>
        </section>

        <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Surface className="p-4 xl:col-span-2">
            <h3 className="text-sm font-medium">估值矩阵</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              横轴 PE 分位、纵轴 PB 分位；越靠右上估值越贵
            </p>
            <div className="mt-2">
              <ValuationMatrix rows={rows} />
            </div>
          </Surface>
          <Surface className="p-4">
            <h3 className="text-sm font-medium">全市场截面</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              东财收盘截面（分位需积累 ≥60 个交易日后启用）
            </p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {sortedBoards.slice(0, 4).map((board) => {
                const ready = board.history_days >= 60;
                return (
                  <div key={board.board} className="rounded-lg border border-border p-2.5">
                    <div className="text-[11px] text-muted-foreground">{board.label}</div>
                    <div className="mt-0.5 text-lg font-semibold tabular-nums">
                      {board.pe == null ? "—" : board.pe.toFixed(2)}
                      <span className="ml-1 text-[10px] font-normal text-muted-foreground">PE</span>
                    </div>
                    <div className="text-[11px] tabular-nums text-muted-foreground">
                      PB {board.pb == null ? "—" : board.pb.toFixed(2)} ·{" "}
                      {ready && board.pe_percentile != null
                        ? "分位 " + board.pe_percentile.toFixed(0) + "%"
                        : "分位 " + board.history_days + "/60"}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-3 text-[11px] text-muted-foreground">
              截面样本 {sortedBoards[0]?.sample_size ?? 0} 只 · 每日 21:20 采集
            </div>
          </Surface>
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
              <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
                {METRICS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setMetric(item.value)}
                    className={cn(
                      "px-2 py-1.5",
                      metric === item.value
                        ? "bg-foreground text-background"
                        : "text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
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
            {loading ? (
              <span className="ml-1 text-[11px] text-muted-foreground">更新中…</span>
            ) : null}
          </div>

          <div className="mt-3 overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                  <th className="sticky left-0 z-10 bg-muted/40 px-3 py-2 text-left font-medium">
                    指数
                  </th>
                  {COLUMNS.filter((column) => columns.includes(column.key)).map((column) => (
                    <th key={column.key} className="px-3 py-2 text-right font-medium">
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
                        <span className="text-sm font-medium group-hover:text-primary">
                          {row.name}
                        </span>
                        <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                          {row.index_code}
                        </span>
                        <span className="ml-2 text-[10px] text-muted-foreground">
                          {row.category}
                          {row.industry ? " · " + row.industry : ""}
                        </span>
                      </Link>
                    </td>
                    {COLUMNS.filter((column) => columns.includes(column.key)).map((column) => {
                      const value = cellValue(row, column.key);
                      if (column.key === "position") {
                        return (
                          <td key={column.key} className="px-3 py-2">
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-16">
                                <PercentileBar value={row.position_52w_pct ?? null} />
                              </div>
                              <span className="w-9 text-right font-mono text-xs tabular-nums text-muted-foreground">
                                {value == null ? "—" : value.toFixed(0) + "%"}
                              </span>
                            </div>
                          </td>
                        );
                      }
                      if (column.key === "pe_pct" || column.key === "pb_pct") {
                        return (
                          <td key={column.key} className="px-3 py-2 text-right">
                            <span className={cn("font-mono text-xs tabular-nums", percentileTone(value))}>
                              {value == null ? "—" : value.toFixed(1) + "%"}
                            </span>
                          </td>
                        );
                      }
                      if (column.key === "change_pct" || column.key === "change_52w") {
                        return (
                          <td key={column.key} className={cn("px-3 py-2 text-right font-mono text-xs tabular-nums", changeClass(value))}>
                            {formatSignedPct(value)}
                          </td>
                        );
                      }
                      if (column.key === "dividend") {
                        return (
                          <td key={column.key} className="px-2 py-2 text-right font-mono text-xs tabular-nums">
                            {value == null ? "—" : value.toFixed(2) + "%"}
                          </td>
                        );
                      }
                      return (
                        <td key={column.key} className="px-2 py-2 text-right font-mono text-xs tabular-nums">
                          {formatNumber(value, 2)}
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
              显示 {visibleRows.length} / {filtered.length} 只
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

        <p className="mt-6 text-[11px] leading-5 text-muted-foreground">
          分位口径：PE/PB/股息率/ERP 分别基于 2021-11 起的周频估值序列；1 年窗口按 40 个样本门槛、其余窗口按 120
          个样本门槛，样本不足统一显示「—」。数据区间最高点为可获取行情区间的最高收盘，非交易所全历史最高。
        </p>
      </div>
    </div>
  );
}
