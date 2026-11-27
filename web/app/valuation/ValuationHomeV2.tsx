"use client";

/**
 * /valuation v2 内容区（纯展示，不发起首屏数据请求）。
 *
 * 数据获取策略（2026-11 性能改造）：
 * - 首页快照由服务端一次取全（4 指标分位 + 默认指数 4 指标历史），首屏后指标 tab 切换
 *   只改本地 state（150ms 交叉淡入），**不再发任何 list 请求**；
 * - 指数选择器 4 只（沪深300/中证A500/上证50/中证全指）：切换时只取该指数的 4 指标历史，
 *   图表/右栏局部 skeleton，不整页 loading；
 * - 窗口切换才刷新列表分位（服务端窗口口径），并提示局部加载状态；
 * - 任一接口失败保留上次数据/显示局部错误态，绝不伪造数据。
 */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronDown,
  RotateCcw,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type {
  BroadProxyCard,
  IndexQuoteRow,
  MviInfo,
  PercentileWindow,
  ValuationHistory,
  ValuationMetric,
} from "@/lib/valuation-types";
import { changeClass, formatSignedPct } from "@/lib/valuation-mock";
import {
  BAND_INDEX_OPTIONS,
  DEFAULT_BAND_INDEX,
  deriveProxyCards,
  fetchBandHistories,
  fetchIndexHistory,
  fetchIndexSnapshot,
  fetchMvi,
} from "@/lib/valuation-snapshot";
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
  type DividendMode,
} from "./_components/valuation-v2";
import {
  ChartSkeleton,
  CrossFade,
  DataEmptyState,
  InfoTip,
  LevelBadge,
  PercentileBar,
  percentileLabel,
  percentileTone,
  SectionHeading,
  ValueSkeleton,
} from "./_components/valuation-ui";

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

type MetricSlice = { value: number | null; pct: number | null; unit: string };

/** 从快照行取某指标的当前值 + 分位（4 个指标一次取全，切换不再请求）。 */
function metricSlice(row: IndexQuoteRow | null, metric: ValuationMetric): MetricSlice {
  if (!row) return { value: null, pct: null, unit: "" };
  switch (metric) {
    case "pe_ttm":
      return { value: row.pe_ttm, pct: row.pe_percentile, unit: "x" };
    case "pb":
      return { value: row.pb, pct: row.pb_percentile, unit: "x" };
    case "dividend_yield_ttm":
      return { value: row.dividend_yield_pct, pct: row.dividend_percentile ?? null, unit: "%" };
    case "erp":
      return { value: row.risk_premium_pct, pct: row.erp_percentile ?? null, unit: "%" };
    default:
      return { value: null, pct: null, unit: "" };
  }
}

function formatMetricValue(value: number | null, unit: string): string {
  if (value == null) return "—";
  return value.toFixed(2) + unit;
}

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

/** URL 同步用原生 history API：不触发 RSC 重新请求（指标/窗口切换零网络）。 */
function replaceQuery(params: { window?: PercentileWindow; metric?: ValuationMetric }) {
  if (typeof window === "undefined") return;
  try {
    const url = new URL(window.location.href);
    if (params.window) url.searchParams.set("window", params.window);
    if (params.metric) url.searchParams.set("metric", params.metric);
    window.history.replaceState(null, "", url.toString());
  } catch {
    // 忽略：URL 同步失败不影响本地交互
  }
}

export interface ValuationHomeV2Props {
  rows: IndexQuoteRow[];
  proxies: BroadProxyCard[];
  histories: Partial<Record<ValuationMetric, ValuationHistory>>;
  mvi: MviInfo | null;
  window: PercentileWindow;
  metric: ValuationMetric;
}

export function ValuationHomeV2({
  rows: initialRows,
  proxies: initialProxies,
  histories: initialHistories,
  mvi,
  window: initialWindow,
  metric: initialMetric,
}: ValuationHomeV2Props) {
  const [rows, setRows] = useState(initialRows);
  const [window, setWindow] = useState<PercentileWindow>(initialWindow);
  const [metric, setMetric] = useState<ValuationMetric>(initialMetric);
  const [bandIndex, setBandIndex] = useState<string>(DEFAULT_BAND_INDEX);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const listRequestRef = useRef(0);
  const [dividendMode, setDividendMode] = useState<DividendMode>("absolute");
  const [mviData, setMviData] = useState<MviInfo | null>(mvi);

  // ---- 指数 × 窗口 -> 4 指标历史缓存（指标切换只读缓存，不再发请求）----
  const initialKey = DEFAULT_BAND_INDEX + ":" + initialWindow;
  const cacheRef = useRef(
    new Map<string, Partial<Record<ValuationMetric, ValuationHistory>>>(),
  );
  if (!cacheRef.current.has(initialKey)) {
    cacheRef.current.set(initialKey, initialHistories);
  }
  const pendingRef = useRef(new Set<string>());
  const singlePendingRef = useRef(new Set<string>());
  /** 单指标补拉失败过的 key；重试按钮会清空，避免失败后 effect 自动死循环。 */
  const failedSingleRef = useRef(new Set<string>());
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const [cacheVersion, bumpCache] = useReducer((value: number) => value + 1, 0);

  // 切换指数/窗口：一次并行拉取该指数 4 个指标的历史（失败只影响图表区）。
  // 注意：请求结果按 key 缓存且不随 effect 清理丢弃 —— 快速切走再切回时可直接命中，
  // 否则「切回时旧请求仍在途 → 归来后被丢弃 → 无状态变更触发补拉」会停在永久骨架。
  useEffect(() => {
    const key = bandIndex + ":" + window;
    if (cacheRef.current.has(key) || pendingRef.current.has(key)) return;
    pendingRef.current.add(key);
    setLoadingKey(key);
    void fetchBandHistories(bandIndex, window)
      .then((histories) => {
        pendingRef.current.delete(key);
        cacheRef.current.set(key, histories);
        setLoadingKey((current) => (current === key ? null : current));
        // 4 指标全空也先交给「当前指标补拉」处理：单指标接口可能仍然可用。
        bumpCache();
      })
      .catch(() => {
        pendingRef.current.delete(key);
        setLoadingKey((current) => (current === key ? null : current));
        // 批量失败不直接判死：bump 后由「当前指标补拉」effect 再试一次，失败才进错误态。
        bumpCache();
      });
  }, [bandIndex, window, retryTick]);

  // 当前指标兜底：首屏预取或批量拉取里缺当前 metric 时，针对它再补一次。
  // 依赖 cacheVersion：批量请求完成后重新评估缓存 —— 修复「批量还在途时切到缺失指标，
  // 批量结束后不再补拉 → 永久骨架且无重试」的竞态。
  useEffect(() => {
    const key = bandIndex + ":" + window;
    const singleKey = key + ":" + metric;
    if (cacheRef.current.get(key)?.[metric]) return;
    if (pendingRef.current.has(key) || singlePendingRef.current.has(singleKey)) return;
    if (failedSingleRef.current.has(singleKey)) return;
    singlePendingRef.current.add(singleKey);
    setLoadingKey(key);
    void fetchIndexHistory(bandIndex, metric, window)
      .then((history) => {
        singlePendingRef.current.delete(singleKey);
        if (history) {
          const merged = { ...(cacheRef.current.get(key) ?? {}), [metric]: history };
          cacheRef.current.set(key, merged);
        } else {
          failedSingleRef.current.add(singleKey);
        }
        setLoadingKey((current) => (current === key ? null : current));
        bumpCache();
      })
      .catch(() => {
        singlePendingRef.current.delete(singleKey);
        failedSingleRef.current.add(singleKey);
        setLoadingKey((current) => (current === key ? null : current));
        bumpCache();
      });
  }, [metric, bandIndex, window, retryTick, cacheVersion]);

  // MVI 首屏缺失时客户端补一次（新接口未就绪时保持空态，不伪造数据）。
  useEffect(() => {
    if (mviData) return;
    let active = true;
    void fetchMvi("5y").then((data) => {
      if (active && data) setMviData(data);
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retryBand = useCallback(() => {
    const key = bandIndex + ":" + window;
    cacheRef.current.delete(key);
    pendingRef.current.delete(key);
    for (const singleKey of [...failedSingleRef.current]) {
      if (singleKey.startsWith(key + ":")) failedSingleRef.current.delete(singleKey);
    }
    setLoadingKey(key);
    setRetryTick((tick) => tick + 1);
  }, [bandIndex, window]);

  const switchMetric = useCallback((next: ValuationMetric) => {
    if (next === metric) return;
    setMetric(next);
    replaceQuery({ metric: next });
  }, [metric]);

  /** 最近一次列表快照成功对应的窗口；窗口切换失败时回滚到它，避免「新窗口标签 + 旧窗口分位」。 */
  const appliedWindowRef = useRef<PercentileWindow>(initialWindow);
  const windowLabelOf = (value: PercentileWindow) =>
    V2_WINDOWS.find((item) => item.value === value)?.label ?? value;

  const switchWindow = useCallback(
    (next: PercentileWindow) => {
      if (next === window) return;
      const fallbackWindow = appliedWindowRef.current;
      setWindow(next);
      replaceQuery({ window: next, metric });
      setListLoading(true);
      setListError(null);
      // 连续快速切窗口时只认最后一次请求的结果，避免旧响应覆盖新窗口数据。
      listRequestRef.current += 1;
      const requestId = listRequestRef.current;
      const fail = () => {
        if (requestId !== listRequestRef.current) return;
        // 失败回滚：窗口标签、图表窗口与列表分位必须保持同一口径，不能只改标签。
        setWindow(fallbackWindow);
        replaceQuery({ window: fallbackWindow, metric });
        setListError(
          "「" +
            windowLabelOf(next) +
            "」列表数据更新失败，已回滚到「" +
            windowLabelOf(fallbackWindow) +
            "」并保留原结果",
        );
      };
      void fetchIndexSnapshot({ window: next, metric })
        .then((snapshot) => {
          if (requestId !== listRequestRef.current) return;
          if (snapshot) {
            appliedWindowRef.current = next;
            setRows(snapshot.rows);
          } else {
            fail();
          }
        })
        .catch(fail)
        .finally(() => {
          if (requestId === listRequestRef.current) setListLoading(false);
        });
    },
    [window, metric],
  );

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
  const proxyCards = useMemo(() => {
    const derived = deriveProxyCards(rows, window);
    return derived.length > 0 ? derived : initialProxies;
  }, [rows, window, initialProxies]);

  const bandRow = useMemo(
    () => rows.find((row) => row.index_code === bandIndex) ?? null,
    [rows, bandIndex],
  );
  const bandOption = BAND_INDEX_OPTIONS.find((item) => item.code === bandIndex) ?? BAND_INDEX_OPTIONS[0];
  const slice = metricSlice(bandRow, metric);
  const currentKey = bandIndex + ":" + window;
  const currentHistories = cacheRef.current.get(currentKey) ?? {};
  const history = currentHistories[metric] ?? null;
  const singleFailed = failedSingleRef.current.has(currentKey + ":" + metric);
  // 无数据且当前指标补拉尚未失败 = 仍在加载/补拉（含批量在途与失败后的自动补拉），
  // 一律显示骨架；只有补拉也失败才进入可重试错误态，避免失败瞬间闪错。
  const bandPending = loadingKey === currentKey || (!history && !singleFailed);
  const listAsOf = rows.length
    ? rows
        .map((row) => row.trade_date)
        .filter(Boolean)
        .sort()
        .at(-1) ?? null
    : null;
  const windowLabel = V2_WINDOWS.find((item) => item.value === window)?.label ?? window;

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
    <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 sm:px-6 lg:px-8">
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-muted-foreground">
          指标切换本地完成、不整页刷新；数据截至 {listAsOf ?? "—"}
          {listLoading ? " · 列表更新中…" : ""}
          {listError ? " · " + listError : ""}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {V2_WINDOWS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => switchWindow(item.value)}
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

      {rows.length === 0 ? (
        <div className="mt-4 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          估值数据暂不可用（接口未就绪或上游数据失败），页面以空态展示；恢复后会自动更新。
        </div>
      ) : null}

      {/* 代表性宽基：快照为空时给明确空态（服务端首屏已取数，无客户端加载阶段），
          不能停在永久骨架。 */}
      <section className="mt-4">
        {proxyCards.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {proxyCards.map((card) => (
              <ProxyCard key={card.index_code} card={card} />
            ))}
          </div>
        ) : (
          <DataEmptyState
            title="宽基估值卡数据建设中"
            description={
              rows.length === 0
                ? "估值快照暂不可用（接口未就绪或上游数据失败）；恢复后本区域自动展示，无需刷新页面。"
                : "代表性宽基（上证50 / 沪深300 / 中证A500 / 中证500 / 中证1000）的估值分位尚未返回。"
            }
          />
        )}
      </section>

      {/* 主图 + 行业热力 */}
      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title={bandOption.name + " · Valuation Band"}
          desc={METRIC_LABEL[metric] + " · " + windowLabel}
          className="xl:col-span-2"
          aside={
            <div
              className="inline-flex overflow-hidden rounded-md border border-border text-[11px]"
              role="group"
              aria-label="选择指数"
            >
              {BAND_INDEX_OPTIONS.map((item) => (
                <button
                  key={item.code}
                  type="button"
                  onClick={() => setBandIndex(item.code)}
                  aria-pressed={bandIndex === item.code}
                  className={cn(
                    "px-2 py-1 transition-colors",
                    bandIndex === item.code
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {item.name}
                </button>
              ))}
            </div>
          }
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
              {V2_METRICS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => switchMetric(item.value)}
                  className={cn(
                    "px-2.5 py-1 transition-colors",
                    metric === item.value
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted",
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

          <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {bandPending && !history ? (
              <ValueSkeleton lines={1} className="py-1" />
            ) : (
              <>
                <span className="text-foreground">
                  {METRIC_LABEL[metric]} 当前 <b className="font-mono tabular-nums">{formatMetricValue(slice.value, slice.unit)}</b>
                </span>
                <span>
                  {windowLabel}分位{" "}
                  <b className={cn("font-mono tabular-nums", percentileTone(slice.pct))}>
                    {slice.pct == null ? "—" : slice.pct.toFixed(1) + "%"}
                  </b>
                </span>
                <LevelBadge level={percentileLabel(slice.pct)} />
                <span>数据截至 {bandRow?.trade_date ?? "—"}</span>
                {bandRow?.coverage_start ? (
                  <span>估值自 {bandRow.coverage_start.slice(0, 7)} 起</span>
                ) : null}
              </>
            )}
          </div>

          <CrossFade fadeKey={currentKey + ":" + metric}>
            {history ? (
              <PeBandChart
                series={history.series}
                stats={history.stats}
                metric={metric}
                mode={bandMode}
                sigma={sigma}
                frequency="周线"
              />
            ) : bandPending ? (
              <ChartSkeleton height={280} label="估值带加载中" />
            ) : (
              // 加载已结束但仍无当前指标序列（批量失败 / 单指标补拉失败）：
              // 固定显示可重试错误态，绝不停在永久骨架。
              <div className="flex h-[280px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-xs text-muted-foreground">
                <span>该指数「{METRIC_LABEL[metric]}」历史序列加载失败</span>
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={retryBand}>
                  <RotateCcw className="mr-1 size-3" />
                  重试
                </Button>
              </div>
            )}
          </CrossFade>
        </ChartCard>

        <ChartCard
          title="行业估值热力"
          desc="PE 分位均值，颜色越高表示越贵"
          titleExtra={
            <InfoTip label="行业估值热力">
              <p className="font-medium">行业估值热力</p>
              <p className="mt-1">
                该行业下所有跟踪指数的 PE-TTM {windowLabel}分位均值；样本数 = 参与计算的指数数量；分位越低越便宜。
              </p>
              <p className="mt-1">
                点击方格可筛选下方列表 · 数据截至 {listAsOf ?? "—"} · 窗口 {windowLabel}
              </p>
            </InfoTip>
          }
        >
          <IndustryHeatmap
            rows={rows}
            onSelect={(value) => setIndustry(value)}
            windowLabel={windowLabel}
            asOf={listAsOf}
          />
        </ChartCard>
      </section>

      {/* 红利指数吸引力 + 全市场截面 */}
      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title="红利指数吸引力"
          desc={
            dividendMode === "relative"
              ? "PB 5y 分位 × 股息率 5y 分位；左下（低 PB 分位 + 高股息分位）最具吸引力"
              : "股息率 × PB（对数轴），气泡=跟踪基金规模；左上（低 PB + 高股息）最具吸引力"
          }
          className="xl:col-span-2"
          aside={
            <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]">
              <button
                type="button"
                onClick={() => setDividendMode("absolute")}
                aria-pressed={dividendMode === "absolute"}
                className={cn(
                  "px-2 py-1",
                  dividendMode === "absolute" ? "bg-foreground text-background" : "text-muted-foreground",
                )}
              >
                绝对估值
              </button>
              <button
                type="button"
                onClick={() => setDividendMode("relative")}
                aria-pressed={dividendMode === "relative"}
                className={cn(
                  "px-2 py-1",
                  dividendMode === "relative" ? "bg-foreground text-background" : "text-muted-foreground",
                )}
              >
                相对估值
              </button>
            </div>
          }
        >
          <DividendValueChart rows={rows} mode={dividendMode} />
        </ChartCard>
        <ChartCard
          title="市场估值指数 MVI"
          desc="周频 · 双仪表盘 · 每日 23:50 更新"
          titleExtra={
            <InfoTip label="MVI 说明">
              <p className="font-medium">市场估值指数 MVI</p>
              <p className="mt-1">MVI = 100 − 估值分；0 代表极度低估、100 代表极度高估（分 5 档区间）。</p>
              <p className="mt-1">周频序列按 ISO 周去重，104 周滚动分位；因子权重 v1 固定（in-sample，仅作研究参考）。</p>
            </InfoTip>
          }
        >
          <MviPanel mvi={mviData} />
        </ChartCard>
      </section>

      {/* 两张估值矩阵 */}
      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="估值矩阵 · PB 分位 × 股息率"
          desc={"PB 分位窗口：" + windowLabel + " · 回归线 + 方程 + R²；气泡=基金规模"}
        >
          <PbDividendMatrix rows={rows} />
        </ChartCard>
        <ChartCard
          title="估值矩阵 · ROE × PE"
          desc={"ROE 当前值 · PE 窗口：" + windowLabel + " · log 轴；回归线 + 方程 + R²"}
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

        {visibleRows.length === 0 ? (
          <div className="mt-3">
            <DataEmptyState
              title={rows.length === 0 ? "估值数据建设中" : "没有符合筛选条件的指数"}
              description={
                rows.length === 0
                  ? "接口未就绪或上游数据失败；恢复后列表自动展示，无需刷新页面。"
                  : "可调整搜索、类别或「有 ETF/基金」筛选条件。"
              }
            />
          </div>
        ) : (
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
                            className="ml-1.5 rounded bg-warning/20 px-1 py-0.5 text-[10px] text-warning"
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
                            ? row.close == null
                              ? "该指数暂无行情数据"
                              : "K 线历史不足 251 个交易日"
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
                      if (
                        column.key === "pe_pct" ||
                        column.key === "pb_pct" ||
                        column.key === "dividend_pct" ||
                        column.key === "erp_pct"
                      ) {
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
        )}

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
  );
}
