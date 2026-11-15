"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  fetchBasket,
  optimizeBasket,
  saveBasket,
  updateBasket,
} from "@/lib/basket-api";
import { formatPct, normalizeRiskBudget } from "@/lib/basket-format";
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
import { ModeSwitch } from "./ModeSwitch";

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

export function BasketBuilder({ initialAssets = [] }: { initialAssets?: Asset[] }) {
  const { canManageAssets } = useAuth();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const [poolAssets, setPoolAssets] = useState<Asset[]>(initialAssets);
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
  const backtestController = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      backtestController.current?.abort();
    },
    [],
  );

  // ?basket=<id>：载入已保存的篮子配置（编辑模式）。
  useEffect(() => {
    const raw = searchParams.get("basket");
    if (!raw) return;
    const basketId = Number(raw);
    if (!Number.isFinite(basketId)) return;
    let cancelled = false;
    void (async () => {
      try {
        const record = await fetchBasket<BasketRecord>(basketId);
        if (cancelled) return;
        setLoadedBasket(record);
        setItems(
          record.assets.map((asset) => {
            const hit = initialAssets.find(
              (item) => item.symbol === asset.symbol && item.source === asset.source,
            );
            if (hit) return basketItemFromAsset(hit);
            return {
              key: basketKey(asset.symbol, asset.source),
              symbol: asset.symbol,
              source: asset.source,
              name: asset.symbol,
              adjustView: "hfq" as BasketAdjust,
              inPool: false,
              hasData: true,
            };
          }),
        );
        setMethod(record.method as BasketMethod);
        const params = (record.params ?? {}) as Record<string, unknown>;
        if (typeof params.lookback_days === "number") setLookback(params.lookback_days);
        if (typeof params.rebalance_band === "number") setBandPct(Number(params.rebalance_band) * 100);
        if (typeof params.risk_free === "number") setRiskFreePct(Number(params.risk_free) * 100);
        if (typeof params.start === "string") setStartDate(params.start);
        if (typeof params.end === "string") setEndDate(params.end);
        setSaveName(record.name);
        setSaveDesc(record.description ?? "");
        toast.success("已载入篮子「" + record.name + "」，可修改后重新运行回测");
      } catch (error) {
        if (!cancelled) toast.error(basketErrorMessage(error));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchParams, initialAssets]);

  const handleSaveBasket = async () => {
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
      const payload = {
        name: saveName.trim(),
        description: saveDesc.trim() || null,
        method,
        assets: items.map((item) => ({ symbol: item.symbol, source: item.source })),
        params,
        latest_result: latestResult,
      };
      if (loadedBasket) {
        await updateBasket(loadedBasket.basket_id, payload);
        toast.success("篮子已更新");
        setSaveOpen(false);
      } else {
        const created = await saveBasket(payload);
        toast.success("篮子已保存，可在 /dashboard 查看");
        setLoadedBasket({ ...payload, basket_id: created.basket_id, owner_user_id: null, created_at: "", updated_at: "" } as unknown as BasketRecord);
        setSaveOpen(false);
        router.replace("/builder?mode=basket&basket=" + created.basket_id, { scroll: false });
      }
    } catch (error) {
      toast.error(basketErrorMessage(error));
    } finally {
      setSaving(false);
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
    addItem(basketItemFromAsset(asset));
  };

  const addStock = (stock: StockSearchItem) => {
    const poolHit = poolAssets.find(
      (asset) => asset.symbol === stock.stock_code && asset.source === STOCK_SOURCE,
    );
    const item = basketItemFromStock(stock, poolHit);
    if (addItem(item)) notifyStockAdded(stock, Boolean(poolHit));
  };

  const removeItem = (key: string) => {
    setItems((previous) => previous.filter((item) => item.key !== key));
  };

  const changeAdjust = (key: string, adjust: BasketAdjust) => {
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
   * 通过后保存；后端按 stock_sina 自动抓 bfq/qfq/hfq 三口径，回测主口径 hfq。
   */
  const ingestStock = async (item: BasketItem) => {
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
      setPoolAssets((previous) =>
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
          ? "已接入，后台正在拉取 bfq/qfq/hfq 三口径历史行情"
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

  return (
    <div className="flex-1 bg-bg-subtle/30 pb-16">
      <div className="border-b border-border bg-background px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <ModeSwitch mode="basket" />
          <span className="hidden text-xs text-muted-foreground sm:inline">
            单层风险平价 · 不落库 · 股票回测口径 hfq
          </span>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">一篮子资产</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              选择资产与方法，自动计算目标权重，并按偏离带做再平衡回测。
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setPoolOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              资产池
            </Button>
            <Button size="sm" onClick={() => setStockOpen(true)}>
              <Search className="mr-1 h-4 w-4" />
              搜索股票
            </Button>
          </div>
        </div>

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
                      className={cn(
                        "rounded-md border px-2.5 py-2 text-left text-xs font-medium transition-colors",
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
                      className="w-full font-mono text-xs"
                    />
                  </label>
                  <label className="block space-y-1 text-xs">
                    <span className="font-medium">回测结束</span>
                    <Input
                      type="date"
                      value={endDate}
                      onChange={(event) => setEndDate(event.target.value)}
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
                  if (!saveName) setSaveName(loadedBasket?.name ?? "");
                  setSaveOpen(true);
                }}
                disabled={items.length === 0}
              >
                <Save className="mr-1 h-4 w-4" />
                {loadedBasket ? "保存更改" : "保存这个篮子"}
              </Button>
              {items.length === 0 && (
                <p className="text-[11px] text-muted-foreground">
                  先添加至少一个资产，按钮才会启用。
                </p>
              )}
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
      />
      <StockSearchDialog
        open={stockOpen}
        onOpenChange={setStockOpen}
        selectedKeys={selectedKeys}
        poolKeys={poolKeys}
        onPick={addStock}
      />
    </div>
  );
}
