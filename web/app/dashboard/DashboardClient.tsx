"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { motion, AnimatePresence } from "motion/react";
import { Trash2, Pencil, RefreshCw, Star, Copy, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { EChart } from "@/components/EChart";
import { RiskMatrixSection } from "@/components/RiskMatrixSection";
import { ConfirmRecomputeDialog } from "@/components/ConfirmRecomputeDialog";
import { BacktestProgressDialog } from "@/components/BacktestProgressDialog";
import { useIsMobile } from "@/components/ui/use-mobile";
import {
  api, BacktestResult, Quadrant, QUADRANT_LABELS, PortfolioInfo, PortfolioStatus, Rebalance,
  Attribution, DEFAULT_BENCHMARK_KEY, DEFAULT_MAX_WEIGHT_PCT, BENCHMARK_OPTIONS, BENCHMARK_COMPOSITION,
  DEFAULT_DESCRIPTION, methodLabel,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useQueryClient } from "@tanstack/react-query";
import { fetchResult, invalidatePortfolio, qk } from "@/lib/queries";

const ZERO_EPS = 0.0005; // 隐藏 < 0.05% 的权重噪声
const HOLDINGS_DISPLAY_MIN = 0.05; // 勾选「不显示低于5%」时的合并阈值

const QUADRANT_ORDER: Quadrant[] = ["overheat", "stagflation", "recovery", "recession"];
const QUADRANT_COLOR: Record<Quadrant, string> = {
  overheat: "text-up", stagflation: "text-weak", recovery: "text-primary", recession: "text-down",
};
const PERIOD_LABELS: Record<string, string> = {
  "1d": "最近一日", "1w": "近一周", "1m": "近一月", "3m": "近三月",
  "6m": "近半年", "1y": "近一年", "3y": "近三年", "ytd": "年初至今", "annualized": "年化",
};
const PERIOD_KEYS = ["1d", "1w", "1m", "3m", "6m", "1y", "3y", "ytd", "annualized"];

function pct(x: number | null | undefined, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return "-";
  return `${(x * 100).toFixed(digits)}%`;
}
function signPct(x: number | null | undefined, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return "-";
  return `${x > 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;
}

export default function DashboardClient({
  initialDemo = null,
}: {
  initialDemo?: BacktestResult | null;
}) {
  return (
    <Suspense fallback={<div className="p-12 text-center text-muted-foreground">加载中...</div>}>
      <DashboardInner initialDemo={initialDemo} />
    </Suspense>
  );
}

function DashboardInner({ initialDemo = null }: { initialDemo?: BacktestResult | null }) {
  const params = useSearchParams();
  const router = useRouter();
  const idParam = params.get("id");
  const { isWhitelisted } = useAuth();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const queryClient = useQueryClient();
  const pidNum = idParam ? Number(idParam) : null;

  const [cache, setCache] = useState<Record<string, BacktestResult>>({});
  const [method, setMethod] = useState<string | null>(null);
  const [benchmark, setBenchmark] = useState<string | null>(null);
  const [portfolios, setPortfolios] = useState<PortfolioInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningStatus, setRunningStatus] = useState<PortfolioStatus | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const reloadPortfolios = () => {
    api.listPortfolios().then((r) => setPortfolios(r.portfolios)).catch(() => {});
  };

  const reloadResult = () => {
    invalidatePortfolio(queryClient, pidNum);
    setReloadToken((t) => t + 1);
  };

  const cacheKey = (m: string, b: string) => `${m}::${b}`;
  const fetcher = (m?: string, b?: string) => fetchResult(queryClient, pidNum, m, b);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setRunningStatus(null);
    setCache({});
    setMethod(null);
    setBenchmark(null);

    if (initialDemo && pidNum == null && reloadToken === 0) {
      const m = initialDemo.method || "default";
      const b = initialDemo.benchmark || DEFAULT_BENCHMARK_KEY;
      setCache({ [cacheKey(m, b)]: initialDemo });
      setMethod(m);
      setBenchmark(b);
      queryClient.setQueryData(qk.result(null, m, b), initialDemo);
      setLoading(false);
      reloadPortfolios();
      return;
    }

    fetcher()
      .then((res) => {
        const m = res.method || "default";
        const b = res.benchmark || DEFAULT_BENCHMARK_KEY;
        setCache({ [cacheKey(m, b)]: res });
        setMethod(m);
        setBenchmark(b);
      })
      .catch(async (e) => {
        const msg = String(e instanceof Error ? e.message : e);
        if (msg.includes("回测进行中") && idParam) {
          try {
            const st = await api.getPortfolioStatus(Number(idParam));
            setRunningStatus(st);
          } catch {
            setError(msg);
          }
        } else if (msg.includes("回测进行中") && !idParam) {
          try {
            const r = await api.listPortfolios();
            const fallback = r.portfolios.find((p) => p.is_demo && p.status === "done");
            if (fallback) {
              router.replace(`/dashboard?id=${fallback.portfolio_id}`);
              return;
            }
            setError(msg);
          } catch {
            setError(msg);
          }
        } else {
          setError(msg);
        }
      })
      .finally(() => setLoading(false));
    reloadPortfolios();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idParam, reloadToken]);

  const switchTo = (m: string, b: string) => {
    if (m === method && b === benchmark) return;
    const k = cacheKey(m, b);
    if (cache[k]) {
      setMethod(m); setBenchmark(b);
      return;
    }
    setSwitching(true);
    fetcher(m, b)
      .then((res) => {
        setCache((c) => ({ ...c, [k]: res }));
        setMethod(m); setBenchmark(b);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setSwitching(false));
  };

  if (loading) return <div className="p-12 text-center text-muted-foreground">正在加载回测结果...</div>;
  if (runningStatus) return (
    <RunningPortfolioView
      status={runningStatus}
      portfolios={portfolios}
      router={router}
      onRefresh={reloadResult}
    />
  );
  if (error) return (
    <div className="max-w-3xl mx-auto p-12 text-center space-y-4">
      <p className="text-destructive">加载失败：{error}</p>
      <p className="text-sm text-muted-foreground">请确认后端已启动、数据库已建表且行情已落库(运行 bp_ingest)。</p>
      {isWhitelisted && <Button asChild><Link href="/builder">新建组合</Link></Button>}
    </div>
  );
  const data = method && benchmark ? cache[cacheKey(method, benchmark)] : null;
  if (!data) return null;

  return (
    <DashboardView
      data={data} portfolios={portfolios} isDark={isDark} router={router} idParam={idParam}
      methods={data.available_methods || []} current={method!}
      benchmark={benchmark!} switching={switching}
      onSwitchMethod={(m) => switchTo(m, benchmark!)}
      onSwitchBenchmark={(b) => switchTo(method!, b)}
      onReload={reloadResult}
      onReloadPortfolios={reloadPortfolios}
    />
  );
}

function DashboardView({
  data, portfolios, isDark, router, idParam, methods, current,
  benchmark, switching, onSwitchMethod, onSwitchBenchmark, onReload, onReloadPortfolios,
}: {
  data: BacktestResult; portfolios: PortfolioInfo[]; isDark: boolean; router: ReturnType<typeof useRouter>; idParam: string | null;
  methods: string[]; current: string; benchmark: string; switching: boolean;
  onSwitchMethod: (m: string) => void; onSwitchBenchmark: (b: string) => void;
  onReload: () => void; onReloadPortfolios: () => void;
}) {
  const { userId, isWhitelisted, isSuperAdmin } = useAuth();
  const { portfolio, nav, rebalances, metrics, holdings, optimal_holdings, corr, quadrant_weights: quadrantWeights } = data;
  const mPort = metrics.portfolio;
  const mBench = metrics.benchmark;

  const textCol = isDark ? "#A1A1A1" : "#666666";
  const axisLineCol = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
  const splitLineCol = isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)";
  const cardBg = isDark ? "#161616" : "#ffffff";
  const fg = isDark ? "#EDEDED" : "#171717";
  const primary = "#3B82F6";
  const benchName = data.benchmark_name || benchmarkName(portfolio);
  const bandPct = portfolio.rebalance_band != null
    ? +(portfolio.rebalance_band * 100).toFixed(1)
    : 5;

  // key -> display name
  const nameMap = useMemo(() => {
    const m: Record<string, string> = {};
    holdings.forEach((h) => (m[h.key] = h.name || h.key));
    (portfolio.assets || []).forEach((a) => (m[`${a.symbol}@${a.source}`] = a.display_name || a.symbol));
    return m;
  }, [holdings, portfolio.assets]);

  // ---- 净值区间过滤 ----
  const [range, setRange] = useState<"1y" | "3y" | "all">("all");
  const navFiltered = useMemo(() => {
    if (range === "all") return nav;
    const days = range === "1y" ? 244 : 244 * 3;
    return nav.slice(Math.max(0, nav.length - days));
  }, [nav, range]);

  const navDisplay = useMemo(() => {
    if (!navFiltered.length) return [];
    const n0 = navFiltered[0].nav;
    const b0 = navFiltered[0].benchmark_nav;
    return navFiltered.map((d) => ({
      ...d,
      nav: n0 ? d.nav / n0 : d.nav,
      benchmark_nav: b0 != null && d.benchmark_nav != null ? d.benchmark_nav / b0 : d.benchmark_nav,
    }));
  }, [navFiltered]);

  // ---- 调仓期选择 ----
  const [rbIdx, setRbIdx] = useState(rebalances.length - 1);
  const [hideSmallHoldings, setHideSmallHoldings] = useState(true);
  const [showOptimalHoldings, setShowOptimalHoldings] = useState(false);
  const rebalancesDesc = useMemo(
    () => rebalances.map((r, idx) => ({ r, idx })).reverse(),
    [rebalances],
  );
  const optimalAsOf = (optimal_holdings?.as_of_date ?? mPort?.end_date ?? nav.at(-1)?.trade_date ?? "")
    .slice(0, 10);
  const hasOptimalHoldings = (optimal_holdings?.holdings?.length ?? 0) > 0;
  // 切换方法/组合后数据变化 → 重置选中的调仓期为最近
  useEffect(() => {
    setRbIdx(rebalances.length - 1);
    setShowOptimalHoldings(false);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const rb = rebalances[Math.min(rbIdx, rebalances.length - 1)];

  const holdingsAtRb = useMemo(() => {
    if (!rb?.target_weights) return [];
    return Object.entries(rb.target_weights)
      .filter(([, w]) => w >= ZERO_EPS)
      .sort((a, b) => b[1] - a[1])
      .map(([key, weight]) => ({
        key,
        name: nameMap[key] || key,
        weight,
      }));
  }, [rb, nameMap]);

  const holdingsAtOptimal = useMemo(() => {
    if (!optimal_holdings?.holdings?.length) return [];
    return optimal_holdings.holdings
      .filter((h) => h.weight >= ZERO_EPS)
      .sort((a, b) => b.weight - a.weight)
      .map((h) => ({
        key: h.key,
        name: h.name || nameMap[h.key] || h.key,
        weight: h.weight,
      }));
  }, [optimal_holdings, nameMap]);

  const visibleHoldings = showOptimalHoldings && hasOptimalHoldings ? holdingsAtOptimal : holdingsAtRb;

  const displayHoldings = useMemo(() => {
    if (!hideSmallHoldings) {
      return visibleHoldings.map((h) => ({ ...h, isOther: false as const }));
    }
    const major = visibleHoldings.filter((h) => h.weight >= HOLDINGS_DISPLAY_MIN);
    const minorSum = visibleHoldings
      .filter((h) => h.weight < HOLDINGS_DISPLAY_MIN)
      .reduce((s, h) => s + h.weight, 0);
    const rows = major.map((h) => ({ ...h, isOther: false as boolean }));
    if (minorSum > ZERO_EPS) {
      rows.push({ key: "__other__", name: "其他", weight: minorSum, isOther: true });
    }
    return rows;
  }, [visibleHoldings, hideSmallHoldings]);

  const pieOption = useMemo(() => ({
    tooltip: {
      trigger: "item", backgroundColor: cardBg, textStyle: { color: fg },
      valueFormatter: (v: number) => pct(v),
    },
    series: [{
      name: "资产占比", type: "pie", radius: ["50%", "70%"],
      itemStyle: { borderColor: cardBg, borderWidth: 2 }, label: { show: false },
      data: displayHoldings.map((h) => ({
        value: +h.weight.toFixed(4),
        name: h.name,
      })),
    }],
  }), [displayHoldings, cardBg, fg]);
  const weightMap = useMemo(
    () => Object.fromEntries(visibleHoldings.map((h) => [h.key, h.weight])),
    [visibleHoldings]
  );
  const multiQuadKeys = useMemo(() => {
    const s = new Set<string>();
    holdings.forEach((h) => {
      const qs = h.quadrants?.length ? h.quadrants : (h.quadrant ? [h.quadrant] : []);
      if (qs.length > 1) s.add(h.key);
    });
    return s;
  }, [holdings]);

  const byQuadrant = useMemo(() => {
    type QItem = { key: string; name: string; weight: number; multi: boolean };
    const g: Record<Quadrant, QItem[]> = { overheat: [], stagflation: [], recovery: [], recession: [] };
    (portfolio.assets || []).forEach((a) => {
      const key = `${a.symbol}@${a.source}`;
      const w = weightMap[key] ?? 0;
      if (w < ZERO_EPS) return;
      g[a.quadrant].push({
        key,
        name: a.display_name || nameMap[key] || a.symbol,
        weight: w,
        multi: multiQuadKeys.has(key),
      });
    });
    return g;
  }, [portfolio.assets, weightMap, nameMap, multiQuadKeys]);

  const navOption = {
    tooltip: {
      trigger: "axis", backgroundColor: cardBg, borderColor: axisLineCol,
      textStyle: { color: fg, fontFamily: "monospace" }, axisPointer: { type: "cross" },
      valueFormatter: (v: number) => (v == null ? "-" : Number(v).toFixed(4)),
    },
    legend: { data: ["组合净值", benchName], textStyle: { color: textCol }, top: 0 },
    grid: { top: 40, right: 20, bottom: 30, left: 50 },
    xAxis: {
      type: "category", data: navDisplay.map((d) => d.trade_date),
      axisLabel: { color: textCol }, axisLine: { lineStyle: { color: axisLineCol } },
    },
    yAxis: {
      type: "value", scale: true, axisLabel: { color: textCol },
      splitLine: { lineStyle: { color: splitLineCol } },
    },
    series: [
      {
        name: "组合净值", type: "line", showSymbol: false, smooth: true,
        data: navDisplay.map((d) => d.nav),
        lineStyle: { width: 2, color: primary },
        areaStyle: {
          color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [
            { offset: 0, color: "rgba(59,130,246,0.3)" }, { offset: 1, color: "rgba(59,130,246,0)" }] },
        },
      },
      {
        name: benchName, type: "line", showSymbol: false, smooth: true,
        data: navDisplay.map((d) => d.benchmark_nav),
        lineStyle: { width: 1.5, type: "dashed", color: "#A1A1A1" },
      },
    ],
  };

  // 日收益率分布
  const distOption = useMemo(
    () => buildDistOption(navDisplay, isDark, cardBg, fg, textCol, axisLineCol, splitLineCol, benchName),
    [navDisplay, isDark, cardBg, fg, textCol, axisLineCol, splitLineCol, benchName],
  );

  const demoPortfolios = portfolios.filter((p) => p.is_demo);
  const otherPortfolios = portfolios.filter((p) => !p.is_demo);
  const selectValue = idParam ?? String(portfolio.portfolio_id);
  const allPortfolios = [...demoPortfolios, ...otherPortfolios];
  const canEdit = isSuperAdmin || (!!userId && !portfolio.is_demo && portfolio.owner_user_id === userId);
  const canCopy = isWhitelisted && (portfolio.is_demo || portfolio.owner_user_id === userId || isSuperAdmin);
  const bestMethod = data.method_summaries?.find((m) => m.is_best_total_return)?.method;

  return (
    <div className="flex-1 px-4 py-4 sm:p-6 max-w-7xl mx-auto w-full space-y-4 sm:space-y-6">
      {/* Top bar */}
      <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
        <div className="px-5 pt-5 pb-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{portfolio.name}</h1>
              {portfolio.is_demo && (
                <Badge variant="secondary" className="font-normal shrink-0">Demo</Badge>
              )}
              {mPort && (
                <Badge variant="outline" className="font-normal text-muted-foreground shrink-0">
                  {mPort.end_date} 更新
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {portfolio.description || DEFAULT_DESCRIPTION}
            </p>
          </div>
          {isWhitelisted && (
            <Button size="sm" className="shrink-0 rounded-full px-4" asChild>
              <Link href="/builder">新增方案</Link>
            </Button>
          )}
        </div>

        <div className="px-4 sm:px-5 py-3 border-t border-border bg-muted/20 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 min-w-0 w-full lg:w-auto">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide shrink-0">
              组合
            </span>
            <Select
              value={selectValue}
              onValueChange={(v) => router.push(`/dashboard?id=${v}`)}
            >
              <SelectTrigger size="sm" className="w-full sm:w-[min(100%,20rem)] bg-background">
                <SelectValue placeholder="选择组合" />
              </SelectTrigger>
              <SelectContent align="start" className="max-w-[min(24rem,90vw)]">
                {demoPortfolios.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>示例组合</SelectLabel>
                    {demoPortfolios.map((p) => (
                      <SelectItem key={p.portfolio_id} value={String(p.portfolio_id)}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
                {otherPortfolios.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>其他组合</SelectLabel>
                    {otherPortfolios.map((p) => (
                      <SelectItem key={p.portfolio_id} value={String(p.portfolio_id)}>
                        {p.name} #{p.portfolio_id}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
              </SelectContent>
            </Select>
            {isWhitelisted && allPortfolios.length > 1 && (
              <ReorderDialog portfolios={allPortfolios} onSaved={onReloadPortfolios} />
            )}
          </div>

          {isWhitelisted && (
            <div className="flex flex-wrap items-center gap-1.5 w-full lg:w-auto lg:shrink-0">
              {canEdit && (
                <Button variant="outline" size="sm" asChild>
                  <a href={`/builder?id=${portfolio.portfolio_id}`}>
                    <Pencil className="w-3.5 h-3.5" />
                    编辑
                  </a>
                </Button>
              )}
              {canEdit && <RecomputeButton portfolioId={portfolio.portfolio_id} onDone={onReload} />}
              {canCopy && <CopyButton portfolioId={portfolio.portfolio_id} router={router} />}
              {isSuperAdmin && (
                <DemoToggleButton
                  portfolioId={portfolio.portfolio_id}
                  isDemo={portfolio.is_demo}
                  onChanged={() => { onReloadPortfolios(); onReload(); }}
                />
              )}
              {canEdit && (
                <DeleteButton
                  portfolioId={portfolio.portfolio_id}
                  name={portfolio.name}
                  onDeleted={() => {
                    const fallback = allPortfolios.find((p) => p.portfolio_id !== portfolio.portfolio_id);
                    router.push(fallback ? `/dashboard?id=${fallback.portfolio_id}` : "/dashboard");
                  }}
                />
              )}
            </div>
          )}
        </div>
      </div>

      <PortfolioParamsCard portfolio={portfolio} currentMethod={current} />

      {/* 优化方法选择框 */}
      <div className="bg-card border border-border rounded-xl p-2 flex flex-wrap items-center gap-1.5 sm:gap-2">
        <span className="text-sm text-muted-foreground px-2 shrink-0">优化方法</span>
        {methods.map((m) => {
          const active = m === current;
          return (
            <button
              key={m}
              onClick={() => onSwitchMethod(m)}
              disabled={switching}
              className={`relative text-xs sm:text-sm px-2 sm:px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-60 ${
                active ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {active && (
                <motion.span
                  layoutId="methodPill"
                  className="absolute inset-0 rounded-lg bg-primary/10"
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <span className="relative inline-flex items-center gap-1">
                {methodLabel(m)}
                {bestMethod === m && (
                  <span title="该方法在完整回测区间 total_return 最高，不代表未来收益"
                    className="inline-flex items-center gap-0.5 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                    <Star className="w-3 h-3 fill-primary" /> 最佳收益
                  </span>
                )}
              </span>
            </button>
          );
        })}
        {switching && <span className="text-xs text-muted-foreground animate-pulse ml-1">计算切换中...</span>}
      </div>

      <AnimatePresence mode="wait">
      <motion.div
        key={current}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="space-y-6"
      >

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 min-w-0">
        {/* Quadrant matrix */}
        <Card className="lg:col-span-2 min-w-0">
          <CardHeader>
            <CardTitle>经济场景四象限配置矩阵</CardTitle>
            <CardDescription>
              根据宏观经济学基本理论，将通胀与增长预期将占优资产分配至不同宏观周期环境。* 表示跨象限品种, 每个调仓期及最新持仓的资产权重见右侧持仓表
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground mb-3 md:hidden">
              宏观周期：通胀预期（横向）· 经济增长（纵向）
            </p>
            <div className="relative md:aspect-video md:max-h-[420px] border border-border rounded-lg bg-bg-subtle grid grid-cols-1 grid-rows-4 md:grid-cols-2 md:grid-rows-2">
              {QUADRANT_ORDER.map((q, i) => {
                const list = byQuadrant[q];
                const total = quadrantWeights?.[q] ?? list.reduce((s, h) => s + h.weight, 0);
                const bordersMobile = i < QUADRANT_ORDER.length - 1 ? "border-b" : "";
                const bordersDesktop = [
                  "md:border-r md:border-b", "md:border-b", "md:border-r", "",
                ][i];
                return (
                  <div
                    key={q}
                    className={`${bordersMobile} ${bordersDesktop} border-border p-3 sm:p-4 relative min-h-[120px] md:min-h-0 overflow-auto`}
                  >
                    <div className="absolute top-2 right-2 sm:top-3 sm:right-3 text-xs font-mono text-muted-foreground">
                      象限权重 {pct(total, 1)}
                    </div>
                    <div className={`text-sm font-medium mb-2 pr-16 ${QUADRANT_COLOR[q]}`}>{QUADRANT_LABELS[q]}</div>
                    <div className="flex flex-wrap gap-1.5 sm:gap-2">
                      {list.map((h) => (
                        <Badge key={`${q}-${h.key}`} variant="outline" className="bg-card text-xs font-normal">
                          {h.name}
                          {h.multi ? " *" : ` (${pct(h.weight, 1)})`}
                        </Badge>
                      ))}
                      {list.length === 0 && <span className="text-xs text-muted-foreground">—</span>}
                    </div>
                  </div>
                );
              })}
              <div className="hidden md:block absolute top-1/2 -left-6 -translate-y-1/2 -rotate-90 text-xs text-muted-foreground tracking-widest uppercase pointer-events-none">
                经济增长
              </div>
              <div className="hidden md:block absolute -bottom-6 left-1/2 -translate-x-1/2 text-xs text-muted-foreground tracking-widest uppercase pointer-events-none">
                预期通胀
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Current holdings */}
        <Card className="flex flex-col min-w-0">
          <CardHeader>
            <div className="flex flex-col gap-3">
              <div className="flex justify-between items-center gap-2">
                <CardTitle>当期持仓</CardTitle>
                <select
                  className="text-sm bg-transparent border border-border rounded px-2 py-1 text-muted-foreground focus:outline-none max-w-[160px]"
                  value={rbIdx}
                  onChange={(e) => setRbIdx(Number(e.target.value))}
                  disabled={showOptimalHoldings}
                >
                  {rebalancesDesc.map(({ r, idx }) => (
                    <option key={r.trade_date} value={idx}>
                      {r.trade_date}{idx === rebalances.length - 1 ? " (最近)" : ""}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                <Checkbox
                  id="hide-small-holdings"
                  checked={hideSmallHoldings}
                  onCheckedChange={(v) => setHideSmallHoldings(v === true)}
                />
                不显示低于5%的持仓
              </label>
              <label className={`flex items-center gap-2 text-sm select-none ${hasOptimalHoldings ? "text-muted-foreground cursor-pointer" : "text-muted-foreground/50 cursor-not-allowed"}`}>
                <Checkbox
                  id="show-optimal-holdings"
                  checked={showOptimalHoldings}
                  disabled={!hasOptimalHoldings}
                  onCheckedChange={(v) => setShowOptimalHoldings(v === true)}
                />
                显示最新优化持仓{optimalAsOf ? ` ${optimalAsOf}` : ""}
              </label>
            </div>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col">
            <div className="h-[200px] mb-4"><EChart option={pieOption} style={{ height: "100%", width: "100%" }} /></div>
            <div className="flex-1 overflow-auto max-h-[220px] pr-2 min-w-0">
              <Table className="min-w-0">
                <TableBody>
                  {displayHoldings.map((h) => (
                    <TableRow key={h.key}>
                      <TableCell className={`py-2 pl-0 font-medium ${h.isOther ? "text-muted-foreground" : ""}`}>
                        {h.name}
                      </TableCell>
                      <TableCell className="py-2 text-right font-mono">{pct(h.weight)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* NAV chart */}
        <Card>
          <CardHeader>
            <div className="flex justify-between items-center gap-2 flex-wrap">
              <CardTitle>净值走势</CardTitle>
              <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                <select
                  className="text-xs bg-transparent border border-border rounded px-2 py-1 text-muted-foreground focus:outline-none"
                  value={benchmark}
                  onChange={(e) => onSwitchBenchmark(e.target.value)}
                  disabled={switching}
                >
                  {(data.benchmarks || []).map((b) => (
                    <option key={b.key} value={b.key}>基准: {b.name}</option>
                  ))}
                </select>
                <div className="flex gap-1">
                  {(["1y", "3y", "all"] as const).map((r) => (
                    <button key={r} onClick={() => setRange(r)}
                      className={`text-xs px-2 py-1 rounded border ${range === r ? "border-primary text-primary" : "border-border text-muted-foreground"}`}>
                      {r === "1y" ? "近1年" : r === "3y" ? "近3年" : "全部"}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <CardDescription>组合 vs 基准 {benchName}</CardDescription>
            {BENCHMARK_COMPOSITION[benchmark] && (
              <div className="mt-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground leading-relaxed">
                <span className="font-medium text-foreground">基准构成 · </span>
                {BENCHMARK_COMPOSITION[benchmark].legs.map((leg, i) => (
                  <span key={leg.name}>
                    {i > 0 && " + "}
                    {(leg.weight * 100).toFixed(0)}% {leg.name}
                  </span>
                ))}
                。{BENCHMARK_COMPOSITION[benchmark].note}
              </div>
            )}
          </CardHeader>
          <CardContent><EChart option={navOption} style={{ height: 320, width: "100%" }} /></CardContent>
        </Card>

        {/* Rebalance timeline */}
        <Card>
          <CardHeader>
            <div className="flex flex-wrap justify-between items-center gap-2">
              <CardTitle>调仓变动</CardTitle>
              <select className="text-sm bg-transparent border border-border rounded px-2 py-1 text-muted-foreground focus:outline-none"
                value={rbIdx} onChange={(e) => setRbIdx(Number(e.target.value))}>
                {rebalancesDesc.map(({ r, idx }) => (
                  <option key={r.trade_date} value={idx}>
                    {r.trade_date}{idx === rebalances.length - 1 ? " (最近)" : ""}
                  </option>
                ))}
              </select>
            </div>
          </CardHeader>
          <CardContent>
            {rb && (
              <>
                <div className="bg-primary/5 border border-primary/20 text-sm p-4 rounded-lg mb-6 leading-relaxed space-y-1.5">
                  <RebalanceSummary rb={rb} nameMap={nameMap} bandPct={bandPct} />
                </div>
                <div className="max-h-[260px] overflow-auto min-w-0">
                  <Table className="min-w-0">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-0">资产</TableHead>
                        <TableHead className="text-right">上期权重</TableHead>
                        <TableHead className="text-right">本期权重</TableHead>
                        <TableHead className="text-right pr-0">变动</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {Object.entries(rb.target_weights).filter(([, w]) => w >= ZERO_EPS).sort((a, b) => b[1] - a[1]).map(([k, w]) => {
                        const prev = rb.prev_weights?.[k];
                        const d = rb.delta?.[k] ?? (prev != null ? w - prev : null);
                        return (
                          <TableRow key={k}>
                            <TableCell className="pl-0 font-medium">{nameMap[k] || k}</TableCell>
                            <TableCell className="text-right font-mono text-muted-foreground">{prev != null ? pct(prev) : "-"}</TableCell>
                            <TableCell className="text-right font-mono">{pct(w)}</TableCell>
                            <TableCell className={`text-right font-mono pr-0 ${d == null ? "text-muted-foreground" : d > 0 ? "text-up" : d < 0 ? "text-down" : "text-muted-foreground"}`}>
                              {d == null ? "建仓" : Math.abs(d) < 1e-6 ? "-" : signPct(d)}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Period returns / vols */}
      <Card className="min-w-0">
        <CardHeader><CardTitle>区间收益率与波动率</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto min-w-0">
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-0 whitespace-nowrap">指标</TableHead>
                {PERIOD_KEYS.map((k) => (
                  <TableHead key={k} className="text-right whitespace-nowrap">{PERIOD_LABELS[k]}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <PeriodRow label="组合收益率" data={mPort?.period_returns} primary />
              <PeriodRow label={`${benchName}收益率`} data={mBench?.period_returns} />
              <PeriodRow label="组合波动率" data={mPort?.period_vols} muted />
              <PeriodRow label={`${benchName}波动率`} data={mBench?.period_vols} muted />
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Metrics table */}
        <Card className="min-w-0">
          <CardHeader><CardTitle>绩效指标对比</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto min-w-0">
            <Table className="min-w-0">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-0">指标</TableHead>
                  <TableHead className="text-right text-primary">{portfolio.name}</TableHead>
                  <TableHead className="text-right text-muted-foreground">{benchName}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <MetricRow label="夏普比率" p={mPort?.sharpe} b={mBench?.sharpe} fmt={(v) => v?.toFixed(2)} />
                <MetricRow label="Sortino 比率" p={mPort?.sortino} b={mBench?.sortino} fmt={(v) => v?.toFixed(2)} />
                <MetricRow label={`信息比率 (基准:${benchName})`} p={mPort?.information_ratio} b={null} fmt={(v) => v?.toFixed(2)} />
                <MetricRow label="Calmar 比率" p={mPort?.calmar} b={mBench?.calmar} fmt={(v) => v?.toFixed(2)} />
                <MetricRow label="最大回撤" p={mPort?.max_drawdown} b={mBench?.max_drawdown} fmt={(v) => pct(v)} />
                <MetricRow label="最大回撤修复天数" p={mPort?.max_drawdown_recovery_days} b={mBench?.max_drawdown_recovery_days}
                  fmt={(v) => v == null ? undefined : `${v} 天`} />
                <MetricRow label="年化收益" p={mPort?.annualized_return} b={mBench?.annualized_return} fmt={(v) => pct(v)} />
                <MetricRow label="年化波动" p={mPort?.annualized_vol} b={mBench?.annualized_vol} fmt={(v) => pct(v)} />
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Distribution */}
        <Card>
          <CardHeader><CardTitle>日收益率分布</CardTitle></CardHeader>
          <CardContent>
            {distOption ? (
              <>
                <EChart option={distOption} style={{ height: 300, width: "100%" }} />
                <div className="mt-4 overflow-x-auto">
                  <Table className="min-w-[400px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-0">统计量</TableHead>
                        <TableHead className="text-right text-primary">{portfolio.name}</TableHead>
                        <TableHead className="text-right text-muted-foreground">{benchName}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      <DistStatRow label="日收益率期望" p={mPort?.daily_expected_return} b={mBench?.daily_expected_return} fmt={(v) => pct(v, 3)} />
                      <DistStatRow label="年化期望 (252日)" p={mPort?.annualized_expected_return} b={mBench?.annualized_expected_return} fmt={(v) => pct(v, 2)} />
                      <DistStatRow label="偏度" p={mPort?.skewness} b={mBench?.skewness} fmt={(v) => v?.toFixed(4)} />
                      <DistStatRow label="超额峰度" p={mPort?.kurtosis} b={mBench?.kurtosis} fmt={(v) => v?.toFixed(4)} />
                    </TableBody>
                  </Table>
                </div>
              </>
            ) : <div className="text-sm text-muted-foreground py-12 text-center">数据不足</div>}
          </CardContent>
        </Card>
      </div>

      {data.attribution && data.attribution.assets.length > 0 && (
        <AttributionSection
          attribution={data.attribution}
          isDark={isDark}
          cardBg={cardBg}
          fg={fg}
          textCol={textCol}
          axisLineCol={axisLineCol}
          splitLineCol={splitLineCol}
          benchName={benchName}
        />
      )}

      <RiskMatrixSection
        corr={corr}
        portfolioId={portfolio.portfolio_id}
        portfolioAssets={portfolio.assets}
        holdings={holdings}
        lookbackDays={portfolio.lookback_days || 156}
        isDark={isDark}
        cardBg={cardBg}
        fg={fg}
        textCol={textCol}
        axisLineCol={axisLineCol}
        splitLineCol={splitLineCol}
      />

      </motion.div>
      </AnimatePresence>
    </div>
  );
}

function PeriodRow({ label, data, primary, muted }: { label: string; data?: Record<string, number | null>; primary?: boolean; muted?: boolean }) {
  return (
    <TableRow>
      <TableCell className="pl-0 font-medium">{label}</TableCell>
      {PERIOD_KEYS.map((k) => {
        const v = data?.[k];
        const cls = muted ? "text-foreground"
          : v == null ? "text-muted-foreground"
          : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted-foreground";
        return <TableCell key={k} className={`text-right font-mono ${primary ? "" : ""} ${cls}`}>{v == null ? "-" : `${(v * 100).toFixed(2)}%`}</TableCell>;
      })}
    </TableRow>
  );
}

function MetricRow({ label, p, b, fmt }: { label: string; p?: number | null; b?: number | null; fmt: (v: number | null | undefined) => string | undefined }) {
  return (
    <TableRow>
      <TableCell className="pl-0 font-medium">{label}</TableCell>
      <TableCell className="text-right font-mono text-primary">{p == null ? "-" : (fmt(p) ?? "-")}</TableCell>
      <TableCell className="text-right font-mono text-muted-foreground">{b == null ? "-" : (fmt(b) ?? "-")}</TableCell>
    </TableRow>
  );
}

function DistStatRow({ label, p, b, fmt }: { label: string; p?: number | null; b?: number | null; fmt: (v: number | null | undefined) => string | undefined }) {
  return (
    <TableRow>
      <TableCell className="pl-0 font-medium">{label}</TableCell>
      <TableCell className="text-right font-mono">{p == null ? "-" : (fmt(p) ?? "-")}</TableCell>
      <TableCell className="text-right font-mono text-muted-foreground">{b == null ? "-" : (fmt(b) ?? "-")}</TableCell>
    </TableRow>
  );
}

function rebalanceTrigger(rb: Rebalance) {
  if (!rb.prev_weights || !rb.target_weights) return null;
  let key = "";
  let maxDev = 0;
  let drift = 0;
  let target = 0;
  const keys = new Set([...Object.keys(rb.prev_weights), ...Object.keys(rb.target_weights)]);
  for (const k of keys) {
    const d = Math.abs((rb.prev_weights[k] ?? 0) - (rb.target_weights[k] ?? 0));
    if (d > maxDev) {
      maxDev = d;
      key = k;
      drift = rb.prev_weights[k] ?? 0;
      target = rb.target_weights[k] ?? 0;
    }
  }
  return key ? { key, drift, target, maxDev } : null;
}

function RebalanceSummary({
  rb, nameMap, bandPct,
}: {
  rb: Rebalance;
  nameMap: Record<string, string>;
  bandPct: number;
}) {
  const isInitial = !rb.prev_weights || rb.reason === "建仓";
  if (isInitial) {
    return (
      <>
        <p className="font-medium text-foreground">{rb.trade_date} · 建仓</p>
        <p className="text-muted-foreground">
          回测有效起点，按当日最优权重建立初始持仓；此后各成分权重随市场涨跌自然漂移，直至偏离超过 {bandPct} 个百分点时再平衡。
        </p>
      </>
    );
  }
  const trigger = rebalanceTrigger(rb);
  const assetName = trigger ? (nameMap[trigger.key] || trigger.key) : null;
  const devPp = trigger ? +(trigger.maxDev * 100).toFixed(2) : rb.max_deviation != null ? +(rb.max_deviation * 100).toFixed(2) : null;
  return (
    <>
      <p className="font-medium text-foreground">{rb.trade_date} · 再平衡 · 调仓</p>
      <p className="text-muted-foreground">
        自上次调仓后，组合权重随行情漂移；系统每日重算最优目标权重，当任一成分实际权重偏离目标超过 {bandPct} 个百分点时，触发整体再平衡并调回当日最优。
      </p>
      {assetName && devPp != null && trigger && (
        <p>
          <span className="text-muted-foreground">触发原因：</span>
          「{assetName}」漂移最大，实际 {pct(trigger.drift)} vs 目标 {pct(trigger.target)}
          （偏离 {devPp.toFixed(2)}pp &gt; {bandPct}pp），剩余现金将分配给其他资产，再平衡+红利再投资。
        </p>
      )}
    </>
  );
}

function DeleteButton({
  portfolioId, name, onDeleted,
}: {
  portfolioId: number; name: string; onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const onClick = async () => {
    if (!window.confirm(`确认删除组合「${name}」? 此操作不可恢复。`)) return;
    setBusy(true);
    try {
      await api.deletePortfolio(portfolioId);
      onDeleted();
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onClick}
      disabled={busy}
      className="text-destructive hover:text-destructive hover:bg-destructive/10 border-destructive/30"
    >
      <Trash2 className="w-3.5 h-3.5" />
      删除
    </Button>
  );
}

function RecomputeButton({ portfolioId, onDone }: { portfolioId: number; onDone: () => void }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);

  const start = async () => {
    setSubmitting(true);
    try {
      const res = await api.recomputePortfolio(portfolioId);
      setConfirmOpen(false);
      if (res.task_id) {
        setTaskId(res.task_id);
        setProgressOpen(true);
      } else {
        await api.waitForPortfolio(portfolioId);
        onDone();
      }
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setConfirmOpen(true)}>
        <RefreshCw className="w-3.5 h-3.5" />
        重算
      </Button>
      <ConfirmRecomputeDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={start}
        busy={submitting}
      />
      <BacktestProgressDialog
        taskId={taskId}
        portfolioId={portfolioId}
        open={progressOpen}
        onOpenChange={setProgressOpen}
        onDone={() => { setProgressOpen(false); onDone(); }}
      />
    </>
  );
}

function CopyButton({ portfolioId, router }: { portfolioId: number; router: ReturnType<typeof useRouter> }) {
  // 复制 = 继承原参数到 Builder, 与新建/编辑一致; 用户可调整后提交建新组合。
  return (
    <Button variant="outline" size="sm" onClick={() => router.push(`/builder?copy=${portfolioId}`)}>
      <Copy className="w-3.5 h-3.5" />
      复制
    </Button>
  );
}

function DemoToggleButton({
  portfolioId, isDemo, onChanged,
}: {
  portfolioId: number; isDemo: boolean; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const onClick = async () => {
    const next = !isDemo;
    const msg = next
      ? "设为示例组合后, 访客可在 Dashboard 示例列表中看到。"
      : "取消示例后, 该组合仅管理员在列表中可见。";
    if (!window.confirm(msg)) return;
    setBusy(true);
    try {
      await api.setDemoFlag(portfolioId, next);
      onChanged();
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button variant="outline" size="sm" onClick={onClick} disabled={busy}>
      <Star className={`w-3.5 h-3.5 ${isDemo ? "fill-primary text-primary" : ""}`} />
      {isDemo ? "取消示例" : "设为示例"}
    </Button>
  );
}

function ReorderDialog({ portfolios, onSaved }: { portfolios: PortfolioInfo[]; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<PortfolioInfo[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setItems(portfolios);
  }, [open, portfolios]);

  const move = (i: number, dir: -1 | 1) => {
    setItems((arr) => {
      const j = i + dir;
      if (j < 0 || j >= arr.length) return arr;
      const next = arr.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.reorderPortfolios(items.map((p) => p.portfolio_id));
      onSaved();
      setOpen(false);
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="shrink-0 bg-background" title="调整组合顺序">
          <ArrowUpDown className="w-3.5 h-3.5" /> 排序
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>调整组合顺序</DialogTitle></DialogHeader>
        <p className="text-xs text-muted-foreground">仅影响你自己看到的下拉顺序；示例组合固定排在前。</p>
        <div className="max-h-[50vh] overflow-auto space-y-1.5 pr-1">
          {items.map((p, i) => (
            <div key={p.portfolio_id} className="flex items-center gap-2 rounded-md border border-border px-3 py-2">
              <span className="flex-1 truncate text-sm">
                {p.is_demo && <Badge variant="secondary" className="mr-1.5 font-normal">Demo</Badge>}
                {p.name}
                {!p.is_demo && <span className="text-muted-foreground"> #{p.portfolio_id}</span>}
              </span>
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={i === 0} onClick={() => move(i, -1)}>
                <ArrowUp className="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={i === items.length - 1} onClick={() => move(i, 1)}>
                <ArrowDown className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
          <Button onClick={save} disabled={busy}>{busy ? "保存中..." : "保存顺序"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RunningPortfolioView({
  status, portfolios, router, onRefresh,
}: {
  status: PortfolioStatus;
  portfolios: PortfolioInfo[];
  router: ReturnType<typeof useRouter>;
  onRefresh: () => void;
}) {
  const [current, setCurrent] = useState(status);
  const task = current.active_task;
  const pct = task && task.progress_total > 0
    ? Math.round((task.progress_current / task.progress_total) * 100)
    : 5;

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const next = await api.getPortfolioStatus(status.portfolio_id);
        if (stopped) return;
        if (next.status === "done") {
          onRefresh();
          return;
        }
        setCurrent(next);
      } catch {
        // 状态接口临时失败时保持当前页面，下一轮继续。
      }
      if (!stopped) window.setTimeout(tick, 2000);
    };
    const timer = window.setTimeout(tick, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [status.portfolio_id, onRefresh]);

  const demoPortfolios = portfolios.filter((p) => p.is_demo);
  const otherPortfolios = portfolios.filter((p) => !p.is_demo);

  return (
    <div className="flex-1 px-4 py-6 sm:p-6 max-w-4xl mx-auto w-full space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>该组合正在回测计算中</CardTitle>
          <CardDescription>
            你可以切换查看其他组合或 Demo；该组合完成后页面会自动刷新。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Select value={String(status.portfolio_id)} onValueChange={(v) => router.push(`/dashboard?id=${v}`)}>
            <SelectTrigger className="w-full sm:w-80">
              <SelectValue placeholder="选择组合" />
            </SelectTrigger>
            <SelectContent>
              {demoPortfolios.length > 0 && (
                <SelectGroup>
                  <SelectLabel>示例组合</SelectLabel>
                  {demoPortfolios.map((p) => (
                    <SelectItem key={p.portfolio_id} value={String(p.portfolio_id)}>{p.name}</SelectItem>
                  ))}
                </SelectGroup>
              )}
              {otherPortfolios.length > 0 && (
                <SelectGroup>
                  <SelectLabel>其他组合</SelectLabel>
                  {otherPortfolios.map((p) => (
                    <SelectItem key={p.portfolio_id} value={String(p.portfolio_id)}>{p.name} #{p.portfolio_id}</SelectItem>
                  ))}
                </SelectGroup>
              )}
            </SelectContent>
          </Select>
          <div>
            <div className="flex justify-between text-sm mb-2">
              <span className="text-muted-foreground">{task?.progress_message || "任务运行中..."}</span>
              <span className="font-mono">{Math.max(5, Math.min(100, pct))}%</span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div className="h-full bg-primary transition-all" style={{ width: `${Math.max(5, Math.min(100, pct))}%` }} />
            </div>
          </div>
          <Button variant="outline" onClick={onRefresh}>刷新状态</Button>
        </CardContent>
      </Card>
    </div>
  );
}

function benchmarkName(p: PortfolioInfo): string {
  const fromKey = BENCHMARK_OPTIONS.find((b) => b.key === p.benchmark_key)?.name;
  if (fromKey) return fromKey;
  const map: Record<string, string> = {
    bond6040: "60/40经典股债",
    "000300": "沪深300", "000510": "中证A500", "HSI": "恒生指数", "000905": "中证500",
  };
  return map[p.benchmark_key || ""] || p.benchmark_name || p.benchmark_key || DEFAULT_BENCHMARK_KEY;
}

function PortfolioParamsCard({ portfolio, currentMethod }: { portfolio: PortfolioInfo; currentMethod: string }) {
  const benchLabel = benchmarkName(portfolio);
  const maxPct = portfolio.max_weight != null
    ? +(portfolio.max_weight * 100).toFixed(2)
    : DEFAULT_MAX_WEIGHT_PCT;
  const bandPct = portfolio.rebalance_band != null
    ? +(portfolio.rebalance_band * 100).toFixed(1)
    : 5;
  const items = [
    { label: "优化方法", value: methodLabel(currentMethod) },
    { label: "优化指标", value: portfolio.ratio === "sortino" ? "Sortino 比率" : "夏普比率" },
    { label: "无风险利率", value: pct(portfolio.risk_free_rate ?? 0, 2) },
    { label: "回溯天数", value: `${portfolio.lookback_days ?? 156} 交易日` },
    { label: "回测起点", value: portfolio.start_date?.slice(0, 10) || "-" },
    { label: "有效起点", value: portfolio.effective_start_date?.slice(0, 10) || "-" },
    { label: "结果截至", value: portfolio.data_as_of_date?.slice(0, 10) || portfolio.result_updated_at?.slice(0, 10) || "-" },
    { label: "对比基准", value: benchLabel },
    { label: "再平衡带", value: `${bandPct} 个百分点` },
    { label: "单资产上限", value: `${maxPct}%` },
    { label: "手续费", value: pct(portfolio.fee_rate ?? 0, 3) },
    { label: "滑点", value: pct(portfolio.slippage_rate ?? 0, 3) },
    { label: "印花税", value: pct(portfolio.stamp_duty_rate ?? 0, 3) },
    { label: "成本口径", value: "单边换手（印花税仅卖出）" },
  ];
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">组合参数</CardTitle>
        <CardDescription>该投资组合设定的回测与优化参数</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-3 text-sm">
          {items.map(({ label, value }) => (
            <div key={label}>
              <div className="text-muted-foreground mb-0.5">{label}</div>
              <div className="font-medium">{value}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

const UP_COLOR = "#30A46C";
const DOWN_COLOR = "#E5484D";

function AttributionSection({
  attribution, isDark, cardBg, fg, textCol, axisLineCol, splitLineCol, benchName,
}: {
  attribution: Attribution;
  isDark: boolean;
  cardBg: string;
  fg: string;
  textCol: string;
  axisLineCol: string;
  splitLineCol: string;
  benchName: string;
}) {
  const isMobile = useIsMobile();
  const s = attribution.summary;
  const primary = "#3B82F6";

  const summaryCards = [
    { label: "组合总收益", value: s.total_return, hint: "回测区间几何累计" },
    { label: "系统性 Beta", value: s.systematic, hint: `β=${s.beta.toFixed(2)}（对${benchName}）` },
    { label: "截面选择", value: s.selection, hint: "选品（按平均配置）" },
    { label: "时序调仓", value: s.timing, hint: `动态调仓/择时（已扣费${s.costs != null ? signPct(s.costs) : "-"}）` },
    { label: "残差", value: s.residual, hint: "Carino 链接近似误差" },
  ];

  // 瀑布图: 系统性 + 选择 + 调仓 + 残差 → 总收益
  const steps = [
    { name: "系统性 Beta", value: s.systematic },
    { name: "截面选择", value: s.selection },
    { name: "时序调仓", value: s.timing },
    { name: "残差", value: s.residual },
  ];
  const assist: (number | string)[] = [];
  const inc: (number | string)[] = [];
  const dec: (number | string)[] = [];
  let running = 0;
  for (const st of steps) {
    const v = st.value;
    if (v >= 0) { assist.push(+(running * 100).toFixed(3)); inc.push(+(v * 100).toFixed(3)); dec.push("-"); }
    else { assist.push(+((running + v) * 100).toFixed(3)); dec.push(+(-v * 100).toFixed(3)); inc.push("-"); }
    running += v;
  }
  assist.push(0); inc.push("-"); dec.push("-");
  const totalArr: (number | string)[] = ["-", "-", "-", "-", +(running * 100).toFixed(3)];
  const waterfallCats = [...steps.map((x) => x.name), "组合总收益"];

  const waterfallOption = {
    tooltip: {
      trigger: "axis", backgroundColor: cardBg, borderColor: axisLineCol, textStyle: { color: fg },
      formatter: (ps: Array<{ axisValue: string; seriesName: string; value: number | string }>) => {
        const row = ps.find((p) => p.seriesName !== "assist" && p.value !== "-");
        const v = row && typeof row.value === "number" ? row.value : 0;
        return `${ps[0].axisValue}<br/>${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
      },
    },
    grid: { top: 20, right: 16, bottom: 24, left: 44 },
    xAxis: {
      type: "category", data: waterfallCats,
      axisLabel: { color: textCol, fontSize: 11, interval: 0 },
      axisLine: { lineStyle: { color: axisLineCol } },
    },
    yAxis: {
      type: "value", axisLabel: { color: textCol, formatter: "{value}%" },
      splitLine: { lineStyle: { color: splitLineCol } },
    },
    series: [
      { name: "assist", type: "bar", stack: "wf", itemStyle: { color: "transparent" }, emphasis: { itemStyle: { color: "transparent" } }, data: assist },
      { name: "增益", type: "bar", stack: "wf", itemStyle: { color: UP_COLOR }, data: inc },
      { name: "损耗", type: "bar", stack: "wf", itemStyle: { color: DOWN_COLOR }, data: dec },
      { name: "合计", type: "bar", stack: "wf", itemStyle: { color: primary }, data: totalArr },
    ],
  };

  // 逐资产贡献(升序, 水平条形)
  const assetsAsc = [...attribution.assets].sort((a, b) => a.contribution - b.contribution);
  const assetBarOption = {
    tooltip: {
      trigger: "axis", backgroundColor: cardBg, borderColor: axisLineCol, textStyle: { color: fg },
      axisPointer: { type: "shadow" },
      valueFormatter: (v: number) => `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`,
    },
    grid: { top: 10, right: 20, bottom: 24, left: isMobile ? 4 : 8, containLabel: true },
    xAxis: {
      type: "value", axisLabel: { color: textCol, formatter: "{value}%" },
      splitLine: { lineStyle: { color: splitLineCol } },
    },
    yAxis: {
      type: "category", data: assetsAsc.map((a) => a.name),
      axisLabel: {
        color: textCol,
        fontSize: isMobile ? 9 : 11,
        width: isMobile ? 64 : 120,
        overflow: "truncate",
      },
      axisLine: { lineStyle: { color: axisLineCol } },
    },
    series: [{
      type: "bar",
      data: assetsAsc.map((a) => ({
        value: +(a.contribution * 100).toFixed(3),
        itemStyle: { color: a.contribution >= 0 ? UP_COLOR : DOWN_COLOR },
      })),
      barMaxWidth: 22,
    }],
  };

  // 逐调仓贡献
  const rbs = attribution.rebalances;
  const rebalanceBarOption = rbs.length > 0 ? {
    tooltip: {
      trigger: "axis", backgroundColor: cardBg, borderColor: axisLineCol, textStyle: { color: fg },
      axisPointer: { type: "shadow" },
      valueFormatter: (v: number) => `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`,
    },
    grid: { top: 16, right: 16, bottom: 40, left: 44 },
    xAxis: {
      type: "category", data: rbs.map((r) => r.trade_date),
      axisLabel: { color: textCol, fontSize: isMobile ? 8 : 9, rotate: 45 }, axisLine: { lineStyle: { color: axisLineCol } },
    },
    yAxis: {
      type: "value", axisLabel: { color: textCol, formatter: "{value}%" },
      splitLine: { lineStyle: { color: splitLineCol } },
    },
    series: [{
      type: "bar",
      data: rbs.map((r) => ({
        value: +(r.contribution * 100).toFixed(3),
        itemStyle: { color: r.contribution >= 0 ? UP_COLOR : DOWN_COLOR },
      })),
      barMaxWidth: 28,
    }],
  } : null;

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>绩效归因</CardTitle>
        <CardDescription>
          组合收益拆解为 系统性Beta（{benchName}） + 截面选择 + 时序调仓（已扣交易成本） + 残差（Carino链接近似误差），并列出各资产与每次调仓的收益贡献。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* 概览卡片 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {summaryCards.map((c) => (
            <div key={c.label} className="rounded-lg border border-border bg-muted/20 px-3 py-2.5">
              <div className="text-xs text-muted-foreground">{c.label}</div>
              <div className={`text-lg font-mono font-medium ${c.value > 0 ? "text-up" : c.value < 0 ? "text-down" : ""}`}>
                {signPct(c.value)}
              </div>
              <div className="text-[11px] text-muted-foreground mt-0.5">{c.hint}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <div className="text-sm font-medium mb-2">收益拆解瀑布</div>
            <EChart option={waterfallOption} style={{ height: 300, width: "100%" }} />
          </div>
          <div>
            <div className="text-sm font-medium mb-2">各资产收益贡献</div>
            <EChart option={assetBarOption} style={{ height: Math.max(240, assetsAsc.length * 30 + 40), width: "100%" }} />
          </div>
        </div>

        {rebalanceBarOption && (
          <div>
            <div className="text-sm font-medium mb-2">逐次调仓收益贡献（持有区间）</div>
            <EChart option={rebalanceBarOption} style={{ height: 260, width: "100%" }} />
          </div>
        )}

        <div className="overflow-x-auto min-w-0">
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-0">资产</TableHead>
                <TableHead className="text-right">平均权重</TableHead>
                <TableHead className="text-right">区间收益</TableHead>
                <TableHead className="text-right">总贡献</TableHead>
                <TableHead className="text-right">静态(选品)</TableHead>
                <TableHead className="text-right pr-0">调仓(择时)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {attribution.assets.map((a) => (
                <TableRow key={a.key}>
                  <TableCell className="pl-0 font-medium">{a.name}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">{pct(a.avg_weight)}</TableCell>
                  <TableCell className={`text-right font-mono ${a.asset_return > 0 ? "text-up" : a.asset_return < 0 ? "text-down" : ""}`}>{signPct(a.asset_return)}</TableCell>
                  <TableCell className={`text-right font-mono ${a.contribution > 0 ? "text-up" : a.contribution < 0 ? "text-down" : ""}`}>{signPct(a.contribution)}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">{signPct(a.static)}</TableCell>
                  <TableCell className="text-right font-mono pr-0 text-muted-foreground">{signPct(a.timing)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

function buildDistOption(
  nav: BacktestResult["nav"], isDark: boolean, cardBg: string, fg: string,
  textCol: string, axisLineCol: string, splitLineCol: string, benchName: string,
) {
  const rets = nav.map((d) => d.ret).filter((x): x is number => x != null && !Number.isNaN(x));
  const bench = nav.map((d) => d.bench_ret).filter((x): x is number => x != null && !Number.isNaN(x));
  if (rets.length < 10) return null;
  const all = [...rets, ...bench];
  const lo = Math.min(...all), hi = Math.max(...all);
  const bins = 40;
  const width = (hi - lo) / bins || 1;
  const centers = Array.from({ length: bins }, (_, i) => lo + width * (i + 0.5));
  const hist = (arr: number[]) => {
    const c = new Array(bins).fill(0);
    arr.forEach((v) => { let idx = Math.floor((v - lo) / width); if (idx >= bins) idx = bins - 1; if (idx < 0) idx = 0; c[idx]++; });
    return c;
  };
  // 计算中位数（映射到 bin 索引用于 markLine 的 xAxis）
  const median = (arr: number[]) => {
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = sorted.length / 2;
    return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[Math.floor(mid)];
  };
  const portMedian = median(rets);
  const benchMedian = median(bench);
  const portMedianBin = Math.round((portMedian - lo) / width);
  const benchMedianBin = Math.round((benchMedian - lo) / width);
  return {
    tooltip: { trigger: "axis", backgroundColor: cardBg, textStyle: { color: fg } },
    legend: { data: ["组合", benchName], textStyle: { color: textCol }, top: 0 },
    grid: { top: 40, right: 20, bottom: 30, left: 45 },
    xAxis: {
      type: "category", data: centers.map((c) => (c * 100).toFixed(1)),
      axisLabel: { color: textCol, interval: 7 }, axisLine: { lineStyle: { color: axisLineCol } },
      name: "日收益率%", nameTextStyle: { color: textCol },
    },
    yAxis: { type: "value", axisLabel: { color: textCol }, splitLine: { lineStyle: { color: splitLineCol } } },
    series: [
      {
        name: "组合", type: "bar", data: hist(rets),
        itemStyle: { color: "rgba(59,130,246,0.7)" }, barWidth: "90%", barGap: "-100%",
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: "#3B82F6", type: "dashed", width: 1.5 },
          label: { formatter: `中位数 ${(portMedian * 100).toFixed(2)}%`, color: "#3B82F6", fontSize: 10 },
          data: [{ xAxis: portMedianBin }],
        },
      },
      {
        name: benchName, type: "bar", data: hist(bench),
        itemStyle: { color: "rgba(161,161,161,0.5)" }, barWidth: "90%",
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: "#A1A1A1", type: "dashed", width: 1.5 },
          label: { formatter: `中位数 ${(benchMedian * 100).toFixed(2)}%`, color: "#A1A1A1", fontSize: 10 },
          data: [{ xAxis: benchMedianBin }],
        },
      },
    ],
  };
}
