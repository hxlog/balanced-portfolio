"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, ArrowUpDown, CheckCircle2, Download, Loader2, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, AdminAsset, DataSource, ADJUST_LABEL, ASSET_ADJUST_OPTIONS } from "@/lib/api";
import {
  ASSET_CREATE_DEFAULTS, buildExtraParams, parseProbeFailure, validateAssetInput,
  type ProbeFailure,
} from "@/lib/asset-form";
import { useAuth } from "@/lib/auth";
import { BacktestProgressDialog } from "@/components/BacktestProgressDialog";

/** 资产分类枚举(对应 bp_index_config.category) */
const CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "index", label: "index · 指数" },
  { value: "etf", label: "etf · ETF 基金" },
  { value: "commodity", label: "commodity · 商品期货" },
  { value: "bond", label: "bond · 债券指数" },
];

type PortfolioRef = { portfolio_id: number; name: string };

/**
 * 「会影响哪些组合」提示块。删除/停用/批量操作前如实列出引用该资产的组合,
 * 以及「删除后组合下次重算会变化」的后果说明 —— 避免用户在不知情的情况下改动线上组合。
 */
function AffectedPortfolios({
  refs,
  action,
}: {
  refs: PortfolioRef[];
  action: "delete" | "disable" | "enable";
}) {
  if (action === "enable") return null;
  if (refs.length === 0) {
    return (
      <span className="text-muted-foreground">当前没有组合引用这些标的。</span>
    );
  }
  return (
    <>
      将影响 <span className="font-medium text-foreground">{refs.length}</span> 个组合：
      <span className="text-foreground">
        {refs.map((p) => p.name).join("、")}
      </span>
      {action === "delete" &&
        "（组合下次重算时该标的将不再纳入，净值与持仓会随之变化）"}
      {action === "disable" &&
        "（停用只影响 builder 可选性，已有组合在重算时仍可继续使用该标的）"}
    </>
  );
}

/** 逻辑源短名(仅用于筛选下拉展示; 值仍是 logical_source 原文, 保证筛选与表格口径一致) */
const LOGICAL_SOURCE_LABEL: Record<string, string> = {
  cn_index: "cn_index · 指数聚合",
  hk_index: "hk_index · 港股指数",
  global_index: "global_index · 全球指数",
  etf: "etf · ETF 聚合",
};

const LOGICAL_SOURCE_LABEL_CN: Record<string, string> = {
  cn_index: "指数聚合",
  hk_index: "港股指数",
  global_index: "全球指数",
  etf: "ETF 聚合",
};

/** 资产 key: 全栈通用口径 `{symbol}@{source}` */
const assetKey = (a: { symbol: string; source: string }) => `${a.symbol}@${a.source}`;

/** 逻辑源展示名(表格/确认弹窗共用, 与第 3 列「代码 / 源」口径一致) */
function logicalSourceLabel(a: AdminAsset): string {
  const ls = a.logical_source;
  if (!ls) return a.source;
  const cn = LOGICAL_SOURCE_LABEL_CN[ls];
  return cn ? `${cn} · ${a.source}` : a.source;
}

export default function AdminAssetsPage() {
  const { isSuperAdmin, canManageAssets, ready } = useAuth();
  const [assets, setAssets] = useState<AdminAsset[]>([]);
  const [sources, setSources] = useState<DataSource[]>([]);
  // loading 仅首屏 true; 后续刷新走 refreshing —— 刷新期间**不卸载** <Table>, 避免容器塌陷导致滚动位置复位。
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const loadedRef = useRef(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [probeOk, setProbeOk] = useState(false);
  const [probeResult, setProbeResult] = useState<string | null>(null);
  // probe 失败的结构化结论: canSaveAnyway=true(接口可达但被限频挡住) 时给出「仍要保存」出口
  const [probeFailure, setProbeFailure] = useState<ProbeFailure | null>(null);
  const [form, setForm] = useState({ ...ASSET_CREATE_DEFAULTS });
  // 列表筛选/排序
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [laggingOnly, setLaggingOnly] = useState(false);
  const [minRows, setMinRows] = useState("");
  const [rowsSortDesc, setRowsSortDesc] = useState<boolean | null>(null);
  const [lagSortDesc, setLagSortDesc] = useState<boolean | null>(null);
  // 多选批量操作
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchOpen, setBatchOpen] = useState<null | "delete" | "enable" | "disable">(null);
  // 全量增量拉取(异步任务) + 重算所有就绪组合。
  // ⚠️ 必须在早返回(!ready/!isSuperAdmin)之前调用——否则 F5 刷新时 ready 由 false→true,
  //    hook 数量突变会触发 React Rules of Hooks 违规, 整页报 "This page couldn't load"。
  const [syncAllTaskId, setSyncAllTaskId] = useState<string | null>(null);
  const [syncAllOpen, setSyncAllOpen] = useState(false);
  const [enqueueBusy, setEnqueueBusy] = useState(false);
  // 资产 -> 引用它的组合。删除/停用前如实列出「会波及哪些组合」。
  const [assetRefs, setAssetRefs] = useState<Record<string, { portfolio_id: number; name: string }[]>>({});

  /** 拉一次「资产 → 引用组合」映射(失败静默: 只是提示增强, 不影响主流程)。 */
  const loadAssetRefs = async () => {
    try {
      const res = await api.listAssetPortfolioRefs();
      setAssetRefs(
        Object.fromEntries(res.refs.map((r) => [r.key, r.portfolios])),
      );
    } catch {
      /* 提示增强失败不阻断资产管理 */
    }
  };

  /** 刷新列表。首次渲染用 loading(整表占位), 之后一律 refreshing(表格保持挂载, 只显示细进度指示)。 */
  const load = async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent ?? loadedRef.current;
    if (silent) setRefreshing(true);
    else setLoading(true);
    try {
      const [a, s] = await Promise.all([api.listAdminAssets(), api.listDataSources()]);
      setAssets(a.assets);
      setSources(s.data_sources);
      loadedRef.current = true;
      // 组合引用随列表一起刷新(不阻塞主流程): 删除/停用确认框要据此列出受影响组合
      void loadAssetRefs();
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (canManageAssets) void load();
  }, [canManageAssets]);

  const selectedSource = useMemo(
    () => sources.find((s) => s.code === form.source),
    [sources, form.source],
  );

  // 可新增的数据源(is_addable=false 走独立 pipeline, 如 futures_cffex 由 CFFEX backfill 维护)。
  // undefined 视为可添加, 兼容未透出该列的旧后端。
  const addableSources = useMemo(
    () => sources.filter((s) => s.is_addable !== false),
    [sources],
  );

  // 数据源筛选项来自**资产上实际出现的 logical_source**(表格第 3 列渲染的就是它),
  // 不再用 sources.vendor —— 两者不是一回事, 旧实现会出现「选了筛不到 / 筛了还显示」。
  const logicalSources = useMemo(
    () => Array.from(new Set(assets.map((a) => a.logical_source).filter(Boolean))).sort() as string[],
    [assets],
  );

  const filteredAssets = useMemo(() => {
    const q = search.trim().toLowerCase();
    const minN = minRows.trim() === "" ? null : Number(minRows);
    let list = assets.filter((a) => {
      if (q && !(`${a.symbol}`.toLowerCase().includes(q) || `${a.name ?? ""}`.toLowerCase().includes(q))) return false;
      if (sourceFilter !== "all" && a.logical_source !== sourceFilter) return false;
      if (statusFilter === "enabled" && (a.is_deleted || a.is_selectable === false)) return false;
      if (statusFilter === "disabled" && a.is_selectable !== false) return false;
      if (statusFilter === "deleted" && !a.is_deleted) return false;
      if (laggingOnly && a.is_lagging !== true) return false;
      if (minN != null && !Number.isNaN(minN) && (a.clean_rows || 0) < minN) return false;
      return true;
    });
    if (rowsSortDesc !== null) {
      list = [...list].sort((a, b) =>
        rowsSortDesc ? (b.clean_rows || 0) - (a.clean_rows || 0) : (a.clean_rows || 0) - (b.clean_rows || 0),
      );
    }
    if (lagSortDesc !== null) {
      // 缺失(旧后端 / 无清洗日)恒排最后, 与升降序无关: 用 lag_trading_days ?? -1 参与比较时,
      // 降序会把 -1 甩到末位、升序却把它顶到最前 —— 两种序都不该让"没有数据"冒头。
      const lag = (x: AdminAsset) => x.lag_trading_days;
      const missing = (x: AdminAsset) => (lag(x) == null ? 1 : 0);
      list = [...list].sort((a, b) => {
        const ma = missing(a), mb = missing(b);
        if (ma !== mb) return ma - mb;
        if (ma === 1) return 0;
        const la = lag(a) as number, lb = lag(b) as number;
        return lagSortDesc ? lb - la : la - lb;
      });
    }
    return list;
  }, [assets, search, sourceFilter, statusFilter, laggingOnly, minRows, rowsSortDesc, lagSortDesc]);

  const laggingCount = useMemo(() => assets.filter((a) => a.is_lagging === true).length, [assets]);

  // 选中态与会话数据对齐: 已从列表消失的 key 自动剔除(软删除/筛选变化都不会留下幽灵选中)
  const selectedAssets = useMemo(
    () => assets.filter((a) => selected.has(assetKey(a))),
    [assets, selected],
  );
  const allVisibleSelected = filteredAssets.length > 0 && filteredAssets.every((a) => selected.has(assetKey(a)));
  const someVisibleSelected = !allVisibleSelected && filteredAssets.some((a) => selected.has(assetKey(a)));

  const toggleOne = (key: string, next: boolean) => {
    setSelected((s) => {
      const n = new Set(s);
      if (next) n.add(key);
      else n.delete(key);
      return n;
    });
  };

  const toggleAllVisible = (next: boolean) => {
    setSelected((s) => {
      const n = new Set(s);
      for (const a of filteredAssets) {
        const k = assetKey(a);
        if (next) n.add(k);
        else n.delete(k);
      }
      return n;
    });
  };

  if (!ready) return <div className="p-12 text-center text-muted-foreground">加载中...</div>;
  if (!canManageAssets) return <div className="p-12 text-center text-destructive">需要资产编辑权限</div>;

  const updateForm = (patch: Partial<typeof form>) => {
    setForm((f) => ({ ...f, ...patch }));
    setProbeOk(false);
    setProbeResult(null);
    setProbeFailure(null);
  };

  /** 与保存落库口径一致的 extra_params —— 口径定义在 @/lib/asset-form, 与 builder 共用同一份。 */
  const extraParams = buildExtraParams(form.source, form.category, form.adjust);

  const probeForm = async () => {
    const key = `${form.symbol}@${form.source}`;
    setBusyKey(key);
    setProbeOk(false);
    setProbeResult(null);
    setProbeFailure(null);
    try {
      const res = await api.probeAdminAsset(form.source, form.symbol, extraParams);
      setProbeOk(true);
      setProbeResult(`读取成功：${res.first_date} ~ ${res.last_date}，${res.rows} 行，用时 ${res.elapsed_ms}ms`);
      await load();
    } catch (e) {
      setProbeFailure(parseProbeFailure(e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  /** 真正落库。allowUnreachable=true 时放行「接口可达但被限频挡住」的资产。 */
  const doSave = async (allowUnreachable: boolean) => {
    const invalid = validateAssetInput(form);
    if (invalid) {
      toast.error(invalid);
      return;
    }
    if (!probeOk && !allowUnreachable) {
      toast.error("请先测试读取成功后再保存");
      return;
    }
    try {
      const res = await api.saveAdminAsset({
        ...form,
        category: form.category || null,
        start_date: form.start_date || null,
        adjust: extraParams.adjust ?? null,
        is_deleted: 0,
      });
      // 保留表单字段(数据源/分类/起始日/代码/名称)以便连续新增相似标的; 仅清探测状态。
      setProbeOk(false);
      setProbeResult(null);
      setProbeFailure(null);
      if (res.ingest_queued) {
        toast.success("已保存, 正在后台拉取历史行情(可稍后在列表点「增量」查看进度)");
      } else {
        toast.success("已保存");
      }
      await load();
      // 失效 /builder 资产缓存, 让新加标的立即可选(失败不阻断: 非超管调用会被 403 吞掉)
      await api.revalidateAssets().catch(() => {});
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    }
  };

  const save = () => doSave(probeOk);

  // 删除确认由行内 AlertDialog 承担; 此处只执行软删除。
  const remove = async (a: AdminAsset) => {
    try {
      await api.deleteAdminAsset(a.source, a.symbol);
      await load();
      await api.revalidateAssets().catch(() => {});
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    }
  };

  const syncAll = async () => {
    try {
      const res = await api.syncAllAssets();
      setSyncAllTaskId(res.task_id);
      setSyncAllOpen(true);
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    }
  };

  const enqueueReady = async () => {
    setEnqueueBusy(true);
    try {
      const res = await api.enqueueReadyPortfolios();
      toast.success(`已排队 ${res.queued} 个组合的 T-1 更新`);
      await load();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setEnqueueBusy(false);
    }
  };

  const probe = async (a: AdminAsset) => {
    const key = `${a.symbol}@${a.source}`;
    setBusyKey(key);
    try {
      // 与落库 extra_params 同口径: ETF 用已保存的 adjust, 中债国债用财富口径, 其余为空。
      const res = await api.probeAdminAsset(a.source, a.symbol, buildExtraParams(a.source, a.category, a.adjust));
      toast.success(`读取成功: ${res.first_date} ~ ${res.last_date}, ${res.rows} 行, ${res.elapsed_ms}ms`);
      await load();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  const sync = async (a: AdminAsset) => {
    const key = `${a.symbol}@${a.source}`;
    setBusyKey(key);
    try {
      const res = await api.syncAdminAsset(a.source, a.symbol);
      toast.success(`增量拉取完成: 写入 ${res.rows} 行（${res.detail || res.status}）`);
      await load();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  const refreshStatus = async () => {
    setRefreshing(true);
    try {
      await api.refreshAdminAssetStatus();
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  const toggleSelectable = async (a: AdminAsset, next: boolean) => {
    const key = `${a.symbol}@${a.source}`;
    setBusyKey(key);
    // 乐观更新
    setAssets((list) => list.map((x) => (x.symbol === a.symbol && x.source === a.source ? { ...x, is_selectable: next } : x)));
    try {
      await api.setAssetSelectable(a.source, a.symbol, next);
      await api.revalidateAssets().catch(() => {});
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  /** 批量删除: 串行执行(并发受控), 单个失败不中断, 最后汇总 toast。 */
  const runBatchDelete = async () => {
    const targets = selectedAssets;
    setBatchBusy(true);
    const failed: { key: string; reason: string }[] = [];
    let ok = 0;
    for (const a of targets) {
      try {
        await api.deleteAdminAsset(a.source, a.symbol);
        ok += 1;
      } catch (e) {
        failed.push({ key: assetKey(a), reason: String(e instanceof Error ? e.message : e) });
      }
    }
    await api.revalidateAssets().catch(() => {});
    await load();
    setSelected(new Set());
    setBatchBusy(false);
    setBatchOpen(null);
    if (failed.length === 0) {
      toast.success(`已删除 ${ok} 个标的`);
    } else {
      toast.error(`删除完成：成功 ${ok} 个，失败 ${failed.length} 个`, {
        description: failed.slice(0, 5).map((f) => `${f.key}: ${f.reason}`).join("\n")
          + (failed.length > 5 ? `\n…另有 ${failed.length - 5} 个失败项` : ""),
      });
    }
  };

  /** 批量启用/停用: 复用既有 PATCH /selectable 端点, 串行执行 + 失败汇总。 */
  const runBatchSelectable = async (next: boolean) => {
    const targets = selectedAssets.filter((a) => a.is_selectable !== next);
    setBatchBusy(true);
    const failed: { key: string; reason: string }[] = [];
    let ok = 0;
    for (const a of targets) {
      try {
        await api.setAssetSelectable(a.source, a.symbol, next);
        ok += 1;
      } catch (e) {
        failed.push({ key: assetKey(a), reason: String(e instanceof Error ? e.message : e) });
      }
    }
    await api.revalidateAssets().catch(() => {});
    await load();
    setSelected(new Set());
    setBatchBusy(false);
    setBatchOpen(null);
    const verb = next ? "启用" : "停用";
    if (failed.length === 0) {
      toast.success(`已${verb} ${ok} 个标的`);
    } else {
      toast.error(`${verb}完成：成功 ${ok} 个，失败 ${failed.length} 个`, {
        description: failed.slice(0, 5).map((f) => `${f.key}: ${f.reason}`).join("\n")
          + (failed.length > 5 ? `\n…另有 ${failed.length - 5} 个失败项` : ""),
      });
    }
  };

  const probing = busyKey === `${form.symbol}@${form.source}`;

  /** 选中集合涉及的组合并集(去重), 供批量确认框如实提示影响面。 */
  const selectedPortfolioRefs = (() => {
    const seen = new Map<number, PortfolioRef>();
    for (const a of selectedAssets) {
      for (const p of assetRefs[assetKey(a)] ?? []) {
        if (!seen.has(p.portfolio_id)) seen.set(p.portfolio_id, p);
      }
    }
    return [...seen.values()].sort((x, y) => x.portfolio_id - y.portfolio_id);
  })();

  return (
    <div className="flex-1 p-6 max-w-[1440px] mx-auto w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">资产管理</h1>
        <p className="text-sm text-muted-foreground mt-1">
          管理可选投资品、测试数据源读取，并查看最近行情与清洗状态。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">新增 / 更新投资品</CardTitle>
          <CardDescription>
            先选数据源 → 按提示填写该源的 symbol 格式 → 点「测试」确认能读取 → 保存。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5 pt-0 sm:pt-0">
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
            {/* 数据源 */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">数据源 (source)</label>
              <Select value={form.source} onValueChange={(v) => updateForm({ source: v })}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择数据源" />
                </SelectTrigger>
                <SelectContent className="max-w-[min(32rem,90vw)]">
                  {addableSources.map((s) => (
                    <SelectItem key={s.code} value={s.code}>
                      {s.vendor ? `${s.vendor} · ` : ""}{s.code} · {s.asset_class}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {selectedSource?.description || "akshare 行情源；不同源 symbol 书写格式不同。"}
              </p>
            </div>

            {/* symbol */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">代码 (symbol)</label>
              <Input
                placeholder={selectedSource?.symbol_hint || "该数据源要求的原生 symbol"}
                value={form.symbol}
                onChange={(e) => updateForm({ symbol: e.target.value })}
              />
              <p className="text-xs text-muted-foreground leading-relaxed">
                {selectedSource?.symbol_hint
                  ? `书写格式：${selectedSource.symbol_hint}`
                  : "按所选数据源接口要求填写。"}
              </p>
            </div>

            {/* 名称 */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">名称 (name)</label>
              <Input
                placeholder="中文展示名，如 沪深300"
                value={form.name}
                onChange={(e) => updateForm({ name: e.target.value })}
              />
              <p className="text-xs text-muted-foreground leading-relaxed">展示于组合构建器与持仓表的中文名。</p>
            </div>

            {/* 分类 */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">分类 (category)</label>
              <Select value={form.category} onValueChange={(v) => updateForm({ category: v })}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择分类" />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((c) => (
                    <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground leading-relaxed">资产大类，仅用于分组展示。</p>
            </div>

            {/* 复权(仅 ETF) */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">复权 (adjust)</label>
              <Select
                value={form.adjust}
                onValueChange={(v) => updateForm({ adjust: v })}
                disabled={form.category !== "etf"}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择复权类型" />
                </SelectTrigger>
                <SelectContent>
                  {ASSET_ADJUST_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {form.category === "etf"
                  ? "ETF 复权类型; 后复权(hfq) 为默认, 价格连续可比。"
                  : "仅 ETF 类目支持复权; 指数/商品/债券为原始行情。"}
              </p>
            </div>

            {/* 起始日 */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">起始日 (start_date)</label>
              <Input
                type="date"
                value={form.start_date}
                onChange={(e) => updateForm({ start_date: e.target.value })}
              />
              <p className="text-xs text-muted-foreground leading-relaxed">
                首拉起始日；留空则从 2017-01-01 拉取，成功后回写真实最早交易日。
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" onClick={probeForm} disabled={!form.symbol || !form.source || probing}>
              {probing ? <RefreshCw className="w-4 h-4 mr-1 animate-spin" /> : <Activity className="w-4 h-4 mr-1" />}
              测试读取
            </Button>
            <Button
              onClick={() => save()}
              disabled={!form.symbol || !form.source || !form.name || (!probeOk && !probeFailure?.canSaveAnyway)}
            >
              <Plus className="w-4 h-4 mr-1" /> 保存
            </Button>
            {/* 接口可达但本次拉不到(反爬/限频/超时): 放行保存, 落库后由后台 ingest 补拉。
                这种情况下按钮语义要写清楚, 避免用户以为数据已经就绪。 */}
            {!probeOk && probeFailure?.canSaveAnyway && (
              <Button variant="secondary" onClick={() => doSave(true)} disabled={!form.symbol || !form.source || !form.name}>
                仍要保存并后台补拉
              </Button>
            )}
            {(probeResult || probeFailure) && (
              <div className={`text-sm ${probeFailure ? "text-destructive" : "text-muted-foreground"}`}>
                {probeFailure?.message || probeResult}
              </div>
            )}
          </div>
          {!probeOk && probeFailure?.canSaveAnyway && (
            <p className="text-xs text-muted-foreground">
              该数据源本次未返回数据(多为反爬/限频/IP 封锁, 而非代码写错)。可以先保存,
              系统会在后台重试拉取; 数据到位前该投资品在组合构建器里仍可选, 但回测不含其行情。
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">投资品列表</CardTitle>
              {refreshing && (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" aria-label="刷新中" />
              )}
            </div>
            <div className="flex items-center gap-2">
              {isSuperAdmin && (
                <Button variant="outline" size="sm" onClick={enqueueReady} disabled={enqueueBusy}>
                  <RefreshCw className={`w-4 h-4 mr-1 ${enqueueBusy ? "animate-spin" : ""}`} />
                  重算所有就绪组合
                </Button>
              )}
              {isSuperAdmin && (
                <Button variant="outline" size="sm" onClick={syncAll} disabled={loading || refreshing}>
                  <Download className="w-4 h-4 mr-1" />
                  拉取增量数据
                </Button>
              )}
              {isSuperAdmin && (
                <Button variant="outline" size="sm" onClick={refreshStatus} disabled={loading || refreshing}>
                  <RefreshCw className={`w-4 h-4 mr-1 ${refreshing ? "animate-spin" : ""}`} />
                  刷新状态
                </Button>
              )}
              {isSuperAdmin && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="outline" size="sm">
                      <RefreshCw className="w-4 h-4 mr-1" />强制重算全部组合
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>强制重算全部组合？</AlertDialogTitle>
                      <AlertDialogDescription>
                        将对所有组合（含公共案例）重新执行 4 种方法的回测，单个组合约需 2–10 分钟，期间组合不可编辑。此操作不可撤销。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={async () => {
                          try {
                            const r = await api.recomputeAllPortfolios();
                            toast.success(`已入队 ${r.enqueued} 个组合的重算任务`);
                            await load();
                          } catch (e) {
                            toast.error(String(e instanceof Error ? e.message : e));
                          }
                        }}
                      >
                        确认重算
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          </div>
          <CardDescription>
            停用后 builder 四象限不可选，但后台仍定时更新；删除则停更。
          </CardDescription>
          <div className="flex flex-wrap items-center gap-2 pt-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="搜索名称 / Symbol"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8"
              />
            </div>
            <Select value={sourceFilter} onValueChange={setSourceFilter}>
              <SelectTrigger className="w-[190px]"><SelectValue placeholder="逻辑源" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部逻辑源</SelectItem>
                {logicalSources.map((v) => (
                  <SelectItem key={v} value={v}>{LOGICAL_SOURCE_LABEL[v] ?? v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[130px]"><SelectValue placeholder="状态" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="enabled">启用</SelectItem>
                <SelectItem value="disabled">停用</SelectItem>
                <SelectItem value="deleted">已删除</SelectItem>
              </SelectContent>
            </Select>
            <label className="flex items-center gap-1.5 text-sm text-muted-foreground whitespace-nowrap">
              <Checkbox
                checked={laggingOnly}
                onCheckedChange={(v) => setLaggingOnly(v === true)}
                aria-label="仅显示滞后"
              />
              仅显示滞后
              {laggingCount > 0 && <span className="font-mono text-xs">({laggingCount})</span>}
            </label>
            <Input
              type="number"
              min={0}
              placeholder="最小行数"
              value={minRows}
              onChange={(e) => setMinRows(e.target.value)}
              className="w-[110px] font-mono"
            />
            <span className="text-xs text-muted-foreground">共 {filteredAssets.length} 项</span>
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto pt-0 sm:pt-0">
          {loading ? (
            <div className="py-12 text-center text-muted-foreground">加载中...</div>
          ) : (
            <Table className="min-w-[1080px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 px-2">
                    <Checkbox
                      checked={allVisibleSelected ? true : someVisibleSelected ? "indeterminate" : false}
                      onCheckedChange={(v) => toggleAllVisible(v === true)}
                      aria-label="全选当前筛选结果"
                      disabled={filteredAssets.length === 0}
                    />
                  </TableHead>
                  <TableHead className="min-w-[140px] max-w-[200px]">名称</TableHead>
                  <TableHead>代码 / 源</TableHead>
                  <TableHead className="whitespace-nowrap px-2">状态</TableHead>
                  <TableHead className="whitespace-nowrap px-2 text-xs">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-foreground"
                      onClick={() => setRowsSortDesc((v) => (v === null ? true : v ? false : null))}
                      title="按行数排序"
                    >
                      行数
                      <ArrowUpDown className={`w-3 h-3 ${rowsSortDesc === null ? "opacity-40" : "opacity-100"}`} />
                    </button>
                  </TableHead>
                  <TableHead className="whitespace-nowrap px-2 text-xs">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-foreground"
                      onClick={() => setLagSortDesc((v) => (v === null ? true : v ? false : null))}
                      title="按滞后交易日数排序"
                    >
                      新鲜度
                      <ArrowUpDown className={`w-3 h-3 ${lagSortDesc === null ? "opacity-40" : "opacity-100"}`} />
                    </button>
                  </TableHead>
                  <TableHead className="w-10 px-2 text-center text-xs whitespace-nowrap" title="最近错误">错误</TableHead>
                  <TableHead className="text-right whitespace-nowrap">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredAssets.map((a) => {
                  const key = `${a.symbol}@${a.source}`;
                  const disabled = a.is_selectable === false;
                  return (
                    <TableRow key={key} className={a.is_deleted ? "opacity-50" : ""} data-state={selected.has(key) ? "selected" : undefined}>
                      <TableCell className="px-2">
                        <Checkbox
                          checked={selected.has(key)}
                          onCheckedChange={(v) => toggleOne(key, v === true)}
                          aria-label={`选择 ${a.name || a.symbol}`}
                        />
                      </TableCell>
                      <TableCell className="max-w-[200px]">
                        <div className="truncate font-medium" title={a.name || a.symbol}>{a.name || a.symbol}</div>
                      </TableCell>
                      <TableCell>
                        <div className="font-mono text-xs leading-relaxed">
                          <div>{a.symbol}</div>
                          <div className="text-muted-foreground" title={a.source}>
                            {a.logical_source === "etf" || a.logical_source === "cn_index"
                              ? `${a.logical_source === "etf" ? "ETF聚合" : "指数聚合"}${a.adjust ? ` · ${ADJUST_LABEL[a.adjust] ?? a.adjust}` : ""}`
                              : `${a.source}${a.adjust ? ` · ${ADJUST_LABEL[a.adjust] ?? a.adjust}` : ""}`}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="px-2">
                        {a.is_deleted ? (
                          <Badge variant="outline" className="text-muted-foreground">已删除</Badge>
                        ) : isSuperAdmin ? (
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={!disabled}
                              onCheckedChange={(v) => toggleSelectable(a, v)}
                              disabled={busyKey === key}
                              aria-label="启用/停用"
                            />
                            {disabled && <Badge variant="secondary" className="text-muted-foreground font-normal">停用</Badge>}
                          </div>
                        ) : (
                          <Badge variant="outline" className="font-normal">启用</Badge>
                        )}
                      </TableCell>
                      <TableCell className="px-2 font-mono text-xs tabular-nums">{a.clean_rows || 0}</TableCell>
                      <TableCell className="px-2 text-xs">
                        <div>
                          {/* 滞后 >= 2 个交易日才提示; is_stale(差 1 日)保持安静。字段缺失(旧后端)视为不滞后。 */}
                          {a.is_lagging === true ? (
                            <Badge
                              variant="outline"
                              className="font-normal text-warning bg-warning/10 border-warning/30"
                              title={a.is_stale ? "落后于平台最新清洗日" : undefined}
                            >
                              滞后 {a.lag_trading_days ?? "?"} 个交易日
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </div>
                        <div className="text-muted-foreground">{a.last_clean_date || "-"}</div>
                      </TableCell>
                      <TableCell className="w-10 px-2 text-center" title={a.last_error ?? ""}>
                        {a.last_error ? (
                          <AlertTriangle className="h-4 w-4 text-warning" />
                        ) : (
                          <CheckCircle2 className="h-4 w-4 text-success" />
                        )}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" className="h-7 px-2 gap-1 text-xs" onClick={() => probe(a)} disabled={busyKey === key}>
                            {busyKey === key ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
                            测试
                          </Button>
                          <Button variant="ghost" size="sm" className="h-7 px-2 gap-1 text-xs" onClick={() => sync(a)} disabled={busyKey === key} title="立即拉取该投资品增量数据并入库">
                            {busyKey === key ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                            增量
                          </Button>
                          {isSuperAdmin && (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-7 px-2 gap-1 text-xs text-destructive hover:text-destructive">
                                  <Trash2 className="h-3.5 w-3.5" /> 删除
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>确认软删除 {a.name || a.symbol}？</AlertDialogTitle>
                                  <AlertDialogDescription asChild>
                                    <div className="space-y-2">
                                      <p>
                                        删除后停更、builder 不可选；历史行情数据保留。
                                        此操作可在数据库层面恢复，但界面上不可撤销。
                                      </p>
                                      <p>
                                        <AffectedPortfolios
                                          refs={assetRefs[assetKey(a)] ?? []}
                                          action="delete"
                                        />
                                      </p>
                                    </div>
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>取消</AlertDialogCancel>
                                  <AlertDialogAction
                                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                    onClick={() => void remove(a)}
                                  >
                                    确认删除
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 批量操作条: 固定在视口底部, 不参与表格布局, 因此不会改变滚动容器高度 */}
      {isSuperAdmin && selectedAssets.length > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 rounded-lg border bg-background/95 backdrop-blur px-4 py-2.5 shadow-lg">
          <span className="text-sm whitespace-nowrap">
            已选 <span className="font-mono font-medium">{selectedAssets.length}</span> 项
          </span>
          <Button variant="outline" size="sm" onClick={() => setSelected(new Set())} disabled={batchBusy}>
            清空
          </Button>
          <Button variant="outline" size="sm" onClick={() => setBatchOpen("enable")} disabled={batchBusy}>
            批量启用
          </Button>
          <Button variant="outline" size="sm" onClick={() => setBatchOpen("disable")} disabled={batchBusy}>
            批量停用
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => setBatchOpen("delete")}
            disabled={batchBusy}
          >
            {batchBusy ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Trash2 className="w-4 h-4 mr-1" />}
            批量删除
          </Button>
        </div>
      )}

      {/* 批量确认: 展示影响标的数与具体 key(项目规范: 禁止 window.confirm) */}
      <AlertDialog open={batchOpen !== null} onOpenChange={(v) => { if (!v && !batchBusy) setBatchOpen(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {batchOpen === "delete" ? "确认批量删除？" : batchOpen === "disable" ? "确认批量停用？" : "确认批量启用？"}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  将影响 <span className="font-mono font-medium text-foreground">{selectedAssets.length}</span> 个标的
                  {batchOpen === "delete"
                    ? "：删除为软删除（is_deleted=1），标的立即停更并退出 builder 可选池。"
                    : batchOpen === "disable"
                      ? "：停用后 builder 四象限不可选，但后台仍按 6h 调度更新行情。"
                      : "：启用后重新进入 builder 四象限可选池。"}
                  {batchOpen === "delete" && "此操作可在数据库层面恢复，但界面上不可撤销。"}
                </p>
                <div className="max-h-44 overflow-y-auto rounded-md border bg-muted/30 p-2">
                  <ul className="space-y-0.5 font-mono text-xs">
                    {selectedAssets.map((a) => (
                      <li key={assetKey(a)} className="flex items-center gap-2">
                        <span>{assetKey(a)}</span>
                        <span className="text-muted-foreground">{logicalSourceLabel(a)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                {batchOpen === "delete" && (
                  <p className="text-xs">
                    <AffectedPortfolios refs={selectedPortfolioRefs} action="delete" />
                  </p>
                )}
                {batchOpen === "disable" && (
                  <p className="text-xs">
                    <AffectedPortfolios refs={selectedPortfolioRefs} action="disable" />
                  </p>
                )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={batchBusy}>取消</AlertDialogCancel>
            <AlertDialogAction
              className={batchOpen === "delete" ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : undefined}
              disabled={batchBusy}
              onClick={(e) => {
                // 阻止 Radix 默认的「点击即关闭」: 操作是异步的, 对话框保持打开并显示进度,
                // 由 runBatch* 在完成后自己置 null 关闭(否则 batchBusy 的 spinner 根本来不及显示)。
                e.preventDefault();
                if (batchOpen === "delete") void runBatchDelete();
                else if (batchOpen === "disable") void runBatchSelectable(false);
                else if (batchOpen === "enable") void runBatchSelectable(true);
              }}
            >
              {batchBusy ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
              {batchOpen === "delete" ? "确认删除" : batchOpen === "disable" ? "确认停用" : "确认启用"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <BacktestProgressDialog
        taskId={syncAllTaskId}
        portfolioId={null}
        open={syncAllOpen}
        title="正在拉取增量数据"
        onOpenChange={(v) => setSyncAllOpen(v)}
        onDone={() => { setSyncAllOpen(false); void load(); }}
      />
    </div>
  );
}
