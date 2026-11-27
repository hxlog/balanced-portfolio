"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import {
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, type Asset } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  backtestBasket,
  basketErrorMessage,
  copyBasket,
  fetchBasket,
  optimizeBasket,
  saveBasket,
  updateBasket,
} from "@/lib/basket-api";
import {
  DEMO_BASKET_BADGE,
  basketAccess,
  basketCopyGuard,
  basketSaveGuard,
  basketViewerFromAuth,
  isDemoBasket,
} from "@/lib/basket-demo";
import {
  basketFormFromRecord,
  basketItemsFromRecord,
} from "@/lib/basket-load";
import { formatPct, normalizeRiskBudget } from "@/lib/basket-format";
import { qk } from "@/lib/queries";
import { useQuery } from "@tanstack/react-query";
import {
  BASKET_MAX_ASSETS,
  BASKET_METHOD_OPTIONS,
  STOCK_BACKTEST_ADJUST,
  STOCK_SOURCE,
  basketItemFromAsset,
  basketItemFromStock,
  basketKey,
  basketMethodLabel,
  type BasketAdjust,
  type BasketBacktestInput,
  type BasketBacktestResult,
  type BasketItem,
  type BasketMethod,
  type BasketOptimizeInput,
  type BasketOptimizeResult,
  type BasketRecord,
  type StockSearchItem,
} from "@/lib/basket-types";
import { cn } from "@/lib/utils";
import {
  AssetPoolDialog,
  BasketAssets,
  StockSearchDialog,
  notifyStockAdded,
} from "./BasketAssets";
import { BasketErrorPanel, BasketResults } from "./BasketResults";
import { PageModeHeader } from "./PageModeHeader";

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function defaultDateRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 3);
  return { start: isoDate(start), end: isoDate(end) };
}

function canSaveAfterProbeError(error: unknown): boolean {
  const detail = (
    error as {
      detail?: { probe_kind?: string; can_save_anyway?: boolean };
    } | null
  )?.detail;
  return detail?.probe_kind === "unreachable" && detail.can_save_anyway !== false;
}

/**
 * 构建器页面壳：顶部模式条（居中）+ 内容容器。
 * 局部 loading / 错误态与正常内容共用同一壳，避免整页 loading 与布局跳动。
 */
function BasketModeShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex-1 bg-bg-subtle/30 pb-16">
      <div className="border-b border-border bg-background px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-7xl">
          <PageModeHeader
            mode="basket"
            basePath="/builder"
            ariaLabel="组合构建模式"
            trailing={
              <span className="hidden text-xs text-muted-foreground xl:inline">
                单层风险平价 · 股票回测口径 后复权
              </span>
            }
          />
        </div>
      </div>
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</div>
    </div>
  );
}

/** 载入已保存篮子时的局部骨架（保留模式条与页面壳，不整页转圈）。 */
function BasketBuilderLoading() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="正在载入篮子">
      <div className="space-y-2">
        <div className="h-7 w-40 animate-pulse rounded bg-muted" />
        <div className="h-3 w-72 max-w-full animate-pulse rounded bg-muted" />
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
        <div className="space-y-3 rounded-xl border border-border bg-card p-4">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="h-12 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
        <div className="space-y-3 rounded-xl border border-border bg-card p-4">
          <div className="h-4 w-24 animate-pulse rounded bg-muted" />
          <div className="grid grid-cols-2 gap-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="h-8 animate-pulse rounded bg-muted" />
            ))}
          </div>
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-9 animate-pulse rounded bg-muted" />
          ))}
        </div>
      </div>
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="h-4 w-28 animate-pulse rounded bg-muted" />
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="h-6 animate-pulse rounded bg-muted" />
            ))}
          </div>
          <div className="mx-auto h-[220px] w-[220px] animate-pulse rounded-full bg-muted" />
        </div>
      </div>
    </div>
  );
}

/** 篮子载入失败（404/403/网络）：给出重试与新建入口，不丢弃页面壳。 */
function BasketLoadError({
  message,
  onRetry,
  onReset,
}: {
  message: string;
  onRetry: () => void;
  onReset: () => void;
}) {
  return (
    <div className="mx-auto max-w-xl space-y-4 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
      <p className="text-sm font-medium text-destructive">篮子载入失败</p>
      <p className="break-words text-sm text-muted-foreground">{message}</p>
      <div className="flex flex-wrap justify-center gap-2">
        <Button variant="outline" onClick={onRetry}>
          重试
        </Button>
        <Button onClick={onReset}>新建篮子</Button>
      </div>
    </div>
  );
}

export function BasketBuilder({ initialAssets = [] }: { initialAssets?: Asset[] }) {
  const { canManageAssets, userId, isSuperAdmin } = useAuth();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  // 资产池（需求 P2-3）：5min 查询缓存共享 `/api/assets`（与 dashboard 的 useAssets 同 queryKey），
  // 首屏与 ?basket= 详情并行加载；修复此前只用恒为 [] 的 initialAssets 导致「资产池恒空」。
  // 直接用 useQuery 而不是 useAssets：后者被断言成只含 data，拿不到 loading/error/refetch。
  const {
    data: poolAssetsData,
    isLoading: poolLoading,
    error: poolError,
    refetch: refetchPool,
  } = useQuery({
    queryKey: qk.assets,
    queryFn: () => api.getAssets().then((res) => res.assets),
    staleTime: 5 * 60_000,
  });
  // 股票「接入资产池」后先在本地追加，等 /api/assets 缓存刷新前也能立即使用。
  const [localAssets, setLocalAssets] = useState<Asset[]>([]);
  const poolAssets = useMemo(() => {
    const base =
      initialAssets.length > 0 ? initialAssets : (poolAssetsData ?? []);
    const extra = localAssets.filter(
      (asset) =>
        !base.some(
          (row) => row.symbol === asset.symbol && row.source === asset.source,
        ),
    );
    return [...base, ...extra];
  }, [initialAssets, localAssets, poolAssetsData]);

  const [items, setItems] = useState<BasketItem[]>([]);
  const [method, setMethod] = useState<BasketMethod>("risk_parity");
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialRange = useMemo(() => defaultDateRange(), []);
  const [startDate, setStartDate] = useState(initialRange.start);
  const [endDate, setEndDate] = useState(initialRange.end);
  const [lookback, setLookback] = useState(156);
  const [riskFreePct, setRiskFreePct] = useState(0);
  const [bandPct, setBandPct] = useState(5);
  const [riskBudgetRaw, setRiskBudgetRaw] = useState<Record<string, string>>({});
  const [poolOpen, setPoolOpen] = useState(false);
  const [stockOpen, setStockOpen] = useState(false);

  const [optimizeResult, setOptimizeResult] = useState<BasketOptimizeResult | null>(null);
  const [optimizeLoading, setOptimizeLoading] = useState(false);
  const [optimizeError, setOptimizeError] = useState<string | null>(null);
  const [optimizeSig, setOptimizeSig] = useState<string | null>(null);
  const [reoptNonce, setReoptNonce] = useState(0);

  const [backtest, setBacktest] = useState<BasketBacktestResult | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [backtestSig, setBacktestSig] = useState<string | null>(null);
  const [ingestingKey, setIngestingKey] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDesc, setSaveDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadedBasket, setLoadedBasket] = useState<BasketRecord | null>(null);
  const [basketLoading, setBasketLoading] = useState(false);
  const [basketError, setBasketError] = useState<string | null>(null);
  const [basketMapped, setBasketMapped] = useState(false);
  const [basketReloadNonce, setBasketReloadNonce] = useState(0);
  const [copying, setCopying] = useState(false);
  /**
   * 已完成 basket -> 资产池名称映射的记录。
   * poolReady=false 表示映射时资产池请求失败（名称退化为代码）：资产池重试成功后
   * 必须再映射一次，否则 mappedBasketIdRef 已置位会永久阻止名称回填。
   */
  const mappedBasketRef = useRef<{ basketId: number; poolReady: boolean } | null>(null);
  const backtestController = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      backtestController.current?.abort();
    },
    [],
  );

  const basketParam = searchParams.get("basket");
  const basketId = useMemo(() => {
    if (!basketParam) return null;
    const parsed = Number(basketParam);
    return Number.isFinite(parsed) ? parsed : null;
  }, [basketParam]);

  const viewer = useMemo(
    () => basketViewerFromAuth({ userId, isSuperAdmin }),
    [userId, isSuperAdmin],
  );
  const demoBasket = isDemoBasket(loadedBasket);
  /** 非管理员打开示例篮子 = 只读（可复制后编辑）；游客同样只读。 */
  const readOnly = demoBasket && !isSuperAdmin;
  const access = useMemo(
    () => (loadedBasket ? basketAccess(loadedBasket, viewer) : null),
    [loadedBasket, viewer],
  );

  // ?basket=<id>：只请求 basket 详情；资产池由 useAssets 并行加载（两个请求同时起飞），
  // 名称/类别映射在下一个 effect 里等双方就绪后一次性完成。
  useEffect(() => {
    mappedBasketRef.current = null;
    setLoadedBasket(null);
    setItems([]);
    setBasketMapped(false);
    setBasketError(null);
    if (basketId == null) {
      setBasketLoading(false);
      return;
    }
    let cancelled = false;
    setBasketLoading(true);
    void (async () => {
      try {
        const record = await fetchBasket<BasketRecord>(basketId);
        if (cancelled) return;
        setLoadedBasket(record);
        setMethod(record.method as BasketMethod);
        const form = basketFormFromRecord(record);
        setLookback(form.lookbackDays);
        setBandPct(form.bandPct);
        setRiskFreePct(form.riskFreePct);
        if (form.start) setStartDate(form.start);
        if (form.end) setEndDate(form.end);
        setSaveName(record.name);
        setSaveDesc(record.description ?? "");
        toast.success("已载入篮子「" + record.name + "」", {
          description:
            isDemoBasket(record) && !isSuperAdmin
              ? "示例篮子只读，可点「复制并编辑」生成自己的篮子"
              : "可修改后重新运行回测",
        });
      } catch (error) {
        if (!cancelled) {
          const message = basketErrorMessage(error);
          setBasketError(message);
          toast.error(message);
        }
      } finally {
        if (!cancelled) setBasketLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // basketId 已覆盖 searchParams 中唯一相关参数；basketReloadNonce 用于错误态重试。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basketId, basketReloadNonce]);

  // 需求 P2-3：等 basket 详情与资产池都就绪后，把 symbol 映射成资产池里的名称/类别。
  // 资产池加载失败时也用空池映射（名称退化为代码），页面会显示可重试的错误提示；
  // 重试成功后池子从「失败」变「就绪」，这里补一次映射把名称/类别回填（幂等，不覆盖已就绪映射）。
  useEffect(() => {
    if (!loadedBasket) return;
    if (initialAssets.length === 0 && poolLoading) return;
    const poolReady = initialAssets.length > 0 || (!poolError && poolAssetsData != null);
    const mapped = mappedBasketRef.current;
    if (mapped && mapped.basketId === loadedBasket.basket_id) {
      if (mapped.poolReady || !poolReady) return;
    }
    mappedBasketRef.current = { basketId: loadedBasket.basket_id, poolReady };
    setItems(basketItemsFromRecord(loadedBasket, poolAssets));
    setBasketMapped(true);
  }, [
    initialAssets.length,
    loadedBasket,
    poolAssets,
    poolAssetsData,
    poolError,
    poolLoading,
  ]);

  /**
   * 保存：
   * - 游客 → 提示先登录（需求：复制/保存提示登录）；
   * - 非管理员打开示例 → 只读，提示复制后编辑；
   * - 管理员保存示例时**不提交 latest_result**（后端契约：demo 的 latest_result 只能由
   *   /recompute 生成，PATCH 带该字段会 400）。
   */
  const handleSaveBasket = async () => {
    const guard = basketSaveGuard(loadedBasket, viewer);
    if (!guard.allowed) {
      toast.error(guard.message, {
        description: guard.needLogin
          ? "请在右上角登录后保存；也可以先复制一个示例篮子。"
          : "示例篮子由管理员维护，点「复制并编辑」后即可自由保存。",
      });
      return;
    }
    if (!saveName.trim()) {
      toast.error("请输入篮子名称");
      return;
    }
    if (items.length === 0) {
      toast.error("请先添加资产");
      return;
    }
    setSaving(true);
    try {
      const params: Record<string, unknown> = {
        lookback_days: lookbackDays,
        rebalance_band: band,
        risk_free: riskFree,
        start: startDate || undefined,
        end: endDate || undefined,
      };
      if (method === "risk_budget") params.risk_budget = budgetValues;
      const latestResult = backtest
        ? {
            method: backtest.method,
            effective_start: backtest.effective_start,
            annualized_return: backtest.annualized_return,
            annualized_vol: backtest.annualized_vol,
            max_drawdown: backtest.max_drawdown,
            sharpe: backtest.sharpe,
            rebalance_count: backtest.rebalance_count,
            n_obs: backtest.n_obs,
          }
        : null;
      const definition = {
        name: saveName.trim(),
        description: saveDesc.trim() || null,
        method,
        assets: items.map((item) => ({ symbol: item.symbol, source: item.source })),
        params,
      };
      if (loadedBasket) {
        if (isDemoBasket(loadedBasket)) {
          await updateBasket(loadedBasket.basket_id, definition);
        } else {
          await updateBasket(loadedBasket.basket_id, {
            ...definition,
            latest_result: latestResult,
          });
        }
        toast.success("篮子已更新");
        setSaveOpen(false);
      } else {
        const created = await saveBasket({ ...definition, latest_result: latestResult });
        toast.success("篮子已保存，可在 /dashboard 查看");
        setSaveOpen(false);
        router.replace("/builder?mode=basket&basket=" + created.basket_id, { scroll: false });
      }
    } catch (error) {
      toast.error(basketErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  /** 复制示例为自己的篮子（需登录；后端 copy 接口匿名 401）。 */
  const handleCopyBasket = async () => {
    if (!loadedBasket) return;
    const guard = basketCopyGuard(viewer);
    if (!guard.allowed) {
      toast.error(guard.message, {
        description: "登录后即可把示例篮子复制为自己的篮子并编辑保存。",
      });
      return;
    }
    setCopying(true);
    try {
      const created = await copyBasket(loadedBasket.basket_id);
      toast.success("已复制为自己的篮子");
      router.replace("/builder?mode=basket&basket=" + created.basket_id, {
        scroll: false,
      });
    } catch (error) {
      toast.error(basketErrorMessage(error));
    } finally {
      setCopying(false);
    }
  };

  const selectedKeys = useMemo(
    () => new Set(items.map((item) => item.key)),
    [items],
  );
  const poolKeys = useMemo(
    () => new Set(poolAssets.map((asset) => basketKey(asset.symbol, asset.source))),
    [poolAssets],
  );
  const nameByKey = useMemo(
    () => new Map(items.map((item) => [item.key, item.name])),
    [items],
  );

  // 风险预算：新资产默认 1（等预算），移除资产同步清理；输入保持字符串以允许清空。
  useEffect(() => {
    setRiskBudgetRaw((previous) => {
      let changed = false;
      const next: Record<string, string> = {};
      for (const item of items) {
        if (previous[item.key] !== undefined) next[item.key] = previous[item.key];
        else {
          next[item.key] = "1";
          changed = true;
        }
      }
      if (Object.keys(previous).length !== Object.keys(next).length) changed = true;
      return changed ? next : previous;
    });
  }, [items]);

  const rawBudget = useMemo(() => {
    const out: Record<string, number> = {};
    for (const item of items) {
      out[item.key] = Number(riskBudgetRaw[item.key] ?? 1);
    }
    return out;
  }, [items, riskBudgetRaw]);
  const budgetValues = useMemo(() => normalizeRiskBudget(rawBudget), [rawBudget]);

  const lookbackValid = Number.isFinite(lookback) && lookback >= 2;
  const riskFreeValid = Number.isFinite(riskFreePct);
  const bandValid = Number.isFinite(bandPct) && bandPct >= 0;
  const lookbackDays = lookbackValid ? Math.max(2, Math.round(lookback)) : 156;
  const riskFree = riskFreeValid ? riskFreePct / 100 : 0;
  const band = bandValid ? Math.min(1, Math.max(0, bandPct / 100)) : 0.05;

  const optimizePayload = useMemo<BasketOptimizeInput | null>(() => {
    if (items.length === 0 || !lookbackValid || !riskFreeValid) return null;
    return {
      assets: items.map((item) => ({ symbol: item.symbol, source: item.source })),
      method,
      lookback_days: lookbackDays,
      risk_free: riskFree,
      ...(startDate ? { start: startDate } : {}),
      ...(endDate ? { end: endDate } : {}),
      ...(method === "risk_budget" ? { risk_budget: budgetValues } : {}),
    };
  }, [
    items,
    method,
    lookbackValid,
    lookbackDays,
    riskFreeValid,
    riskFree,
    budgetValues,
  ]);

  const backtestPayload = useMemo<BasketBacktestInput | null>(() => {
    if (!optimizePayload || !bandValid) return null;
    return { ...optimizePayload, rebalance_band: band };
  }, [optimizePayload, bandValid, band]);

  const currentOptimizeSig = optimizePayload
    ? JSON.stringify(optimizePayload)
    : null;
  const currentBacktestSig = backtestPayload
    ? JSON.stringify(backtestPayload)
    : null;
  const optimizeDirty =
    optimizeResult != null && optimizeSig !== currentOptimizeSig;
  const backtestDirty =
    backtest != null && backtestSig !== currentBacktestSig;

  // 自动重算：输入稳定 300ms 后请求；请求序列用 AbortController 取消旧响应。
  useEffect(() => {
    if (!optimizePayload) {
      setOptimizeResult(null);
      setOptimizeError(null);
      setOptimizeLoading(false);
      setOptimizeSig(null);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setOptimizeLoading(true);
      setOptimizeError(null);
      optimizeBasket(optimizePayload, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return;
          setOptimizeResult(result);
          setOptimizeSig(JSON.stringify(optimizePayload));
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          setOptimizeResult(null);
          setOptimizeSig(null);
          setOptimizeError(basketErrorMessage(error));
        })
        .finally(() => {
          if (!controller.signal.aborted) setOptimizeLoading(false);
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // optimizeSig 已覆盖 optimizePayload 的全部内容；reoptNonce 用于手动重试。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentOptimizeSig, reoptNonce]);

  // 清空篮子时同时清掉旧回测，避免留下无对应成分的曲线。
  useEffect(() => {
    if (items.length > 0) return;
    backtestController.current?.abort();
    setBacktest(null);
    setBacktestError(null);
    setBacktestSig(null);
    setBacktestLoading(false);
  }, [items.length]);

  const addItem = (item: BasketItem): boolean => {
    if (items.some((existing) => existing.key === item.key)) {
      toast.info(`${item.name} 已在篮子中`);
      return false;
    }
    if (items.length >= BASKET_MAX_ASSETS) {
      toast.error(`最多选择 ${BASKET_MAX_ASSETS} 个资产`);
      return false;
    }
    setItems((previous) => [...previous, item]);
    return true;
  };

  const addFromPool = (asset: Asset) => {
    if (readOnly) return;
    addItem(basketItemFromAsset(asset));
  };

  const addStock = (stock: StockSearchItem) => {
    if (readOnly) return;
    const poolHit = poolAssets.find(
      (asset) => asset.symbol === stock.stock_code && asset.source === STOCK_SOURCE,
    );
    const item = basketItemFromStock(stock, poolHit);
    if (addItem(item)) notifyStockAdded(stock, Boolean(poolHit));
  };

  const removeItem = (key: string) => {
    if (readOnly) return;
    setItems((previous) => previous.filter((item) => item.key !== key));
  };

  const changeAdjust = (key: string, adjust: BasketAdjust) => {
    if (readOnly) return;
    setItems((previous) =>
      previous.map((item) =>
        item.key === key ? { ...item, adjustView: adjust } : item,
      ),
    );
  };

  const setBudget = (key: string, value: string) => {
    setRiskBudgetRaw((previous) => ({ ...previous, [key]: value }));
  };

  const reoptimize = () => setReoptNonce((value) => value + 1);

  const runBacktest = async () => {
    if (!backtestPayload || backtestLoading) return;
    backtestController.current?.abort();
    const controller = new AbortController();
    backtestController.current = controller;
    setBacktestLoading(true);
    setBacktestError(null);
    try {
      const result = await backtestBasket(backtestPayload, controller.signal);
      if (controller.signal.aborted) return;
      setBacktest(result);
      setBacktestSig(JSON.stringify(backtestPayload));
    } catch (error) {
      if (controller.signal.aborted) return;
      const message = basketErrorMessage(error);
      setBacktestError(message);
      toast.error(message);
    } finally {
      if (!controller.signal.aborted) setBacktestLoading(false);
    }
  };

  /**
   * 把搜索到的股票接入资产池：先 probe（与 /admin/assets 同一道门禁），
   * 通过后保存；后端按 stock_sina 自动抓取不复权/后复权两口径（qfq 已停用），回测主口径为后复权。
   */
  const ingestStock = async (item: BasketItem) => {
    if (readOnly) {
      toast.error("示例篮子只读，复制后即可编辑");
      return;
    }
    if (!canManageAssets) {
      toast.error("需要资产编辑权限才能接入个股行情");
      return;
    }
    if (item.inPool && item.hasData) return;
    setIngestingKey(item.key);
    try {
      try {
        await api.probeAdminAsset(STOCK_SOURCE, item.symbol, {});
      } catch (error) {
        // 「接口可达但本次被反爬/限频挡住」与既有 CreateAssetDialog 同口径，
        // 允许保存并由后台 ingest 补拉；其余错误直接展示后端 message。
        if (!canSaveAfterProbeError(error)) throw error;
      }
      const result = await api.saveAdminAsset({
        symbol: item.symbol,
        source: STOCK_SOURCE,
        name: item.name,
        category: "stock",
        start_date: null,
        adjust: STOCK_BACKTEST_ADJUST,
        is_deleted: 0,
      });
      const localAsset: Asset = {
        symbol: item.symbol,
        source: STOCK_SOURCE,
        name: item.name,
        category: "stock",
        asset_class: "stock",
        vendor: "sina",
        logical_source: "stock_sina",
        adjust: STOCK_BACKTEST_ADJUST,
        currency: "CNY",
        last_clean_date: null,
        first_clean_date: null,
      };
      setLocalAssets((previous) =>
        previous.some(
          (asset) => basketKey(asset.symbol, asset.source) === item.key,
        )
          ? previous
          : [...previous, localAsset],
      );
      setItems((previous) =>
        previous.map((row) =>
          row.key === item.key ? { ...row, inPool: true, hasData: false } : row,
        ),
      );
      void api.revalidateAssets().catch(() => {});
      toast.success(
        result.ingest_queued
          ? "已接入，后台正在拉取不复权 / 后复权两口径历史行情"
          : "已接入资产池",
        { description: "行情就绪后点「重新优化」即可参与计算" },
      );
    } catch (error) {
      toast.error(basketErrorMessage(error));
    } finally {
      setIngestingKey(null);
    }
  };

  const canOptimize = items.length > 0 && lookbackValid && riskFreeValid;
  const canBacktest = canOptimize && bandValid;
  const activeMethod =
    BASKET_METHOD_OPTIONS.find((option) => option.value === method) ??
    BASKET_METHOD_OPTIONS[0];
  const displayWeights = optimizeResult?.weights ?? backtest?.weights ?? [];

  // 载入已保存篮子（含匿名看示例）：basket 详情与资产池并行加载，双方就绪前显示局部骨架。
  if (basketId != null && !basketError && (basketLoading || !basketMapped)) {
    return (
      <BasketModeShell>
        <BasketBuilderLoading />
      </BasketModeShell>
    );
  }
  if (basketId != null && basketError) {
    return (
      <BasketModeShell>
        <BasketLoadError
          message={basketError}
          onRetry={() => setBasketReloadNonce((value) => value + 1)}
          onReset={() => router.replace("/builder?mode=basket")}
        />
      </BasketModeShell>
    );
  }

  return (
    <BasketModeShell>
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">一篮子资产</h1>
              {loadedBasket && demoBasket ? (
                <Badge
                  variant="outline"
                  className="border-primary/40 bg-primary/5 font-normal text-primary"
                >
                  {DEMO_BASKET_BADGE}
                </Badge>
              ) : null}
              {loadedBasket && !demoBasket && access ? (
                <Badge variant="secondary" className="font-normal">
                  {access.canEdit ? "我的篮子" : "只读"}
                </Badge>
              ) : null}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {loadedBasket
                ? "已载入「" + loadedBasket.name + "」："
                : ""}
              选择资产与方法，自动计算目标权重，并按偏离带做再平衡回测。
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPoolOpen(true)}
              disabled={readOnly}
              title={readOnly ? "示例篮子只读，复制后即可编辑" : undefined}
            >
              <Plus className="mr-1 h-4 w-4" />
              资产池
            </Button>
            <Button
              size="sm"
              onClick={() => setStockOpen(true)}
              disabled={readOnly}
              title={readOnly ? "示例篮子只读，复制后即可编辑" : undefined}
            >
              <Search className="mr-1 h-4 w-4" />
              搜索股票
            </Button>
          </div>
        </div>

        {readOnly && loadedBasket ? (
          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-primary/25 bg-primary/5 px-4 py-3 text-sm">
            <span className="font-medium text-primary">{DEMO_BASKET_BADGE}</span>
            <span className="text-muted-foreground">
              示例由管理员维护；{viewer.userId ? "可复制为自己的篮子后编辑保存。" : "登录后可复制并编辑。"}
            </span>
            <Button
              size="sm"
              className="ml-auto h-7 text-xs"
              onClick={() => void handleCopyBasket()}
              disabled={copying}
            >
              {copying ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
              复制并编辑
            </Button>
          </div>
        ) : null}

        {poolError ? (
          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-sm text-warning">
            <span className="min-w-0 break-words">
              资产池加载失败（{basketErrorMessage(poolError)}），成分名称暂以代码显示。
            </span>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => void refetchPool()}
            >
              重试
            </Button>
          </div>
        ) : null}

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
          <BasketAssets
            items={items}
            onRemove={removeItem}
            onAdjustChange={changeAdjust}
            onOpenPool={() => setPoolOpen(true)}
            onOpenStock={() => setStockOpen(true)}
            onIngest={ingestStock}
            ingestingKey={ingestingKey}
            canManageAssets={canManageAssets}
            readOnly={readOnly}
          />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">优化配置</CardTitle>
              <CardDescription>切换方法后自动重算权重</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-0">
              <div className="grid grid-cols-2 gap-2">
                {BASKET_METHOD_OPTIONS.map((option) => {
                  const active = option.value === method;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setMethod(option.value)}
                      disabled={readOnly}
                      title={readOnly ? "示例篮子只读" : undefined}
                      className={cn(
                        "rounded-md border px-2.5 py-2 text-left text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                        active
                          ? "border-primary bg-primary/5 text-primary ring-1 ring-primary/20"
                          : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
                      )}
                    >
                      {option.title}
                    </button>
                  );
                })}
              </div>
              <p className="min-h-[2rem] text-xs leading-relaxed text-muted-foreground">
                {activeMethod.desc}
              </p>

              {method === "risk_budget" && items.length > 0 && (
                <div className="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-medium">风险预算（相对权重）</span>
                    <span className="text-muted-foreground">自动归一</span>
                  </div>
                  {items.map((item) => (
                    <div key={item.key} className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-xs">
                        {item.name}
                      </span>
                      <Input
                        type="number"
                        min={0}
                        step={0.1}
                        value={riskBudgetRaw[item.key] ?? "1"}
                        onChange={(event) =>
                          setBudget(item.key, event.target.value)
                        }
                        disabled={readOnly}
                        className="h-7 w-16 px-1.5 text-right font-mono text-xs tabular-nums"
                      />
                      <span className="w-12 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                        {formatPct(budgetValues[item.key] ?? 0)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="space-y-3 border-t border-border pt-4">
                <label className="block space-y-1 text-xs">
                  <span className="font-medium">回看窗口</span>
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min={2}
                      step={1}
                      value={Number.isFinite(lookback) ? lookback : ""}
                      onChange={(event) => setLookback(Number(event.target.value))}
                      disabled={readOnly}
                      aria-invalid={!lookbackValid}
                      className="w-full font-mono tabular-nums"
                    />
                    <span className="shrink-0 text-muted-foreground">交易日</span>
                  </div>
                  {!lookbackValid && (
                    <span className="text-destructive">至少需要 2 个交易日</span>
                  )}
                </label>

                <div className="grid grid-cols-2 gap-3">
                  <label className="block space-y-1 text-xs">
                    <span className="font-medium">回测开始</span>
                    <Input
                      type="date"
                      value={startDate}
                      onChange={(event) => setStartDate(event.target.value)}
                      disabled={readOnly}
                      className="w-full font-mono text-xs"
                    />
                  </label>
                  <label className="block space-y-1 text-xs">
                    <span className="font-medium">回测结束</span>
                    <Input
                      type="date"
                      value={endDate}
                      onChange={(event) => setEndDate(event.target.value)}
                      disabled={readOnly}
                      className="w-full font-mono text-xs"
                    />
                  </label>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <label className="block space-y-1 text-xs">
                    <span className="font-medium">无风险利率</span>
                    <div className="flex items-center gap-1.5">
                      <Input
                        type="number"
                        step="0.01"
                        value={Number.isFinite(riskFreePct) ? riskFreePct : ""}
                        onChange={(event) =>
                          setRiskFreePct(Number(event.target.value))
                        }
                        disabled={readOnly}
                        aria-invalid={!riskFreeValid}
                        className="w-full font-mono tabular-nums"
                      />
                      <span className="shrink-0 text-muted-foreground">%</span>
                    </div>
                  </label>
                  <label className="block space-y-1 text-xs">
                    <span className="font-medium">再平衡带</span>
                    <div className="flex items-center gap-1.5">
                      <Input
                        type="number"
                        min={0}
                        step="0.5"
                        value={Number.isFinite(bandPct) ? bandPct : ""}
                        onChange={(event) => setBandPct(Number(event.target.value))}
                        disabled={readOnly}
                        aria-invalid={!bandValid}
                        className="w-full font-mono tabular-nums"
                      />
                      <span className="shrink-0 text-muted-foreground">%</span>
                    </div>
                  </label>
                </div>
              </div>

              <div className="flex flex-col gap-2 pt-1 sm:flex-row">
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={reoptimize}
                  disabled={!canOptimize || optimizeLoading}
                >
                  {optimizeLoading ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-1 h-4 w-4" />
                  )}
                  重新优化
                </Button>
                <Button
                  className="flex-1"
                  onClick={runBacktest}
                  disabled={!canBacktest || backtestLoading}
                >
                  {backtestLoading ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-1 h-4 w-4" />
                  )}
                  运行回测
                </Button>
              </div>
              <Button
                variant="outline"
                className="mt-2 w-full"
                onClick={() => {
                  if (readOnly) {
                    void handleCopyBasket();
                    return;
                  }
                  if (!viewer.userId) {
                    toast.error("请先登录后保存篮子", {
                      description: "登录后可保存为自己的篮子，或在 /dashboard 查看。",
                    });
                    return;
                  }
                  if (!saveName) setSaveName(loadedBasket?.name ?? "");
                  setSaveOpen(true);
                }}
                disabled={items.length === 0 || copying}
                title={
                  readOnly
                    ? "示例篮子只读：复制为自己的篮子后即可编辑保存"
                    : undefined
                }
              >
                {copying ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-1 h-4 w-4" />
                )}
                {readOnly
                  ? viewer.userId
                    ? "复制并编辑"
                    : "登录后复制并编辑"
                  : loadedBasket
                    ? "保存更改"
                    : "保存这个篮子"}
              </Button>
              {items.length === 0 && (
                <p className="text-[11px] text-muted-foreground">
                  先添加至少一个资产，按钮才会启用。
                </p>
              )}
              {loadedBasket && !readOnly && access && !access.canEdit ? (
                <p className="text-[11px] text-muted-foreground">
                  该篮子只读；仅管理员可编辑示例，普通用户可复制后编辑。
                </p>
              ) : null}
              {optimizeError && <BasketErrorPanel message={optimizeError} />}
            </CardContent>
          </Card>
        </div>

        <div className="mt-6">
          <BasketResults
            weights={displayWeights}
            nameByKey={nameByKey}
            assetCount={items.length}
            methodShort={basketMethodLabel(method)}
            diagnostics={optimizeResult?.diagnostics ?? null}
            optimizeLoading={optimizeLoading}
            optimizeError={optimizeError}
            optimizeDirty={optimizeDirty}
            backtest={backtest}
            backtestLoading={backtestLoading}
            backtestError={backtestError}
            backtestDirty={backtestDirty}
            bandPct={bandPct}
            isDark={isDark}
          />
        </div>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{loadedBasket ? "保存篮子更改" : "保存篮子"}</DialogTitle>
            <DialogDescription>保存后可在 /dashboard 查看、编辑与复制。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block space-y-1 text-xs">
              <span className="font-medium">名称</span>
              <Input value={saveName} onChange={(event) => setSaveName(event.target.value)} placeholder="例如：红利+黄金 风险平价" maxLength={80} />
            </label>
            <label className="block space-y-1 text-xs">
              <span className="font-medium">描述（可选）</span>
              <Input value={saveDesc} onChange={(event) => setSaveDesc(event.target.value)} placeholder="一句话说明" maxLength={500} />
            </label>
            <p className="text-[11px] text-muted-foreground">
              {items.length} 项资产 · {basketMethodLabel(method)} · {startDate} ~ {endDate}
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)} disabled={saving}>取消</Button>
            <Button onClick={handleSaveBasket} disabled={saving}>
              {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AssetPoolDialog
        open={poolOpen}
        onOpenChange={setPoolOpen}
        assets={poolAssets}
        selectedKeys={selectedKeys}
        onPick={addFromPool}
        loading={poolLoading}
        error={poolError ? basketErrorMessage(poolError) : null}
        onRetry={() => void refetchPool()}
      />
      <StockSearchDialog
        open={stockOpen}
        onOpenChange={setStockOpen}
        selectedKeys={selectedKeys}
        poolKeys={poolKeys}
        onPick={addStock}
      />
    </BasketModeShell>
  );
}
