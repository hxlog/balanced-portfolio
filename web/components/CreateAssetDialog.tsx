"use client";

/**
 * 「新增投资品」对话框 —— 从 /builder 的资产搜索无结果处直接开。
 *
 * 功能与 /admin/assets 的「新增 / 更新投资品」表单**完全一致**(同一份
 * @/lib/asset-form 口径、同一个 POST /api/admin/assets 端点、同一道 probe 门禁),
 * 只是在对话框里呈现, 免得用户为了加一个标的中断组合构建跑到管理端。
 *
 * 两条放行路径:
 *   1) 测试读取成功 → 保存(落库即用, 已有数据时不会重复拉取);
 *   2) 测试读取失败但结论是 unreachable(接口可达, 本次被反爬/限频/超时挡住)
 *      → 「仍要保存并后台补拉」。后端保存后自动排 `asset_ingest` 补拉历史,
 *      故不会因为「暂时取不到全量日行情」把用户永久卡在对话框里。
 * 结论是 invalid(未知数据源/代码不存在)时不给第二条路径 —— 那是真写错了。
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Activity, Loader2, Plus, RefreshCw } from "lucide-react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { api, Asset, DataSource, ASSET_ADJUST_OPTIONS, ASSET_CATEGORY_OPTIONS } from "@/lib/api";
import {
  ASSET_CREATE_DEFAULTS, buildExtraParams, parseProbeFailure, validateAssetInput,
  type AssetFormState, type ProbeFailure,
} from "@/lib/asset-form";

const CATEGORY_OPTIONS = ASSET_CATEGORY_OPTIONS.map((c) => ({ value: c.value, label: c.label }));

export function CreateAssetDialog({
  open,
  onOpenChange,
  defaultQuery,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** 预填搜索词(通常是用户刚在 builder 里搜不到的那个代码)。 */
  defaultQuery?: string;
  /** 保存成功回调: 传入新建的资产(供 builder 立刻加入列表并勾选)。 */
  onCreated: (asset: Asset) => void;
}) {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [form, setForm] = useState<AssetFormState>({ ...ASSET_CREATE_DEFAULTS });
  const [probing, setProbing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [probeOk, setProbeOk] = useState(false);
  const [probeResult, setProbeResult] = useState<string | null>(null);
  const [probeFailure, setProbeFailure] = useState<ProbeFailure | null>(null);

  // 每个标的只需拉一次数据源清单(数据源是静态引用表); 失败静默, 用户仍可手填。
  useEffect(() => {
    if (!open || sources.length > 0) return;
    let cancelled = false;
    api.listDataSources()
      .then((r) => { if (!cancelled) setSources(r.data_sources); })
      .catch(() => { /* 下拉为空时仍可用默认 source */ });
    return () => { cancelled = true; };
  }, [open, sources.length]);

  // 打开时重置: 用搜索词预填 symbol(用户往往输的就是代码), 其余回默认值。
  useEffect(() => {
    if (!open) return;
    setForm({ ...ASSET_CREATE_DEFAULTS, symbol: (defaultQuery ?? "").trim() });
    setProbeOk(false);
    setProbeResult(null);
    setProbeFailure(null);
  }, [open, defaultQuery]);

  const selectedSource = sources.find((s) => s.code === form.source);
  const addableSources = sources.filter((s) => s.is_addable !== false);
  const extraParams = buildExtraParams(form.source, form.category, form.adjust);

  const update = (patch: Partial<AssetFormState>) => {
    setForm((f) => ({ ...f, ...patch }));
    setProbeOk(false);
    setProbeResult(null);
    setProbeFailure(null);
  };

  const probe = async () => {
    const invalid = validateAssetInput(form);
    if (invalid) { toast.error(invalid); return; }
    setProbing(true);
    setProbeOk(false);
    setProbeResult(null);
    setProbeFailure(null);
    try {
      const res = await api.probeAdminAsset(form.source, form.symbol.trim(), extraParams);
      setProbeOk(true);
      setProbeResult(`读取成功：${res.first_date} ~ ${res.last_date}，${res.rows} 行，用时 ${res.elapsed_ms}ms`);
    } catch (e) {
      setProbeFailure(parseProbeFailure(e));
    } finally {
      setProbing(false);
    }
  };

  const save = async (allowUnreachable: boolean) => {
    const invalid = validateAssetInput(form);
    if (invalid) { toast.error(invalid); return; }
    if (!probeOk && !allowUnreachable) { toast.error("请先点「测试读取」"); return; }
    setSaving(true);
    try {
      const res = await api.saveAdminAsset({
        symbol: form.symbol.trim(),
        source: form.source,
        name: form.name.trim(),
        category: form.category || null,
        start_date: form.start_date || null,
        adjust: extraParams.adjust ?? null,
        is_deleted: 0,
      });
      // 失效 /builder 的 SSR 资产缓存。许可与「新增资产」同口径(超管 或 有资产编辑权),
      // 见 web/app/api/revalidate/route.ts —— 否则普通资产编辑者刚加的标的自己搜不到。
      // 同一次会话里我们还会用返回值构造 Asset 塞进本地列表, 故即便这里失败也不阻断。
      void api.revalidateAssets().catch(() => {});
      onCreated({
        symbol: form.symbol.trim(),
        source: form.source,
        name: form.name.trim(),
        category: form.category || undefined,
        adjust: extraParams.adjust ?? undefined,
        last_clean_date: null,   // 刚落库, 清洗表还没有数据 → builder 显示「待拉取」
        currency: "CNY",
      });
      if (res.ingest_queued) {
        toast.success("已保存, 正在后台拉取历史行情");
      } else {
        toast.success("已保存");
      }
      onOpenChange(false);
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setSaving(false);
    }
  };

  const canSaveOnly = !probeOk && !!probeFailure?.canSaveAnyway;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100vw-2rem)] sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>新增投资品</DialogTitle>
          <DialogDescription>
            库中找不到该标的时在这里直接新增。先选数据源 → 按提示填写代码 → 点「测试读取」确认 →
            保存。保存后系统会自动拉取并清洗历史行情, 随后即可在本页勾选。
          </DialogDescription>
        </DialogHeader>

        <div className="grid sm:grid-cols-2 gap-x-4 gap-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">数据源 (source)</label>
            <Select value={form.source} onValueChange={(v) => update({ source: v })}>
              <SelectTrigger className="w-full"><SelectValue placeholder="选择数据源" /></SelectTrigger>
              <SelectContent className="max-w-[min(32rem,90vw)]">
                {addableSources.map((s) => (
                  <SelectItem key={s.code} value={s.code}>
                    {s.vendor ? `${s.vendor} · ` : ""}{s.code} · {s.asset_class}
                  </SelectItem>
                ))}
                {/* 数据源清单尚未拉到(或接口失败)时, 至少保留当前默认项可选 */}
                {addableSources.length === 0 && (
                  <SelectItem value={form.source}>{form.source}</SelectItem>
                )}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {selectedSource?.description || "akshare 行情源；不同源 symbol 书写格式不同。"}
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">代码 (symbol)</label>
            <Input
              placeholder={selectedSource?.symbol_hint || "该数据源要求的原生 symbol"}
              value={form.symbol}
              onChange={(e) => update({ symbol: e.target.value })}
            />
            <p className="text-xs text-muted-foreground leading-relaxed">
              {selectedSource?.symbol_hint ? `书写格式：${selectedSource.symbol_hint}` : "按所选数据源接口要求填写。"}
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">名称 (name)</label>
            <Input
              placeholder="中文展示名，如 沪深300"
              value={form.name}
              onChange={(e) => update({ name: e.target.value })}
            />
            <p className="text-xs text-muted-foreground leading-relaxed">展示于组合构建器与持仓表的中文名。</p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">分类 (category)</label>
            <Select value={form.category} onValueChange={(v) => update({ category: v })}>
              <SelectTrigger className="w-full"><SelectValue placeholder="选择分类" /></SelectTrigger>
              <SelectContent>
                {CATEGORY_OPTIONS.map((c) => (
                  <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground leading-relaxed">资产大类，仅用于分组展示。</p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">复权 (adjust)</label>
            <Select value={form.adjust} onValueChange={(v) => update({ adjust: v })} disabled={form.category !== "etf"}>
              <SelectTrigger className="w-full"><SelectValue placeholder="选择复权类型" /></SelectTrigger>
              <SelectContent>
                {ASSET_ADJUST_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {form.category === "etf" ? "ETF 复权类型; 后复权(hfq) 为默认, 价格连续可比。" : "仅 ETF 类目支持复权。"}
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">起始日 (start_date)</label>
            <Input type="date" value={form.start_date} onChange={(e) => update({ start_date: e.target.value })} />
            <p className="text-xs text-muted-foreground leading-relaxed">首拉起始日；留空则从 2017-01-01 拉取。</p>
          </div>
        </div>

        {(probeResult || probeFailure) && (
          <div className={`text-sm rounded-md border p-3 ${
            probeFailure ? "border-destructive/40 bg-destructive/5 text-destructive" : "border-border bg-muted/40 text-muted-foreground"
          }`}>
            {probeFailure?.message || probeResult}
            {canSaveOnly && (
              <p className="mt-1.5 text-xs text-muted-foreground">
                该数据源本次未返回数据，通常是反爬/限频/IP 封锁，而不是代码写错。
                可以先保存，系统会在后台重试拉取；数据到位前该标的在构建器里可选，但回测暂不含其行情。
              </p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="outline" onClick={probe} disabled={probing || saving || !form.symbol || !form.source}>
            {probing ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Activity className="w-4 h-4 mr-1" />}
            测试读取
          </Button>
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:items-center">
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>取消</Button>
            {canSaveOnly && (
              <Button variant="secondary" onClick={() => save(true)} disabled={saving || !form.name.trim()}>
                仍要保存并后台补拉
              </Button>
            )}
            <Button onClick={() => save(false)} disabled={saving || !probeOk || !form.name.trim()}>
              {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Plus className="w-4 h-4 mr-1" />}
              保存
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
