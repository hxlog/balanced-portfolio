"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Check, ChevronRight, Plus, X, Lock } from "lucide-react";
import {
  api, Asset, Quadrant, QUADRANT_LABELS, METHOD_OPTIONS, BENCHMARK_OPTIONS,
  CreatePortfolioInput, DEFAULT_BENCHMARK_KEY, DEFAULT_MAX_WEIGHT_PCT,
  DEFAULT_DESCRIPTION, ASSET_CATEGORY_OPTIONS, ADJUST_LABEL,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ConfirmRecomputeDialog } from "@/components/ConfirmRecomputeDialog";
import { BacktestProgressDialog } from "@/components/BacktestProgressDialog";

const QUADRANT_ORDER: Quadrant[] = ["overheat", "stagflation", "recovery", "recession"];
const QUADRANT_COLOR: Record<Quadrant, string> = {
  overheat: "text-up",
  stagflation: "text-weak",
  recovery: "text-primary",
  recession: "text-down",
};

type Selected = Record<Quadrant, Asset[]>;
const emptySelection: Selected = { overheat: [], stagflation: [], recovery: [], recession: [] };

function keyOf(a: Asset | { symbol: string; source: string }) {
  return `${a.symbol}@${a.source}`;
}

export default function BuilderClient({
  initialAssets = [],
}: {
  initialAssets?: Asset[];
}) {
  return (
    <Suspense fallback={<div className="p-12 text-center text-muted-foreground">加载中...</div>}>
      <BuilderInner initialAssets={initialAssets} />
    </Suspense>
  );
}

function BuilderInner({ initialAssets = [] }: { initialAssets?: Asset[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const editIdParam = searchParams.get("id");
  const copyIdParam = searchParams.get("copy");
  const editId = editIdParam ? Number(editIdParam) : null;
  const copyId = copyIdParam ? Number(copyIdParam) : null;
  const isEditMode = editId != null && !Number.isNaN(editId);
  const isCopyMode = !isEditMode && copyId != null && !Number.isNaN(copyId);
  // 复制模式: 预填源组合参数, 但走 createPortfolio 建新组合。
  const sourceId = isEditMode ? editId : isCopyMode ? copyId : null;

  const [step, setStep] = useState(1);
  const [assets, setAssets] = useState<Asset[]>(initialAssets);
  const [selected, setSelected] = useState<Selected>(emptySelection);
  const { isWhitelisted, ready } = useAuth();
  const [portfolioName, setPortfolioName] = useState("我的组合");
  const [portfolioDescription, setPortfolioDescription] = useState(DEFAULT_DESCRIPTION);
  const [method, setMethod] = useState(METHOD_OPTIONS[0].value);
  const [ratio, setRatio] = useState<"sharpe" | "sortino">("sharpe");
  const [lookback, setLookback] = useState(156);
  const [benchmarkKey, setBenchmarkKey] = useState(DEFAULT_BENCHMARK_KEY);
  const [band, setBand] = useState(5);
  const [maxWeightPct, setMaxWeightPct] = useState(DEFAULT_MAX_WEIGHT_PCT);
  const [riskFreePct, setRiskFreePct] = useState(0);
  const [feePct, setFeePct] = useState(0.015);
  const [slippagePct, setSlippagePct] = useState(0.015);
  const [stampDutyPct, setStampDutyPct] = useState(0.05);
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 3);
    return d.toISOString().slice(0, 10);
  });
  const [loadingEdit, setLoadingEdit] = useState(isEditMode || isCopyMode);
  const [error, setError] = useState<string | null>(null);
  const [origSig, setOrigSig] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [savingMeta, setSavingMeta] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [resultPid, setResultPid] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoadingEdit(isEditMode || isCopyMode);

    (async () => {
      try {
        const catalog =
          initialAssets.length > 0
            ? initialAssets
            : (await api.getAssets()).assets;
        if (cancelled) return;
        if (initialAssets.length === 0) setAssets(catalog);
        const catalogMap = new Map(catalog.map((a) => [keyOf(a), a]));

        if (sourceId != null) {
          const p = await api.getPortfolio(sourceId);
          if (cancelled) return;
          setPortfolioName(isCopyMode ? `${p.name} 副本` : p.name);
          setPortfolioDescription(p.description || DEFAULT_DESCRIPTION);
          setMethod(p.method);
          setRatio(p.ratio as "sharpe" | "sortino");
          setLookback(p.lookback_days ?? 156);
          setBenchmarkKey(p.benchmark_key || DEFAULT_BENCHMARK_KEY);
          setBand((p.rebalance_band ?? 0.05) * 100);
          setMaxWeightPct(
            p.max_weight != null ? +(p.max_weight * 100).toFixed(2) : DEFAULT_MAX_WEIGHT_PCT
          );
          setRiskFreePct(+((p.risk_free_rate ?? 0) * 100).toFixed(4));
          setFeePct(+((p.fee_rate ?? 0) * 100).toFixed(4));
          setSlippagePct(+((p.slippage_rate ?? 0) * 100).toFixed(4));
          setStampDutyPct(+((p.stamp_duty_rate ?? 0) * 100).toFixed(4));
          setStartDate(p.start_date.slice(0, 10));

          const sel: Selected = { overheat: [], stagflation: [], recovery: [], recession: [] };
          for (const row of p.assets || []) {
            const q = row.quadrant as Quadrant;
            if (!QUADRANT_ORDER.includes(q)) continue;
            const a =
              catalogMap.get(keyOf(row)) ||
              ({ symbol: row.symbol, source: row.source, name: row.display_name || row.symbol } as Asset);
            if (!sel[q].some((x) => keyOf(x) === keyOf(a))) {
              sel[q].push(a);
            }
          }
          setSelected(sel);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoadingEdit(false);
      }
    })();

    return () => { cancelled = true; };
  }, [sourceId, isEditMode, isCopyMode]);

  const totalPlacements = useMemo(
    () => QUADRANT_ORDER.reduce((n, q) => n + selected[q].length, 0),
    [selected]
  );
  const uniqueCount = useMemo(() => {
    const s = new Set<string>();
    QUADRANT_ORDER.forEach((q) => selected[q].forEach((a) => s.add(keyOf(a))));
    return s.size;
  }, [selected]);

  const addAssets = (q: Quadrant, list: Asset[]) => {
    if (list.length === 0) return;
    setSelected((s) => {
      const existing = new Set(s[q].map(keyOf));
      const toAdd = list.filter((a) => !existing.has(keyOf(a)));
      return toAdd.length ? { ...s, [q]: [...s[q], ...toAdd] } : s;
    });
  };
  const removeAsset = (q: Quadrant, k: string) =>
    setSelected((s) => ({ ...s, [q]: s[q].filter((a) => keyOf(a) !== k) }));

  const steps = [
    { id: 1, title: "四象限选品" },
    { id: 2, title: "优化方法" },
    { id: 3, title: "回测参数" },
  ];

  // 回测相关参数签名(不含 name/description); 用于判断编辑是否需要重算
  const backtestSig = useMemo(() => {
    const assetSig = QUADRANT_ORDER.flatMap((q) =>
      selected[q].map((a) => `${a.symbol}@${a.source}#${q}`)
    ).sort().join(",");
    return JSON.stringify({
      method, ratio, lookback, startDate, benchmarkKey,
      maxWeightPct, band, riskFreePct, feePct, slippagePct, stampDutyPct, assetSig,
    });
  }, [method, ratio, lookback, startDate, benchmarkKey, maxWeightPct, band, riskFreePct, feePct, slippagePct, stampDutyPct, selected]);

  const backtestParamsChanged = origSig === null || origSig !== backtestSig;
  // 仅元数据(名称/描述)可直接保存的条件: 编辑模式(非复制)且回测参数未变
  const canMetaOnlySave = isEditMode && !isCopyMode && !backtestParamsChanged;

  // 编辑数据加载完成后, 锁定初始回测签名(用于变更检测); 复制模式不锁定(总是新建)。
  useEffect(() => {
    if (isEditMode && !isCopyMode && !loadingEdit && origSig === null) {
      setOrigSig(backtestSig);
    }
  }, [isEditMode, isCopyMode, loadingEdit, origSig, backtestSig]);

  const buildPayload = (): CreatePortfolioInput => ({
    name: portfolioName,
    description: portfolioDescription.trim() || DEFAULT_DESCRIPTION,
    method,
    ratio,
    lookback_days: lookback,
    start_date: startDate,
    benchmark_key: benchmarkKey,
    max_weight: maxWeightPct / 100,
    rebalance_band: band / 100,
    risk_free_rate: riskFreePct / 100,
    fee_rate: feePct / 100,
    slippage_rate: slippagePct / 100,
    stamp_duty_rate: stampDutyPct / 100,
    assets: QUADRANT_ORDER.flatMap((q) =>
      selected[q].map((a) => ({
        symbol: a.symbol,
        source: a.source,
        quadrant: q,
        display_name: a.name || a.symbol,
      }))
    ),
  });

  // 仅保存名称/描述, 不重算
  const handleMetaSave = async () => {
    if (editId == null) return;
    setError(null);
    setSavingMeta(true);
    try {
      await api.updatePortfolioMeta(editId, {
        name: portfolioName,
        description: portfolioDescription.trim() || DEFAULT_DESCRIPTION,
      });
      router.push(`/dashboard?id=${editId}`);
    } catch (e) {
      setError(String(e));
      setSavingMeta(false);
    }
  };

  // 需重算: 校验后打开确认框
  const handleSubmitClick = () => {
    setError(null);
    if (ratio === "sharpe" && (riskFreePct === null || Number.isNaN(riskFreePct))) {
      setError("选择夏普比率时必须填写无风险利率");
      return;
    }
    setConfirmOpen(true);
  };

  // 确认后提交并进入进度弹窗
  const startBacktest = async () => {
    setSubmitting(true);
    try {
      const payload = buildPayload();
      const { portfolio_id, task_id } = isEditMode && !isCopyMode && editId != null
        ? await api.updatePortfolio(editId, payload)
        : await api.createPortfolio(payload);
      setConfirmOpen(false);
      setResultPid(portfolio_id);
      if (task_id) {
        setTaskId(task_id);
        setProgressOpen(true);
      } else {
        await api.waitForPortfolio(portfolio_id);
        router.push(`/dashboard?id=${portfolio_id}`);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (!ready) {
    return <div className="p-12 text-center text-muted-foreground">加载中...</div>;
  }

  if (!isWhitelisted) {
    return (
      <div className="max-w-md mx-auto p-12 text-center space-y-4">
        <Lock className="w-10 h-10 mx-auto text-muted-foreground" />
        <h1 className="text-xl font-semibold">需要登录</h1>
        <p className="text-sm text-muted-foreground">
          仅白名单用户可{isEditMode ? "编辑" : "新建"}组合。请在右上角登录后重试。
        </p>
        <Button variant="outline" onClick={() => router.push("/dashboard")}>返回 Dashboard</Button>
      </div>
    );
  }

  if (loadingEdit) {
    return <div className="p-12 text-center text-muted-foreground">正在加载组合配置...</div>;
  }

  return (
    <div className="flex-1 bg-bg-subtle/30 pb-24">
      <div className="bg-background border-b border-border py-8 px-6 sticky top-16 z-40">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-2xl font-semibold mb-8 text-center">
            {isEditMode ? "编辑投资组合" : isCopyMode ? "复制投资组合" : "新增投资组合"}
          </h1>
          <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-6 sm:gap-0 relative">
            <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-px bg-border -z-10 hidden sm:block" />
            {steps.map((s) => {
              const isActive = s.id === step;
              const isPast = s.id < step;
              return (
                <div key={s.id} className="flex flex-col items-center gap-2 bg-background px-4">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium border-2 transition-colors ${
                    isActive ? "border-primary bg-primary text-primary-foreground"
                      : isPast ? "border-primary text-primary"
                      : "border-border text-muted-foreground bg-card"
                  }`}>
                    {isPast ? <Check className="w-4 h-4" /> : s.id}
                  </div>
                  <span className={`text-sm font-medium ${isActive || isPast ? "text-foreground" : "text-muted-foreground"}`}>
                    {s.title}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto p-6 mt-8">
        {error && (
          <div className="mb-6 bg-destructive/10 border border-destructive/30 text-destructive text-sm p-4 rounded-lg">
            {error}
          </div>
        )}

        {step === 1 && (
          <div className="space-y-6">
            <div className="text-center mb-8">
              <h2 className="text-xl font-medium">配置你的四象限矩阵</h2>
              <p className="text-muted-foreground mt-2">
                从资产库中选择标的放入对应的宏观环境象限中。同一品种可配置在多个象限, 回测时权重会自动加权整合。
                已配置 {totalPlacements} 项 · {uniqueCount} 个品种。
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 min-h-[500px]">
              {QUADRANT_ORDER.map((q) => (
                <Card key={q} className="flex flex-col">
                  <CardContent className="p-4 flex-1 flex flex-col">
                    <div className="flex justify-between items-center mb-4">
                      <div className={`text-sm font-medium ${QUADRANT_COLOR[q]}`}>{QUADRANT_LABELS[q]}</div>
                      <Badge variant="secondary">已选 {selected[q].length}</Badge>
                    </div>
                    <div className="flex flex-wrap gap-2 flex-1 content-start">
                      {selected[q].map((a) => (
                        <Badge key={keyOf(a)} variant="outline" className="pr-1 bg-card border-border text-foreground">
                          {a.name || a.symbol}
                          <X className="w-3 h-3 ml-1 text-muted-foreground cursor-pointer hover:text-foreground"
                            onClick={() => removeAsset(q, keyOf(a))} />
                        </Badge>
                      ))}
                      {selected[q].length === 0 && (
                        <p className="text-sm text-muted-foreground">该象限为空。</p>
                      )}
                    </div>
                    <AssetPicker
                      assets={assets}
                      usedInQuadrant={selected[q].map(keyOf)}
                      onPickMany={(list) => addAssets(q, list)}
                      quadrantLabel={QUADRANT_LABELS[q]}
                    />
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div className="text-center mb-8">
              <h2 className="text-xl font-medium">选择优化方法</h2>
              <p className="text-muted-foreground mt-2">不同的最优化目标会产生不同的权重分配方案。</p>
            </div>
            <div className="space-y-4">
              {METHOD_OPTIONS.map((m) => {
                const active = m.value === method;
                return (
                  <Card key={m.value} onClick={() => setMethod(m.value)}
                    className={`cursor-pointer transition-all ${active ? "border-primary ring-1 ring-primary/20 bg-primary/5" : "hover:border-primary/50"}`}>
                    <CardContent className="p-5 flex items-start gap-4">
                      <div className={`mt-1 w-5 h-5 rounded-full border flex items-center justify-center shrink-0 ${active ? "border-primary text-primary" : "border-border"}`}>
                        {active && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                      </div>
                      <div>
                        <h3 className={`font-medium mb-1 ${active ? "text-primary" : ""}`}>{m.title}</h3>
                        <p className="text-sm text-muted-foreground leading-relaxed">{m.desc}</p>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
            <div className="mt-8 pt-8 border-t border-border">
              <h3 className="font-medium mb-4">附属参数</h3>
              <div className="flex items-center justify-between p-4 bg-card border border-border rounded-lg">
                <div>
                  <div className="font-medium text-sm mb-1">优化指标</div>
                  <div className="text-sm text-muted-foreground">选择最大化夏普比率还是 Sortino 比率</div>
                </div>
                <div className="bg-bg-subtle p-1 rounded-md flex border border-border">
                  {(["sharpe", "sortino"] as const).map((r) => (
                    <div key={r} onClick={() => setRatio(r)}
                      className={`px-4 py-1.5 text-sm font-medium rounded cursor-pointer ${ratio === r ? "bg-background shadow-sm border border-border" : "text-muted-foreground"}`}>
                      {r === "sharpe" ? "夏普比率" : "Sortino 比率"}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6">
            <div className="text-center mb-8">
              <h2 className="text-xl font-medium">回测与计算参数</h2>
              <p className="text-muted-foreground mt-2">调整风险因子的计算窗口与回测起止时间。</p>
            </div>
            <Card>
              <CardContent className="p-6 space-y-8">
                <div>
                  <label className="block text-sm font-medium mb-2">组合名称</label>
                  <Input value={portfolioName} onChange={(e) => setPortfolioName(e.target.value)} className="w-full max-w-xs" />
                </div>
                <div className="border-t border-border pt-8">
                  <label className="block text-sm font-medium mb-2">组合描述</label>
                  <Input value={portfolioDescription} onChange={(e) => setPortfolioDescription(e.target.value)}
                    placeholder={DEFAULT_DESCRIPTION} className="w-full max-w-xs" />
                  <p className="text-sm text-muted-foreground mt-2">展示于 Dashboard 标题下方, 默认「组合描述」。</p>
                </div>
                <div className="border-t border-border pt-8">
                  <label className="block text-sm font-medium mb-2">回溯天数 (风险因子窗口)</label>
                  <div className="flex items-center gap-4">
                    <Input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value))}
                      className="w-full max-w-xs font-mono" />
                    <span className="text-sm text-muted-foreground">个交易日</span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">用过去 N 个交易日的日收益率方差作为风险因子进行计算。</p>
                </div>
                <div className="border-t border-border pt-8">
                  <label className="block text-sm font-medium mb-2">回测开始日期</label>
                  <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full max-w-xs" />
                  <p className="text-sm text-muted-foreground mt-2">受限于个别指数的成立时间，实际可回测日期可能晚于设定日期。</p>
                </div>
                <div className="border-t border-border pt-8">
                  <label className="block text-sm font-medium mb-2">对比基准</label>
                  <select value={benchmarkKey} onChange={(e) => setBenchmarkKey(e.target.value)}
                    className="w-full max-w-xs bg-input-background border border-border rounded-md px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50">
                    {BENCHMARK_OPTIONS.map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
                  </select>
                  <p className="text-sm text-muted-foreground mt-2">净值对比所用基准（信息比率固定以沪深300为基准）。</p>
                </div>
                <div className="border-t border-border pt-8">
                  <label className="block text-sm font-medium mb-2">单资产最大权重</label>
                  <div className="flex items-center gap-4">
                    <Input type="number" step="0.01" min={1} max={100} value={maxWeightPct}
                      onChange={(e) => setMaxWeightPct(Number(e.target.value))} className="w-full max-w-xs font-mono" />
                    <span className="text-sm text-muted-foreground">%</span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">
                    优化器硬约束上限, 默认 33.33%。需满足「独立品种数 × 上限 ≥ 100%」。
                  </p>
                </div>
                <div className="border-t border-border pt-8">
                  <label className="block text-sm font-medium mb-2">再平衡偏离带</label>
                  <div className="flex items-center gap-4">
                    <Input type="number" step="0.5" value={band} onChange={(e) => setBand(Number(e.target.value))}
                      className="w-full max-w-xs font-mono" />
                    <span className="text-sm text-muted-foreground">个百分点（绝对值）</span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">任一品种实际权重偏离当日最优目标超过该百分点时触发整体再平衡。默认 5。</p>
                </div>
                <div className="border-t border-border pt-8 grid md:grid-cols-3 gap-6">
                  <div>
                    <label className="block text-sm font-medium mb-2">
                      无风险利率 {ratio === "sharpe" && <span className="text-destructive">*</span>}
                    </label>
                    <div className="flex items-center gap-3">
                      <Input
                        type="number"
                        step="0.01"
                        value={riskFreePct}
                        onChange={(e) => setRiskFreePct(Number(e.target.value))}
                        className="w-full max-w-xs font-mono"
                      />
                      <span className="text-sm text-muted-foreground">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">夏普比率口径必填；按年化利率输入。</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">手续费</label>
                    <div className="flex items-center gap-3">
                      <Input
                        type="number"
                        step="0.001"
                        value={feePct}
                        onChange={(e) => setFeePct(Number(e.target.value))}
                        className="w-full max-w-xs font-mono"
                      />
                      <span className="text-sm text-muted-foreground">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">按单边换手在调仓日扣除。</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">滑点</label>
                    <div className="flex items-center gap-3">
                      <Input
                        type="number"
                        step="0.001"
                        value={slippagePct}
                        onChange={(e) => setSlippagePct(Number(e.target.value))}
                        className="w-full max-w-xs font-mono"
                      />
                      <span className="text-sm text-muted-foreground">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">买卖双边均缴，模拟价差与成交冲击。</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">印花税（卖出）</label>
                    <div className="flex items-center gap-3">
                      <Input
                        type="number"
                        step="0.001"
                        value={stampDutyPct}
                        onChange={(e) => setStampDutyPct(Number(e.target.value))}
                        className="w-full max-w-xs font-mono"
                      />
                      <span className="text-sm text-muted-foreground">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">仅卖出方缴纳，A股默认 0.05%。</p>
                  </div>
                </div>
              </CardContent>
            </Card>

          </div>
        )}
      </div>

      <ConfirmRecomputeDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={startBacktest}
        title={isEditMode ? "确认保存并重算" : "确认生成组合"}
        confirmLabel={isEditMode ? "保存并重算" : "生成组合"}
        busy={submitting}
      />
      <BacktestProgressDialog
        taskId={taskId}
        portfolioId={resultPid}
        open={progressOpen}
        title={isEditMode ? "正在保存并重算" : "正在生成组合"}
        onOpenChange={(v) => {
          setProgressOpen(v);
          if (!v && resultPid) router.push(`/dashboard?id=${resultPid}`);
        }}
        onDone={(id) => router.push(`/dashboard?id=${id ?? resultPid ?? ""}`)}
      />

      <div className="fixed bottom-0 left-0 w-full bg-background border-t border-border p-4 z-40">
        <div className="max-w-4xl mx-auto flex justify-between items-center">
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(1, s - 1))} disabled={step === 1 || submitting || savingMeta}>
            上一步
          </Button>
          {step < 3 ? (
            <Button onClick={() => setStep((s) => Math.min(3, s + 1))} disabled={step === 1 && uniqueCount === 0}>
              下一步 <ChevronRight className="w-4 h-4 ml-1" />
            </Button>
          ) : isWhitelisted ? (
            canMetaOnlySave ? (
              <Button onClick={handleMetaSave} disabled={savingMeta || uniqueCount === 0}>
                {savingMeta ? "保存中..." : "保存"}
              </Button>
            ) : (
              <Button onClick={handleSubmitClick} disabled={submitting || uniqueCount === 0}>
                {isEditMode ? "保存并重算" : "生成组合"}
              </Button>
            )
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Lock className="w-4 h-4" /> 仅白名单用户可{isEditMode ? "编辑" : "创建"}组合，请在右上角登录
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AssetPicker({
  assets, usedInQuadrant, onPickMany, quadrantLabel,
}: {
  assets: Asset[];
  usedInQuadrant: string[];
  onPickMany: (list: Asset[]) => void;
  quadrantLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [vendor, setVendor] = useState<string>("all");
  const [pending, setPending] = useState<Set<string>>(new Set());
  const usedSet = useMemo(() => new Set(usedInQuadrant), [usedInQuadrant]);
  const vendors = useMemo(
    () => Array.from(new Set(assets.map((a) => a.vendor).filter(Boolean))) as string[],
    [assets],
  );

  const filtered = assets.filter(
    (a) =>
      !usedSet.has(keyOf(a)) &&
      (category === "all" || a.category === category) &&
      (vendor === "all" || a.vendor === vendor) &&
      (q === "" || (a.name || "").includes(q) || a.symbol.toLowerCase().includes(q.toLowerCase()))
  );

  const toggle = (a: Asset) => {
    const k = keyOf(a);
    setPending((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const confirm = () => {
    const picked = assets.filter((a) => pending.has(keyOf(a)));
    onPickMany(picked);
    setPending(new Set());
    setQ("");
    setOpen(false);
  };

  const handleOpenChange = (v: boolean) => {
    setOpen(v);
    if (!v) {
      setPending(new Set());
      setQ("");
      setCategory("all");
      setVendor("all");
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="w-full mt-4 border-dashed text-muted-foreground">
          <Plus className="w-4 h-4 mr-1" /> 添加资产
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>添加资产到「{quadrantLabel}」</DialogTitle>
        </DialogHeader>
        <div className="flex gap-2 mb-3">
          <Input placeholder="搜索名称或代码..." value={q} onChange={(e) => setQ(e.target.value)} className="flex-1" />
          <Select value={vendor} onValueChange={setVendor}>
            <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部数据源</SelectItem>
              {vendors.map((v) => (
                <SelectItem key={v} value={v}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类别</SelectItem>
              {ASSET_CATEGORY_OPTIONS.map((c) => (
                <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="max-h-80 overflow-auto space-y-1">
          {filtered.map((a) => {
            const k = keyOf(a);
            const checked = pending.has(k);
            return (
              <div
                key={k}
                role="button"
                tabIndex={0}
                onClick={() => toggle(a)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggle(a);
                  }
                }}
                className={`w-full text-left px-3 py-2 rounded-md hover:bg-accent flex items-center gap-3 cursor-pointer ${checked ? "bg-accent/60" : ""}`}
              >
                <div
                  className={`size-4 shrink-0 rounded-[4px] border flex items-center justify-center ${
                    checked ? "bg-primary border-primary text-primary-foreground" : "border-border bg-input-background"
                  }`}
                >
                  {checked && <Check className="w-3 h-3" />}
                </div>
                <span className="text-sm flex-1">{a.name || a.symbol}</span>
                {a.vendor ? (
                  <Badge variant="secondary" className="font-normal h-5 px-1.5 text-[10px]">{a.vendor}</Badge>
                ) : null}
                <span className="text-xs text-muted-foreground font-mono">
                  {a.symbol}{a.adjust ? ` · ${ADJUST_LABEL[a.adjust] ?? a.adjust}` : ""}{a.category ? ` · ${a.category}` : ""}
                </span>
              </div>
            );
          })}
          {filtered.length === 0 && <p className="text-sm text-muted-foreground px-3 py-4">无可选资产</p>}
        </div>
        <DialogFooter className="flex-row justify-between sm:justify-between items-center gap-2">
          <span className="text-sm text-muted-foreground">已选 {pending.size} 项</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => handleOpenChange(false)}>取消</Button>
            <Button onClick={confirm} disabled={pending.size === 0}>确认添加</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
