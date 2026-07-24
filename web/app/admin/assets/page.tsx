"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, ArrowUpDown, Download, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, AdminAsset, DataSource, ADJUST_LABEL, ASSET_ADJUST_OPTIONS } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BacktestProgressDialog } from "@/components/BacktestProgressDialog";

/** 资产分类枚举(对应 bp_index_config.category) */
const CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "index", label: "index · 指数" },
  { value: "etf", label: "etf · ETF 基金" },
  { value: "commodity", label: "commodity · 商品期货" },
  { value: "bond", label: "bond · 债券指数" },
];

export default function AdminAssetsPage() {
  const { isSuperAdmin, ready } = useAuth();
  const [assets, setAssets] = useState<AdminAsset[]>([]);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [probeOk, setProbeOk] = useState(false);
  const [probeResult, setProbeResult] = useState<string | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [form, setForm] = useState({
    symbol: "",
    source: "cn_index_em",
    name: "",
    category: "index",
    start_date: "2017-01-01",
    adjust: "hfq",
  });
  // 列表筛选/排序
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [minRows, setMinRows] = useState("");
  const [rowsSortDesc, setRowsSortDesc] = useState<boolean | null>(null);
  // 全量增量拉取(异步任务) + 重算所有就绪组合。
  // ⚠️ 必须在早返回(!ready/!isSuperAdmin)之前调用——否则 F5 刷新时 ready 由 false→true,
  //    hook 数量突变会触发 React Rules of Hooks 违规, 整页报 "This page couldn't load"。
  const [syncAllTaskId, setSyncAllTaskId] = useState<string | null>(null);
  const [syncAllOpen, setSyncAllOpen] = useState(false);
  const [enqueueBusy, setEnqueueBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [a, s] = await Promise.all([api.listAdminAssets(), api.listDataSources()]);
      setAssets(a.assets);
      setSources(s.data_sources);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isSuperAdmin) void load();
  }, [isSuperAdmin]);

  const selectedSource = useMemo(
    () => sources.find((s) => s.code === form.source),
    [sources, form.source],
  );

  const vendors = useMemo(
    () => Array.from(new Set(sources.map((s) => s.vendor).filter(Boolean))) as string[],
    [sources],
  );

  const filteredAssets = useMemo(() => {
    const q = search.trim().toLowerCase();
    const minN = minRows.trim() === "" ? null : Number(minRows);
    let list = assets.filter((a) => {
      if (q && !(`${a.symbol}`.toLowerCase().includes(q) || `${a.name ?? ""}`.toLowerCase().includes(q))) return false;
      if (sourceFilter !== "all" && a.vendor !== sourceFilter) return false;
      if (statusFilter === "enabled" && (a.is_deleted || a.is_selectable === false)) return false;
      if (statusFilter === "disabled" && a.is_selectable !== false) return false;
      if (statusFilter === "deleted" && !a.is_deleted) return false;
      if (minN != null && !Number.isNaN(minN) && (a.clean_rows || 0) < minN) return false;
      return true;
    });
    if (rowsSortDesc !== null) {
      list = [...list].sort((a, b) =>
        rowsSortDesc ? (b.clean_rows || 0) - (a.clean_rows || 0) : (a.clean_rows || 0) - (b.clean_rows || 0),
      );
    }
    return list;
  }, [assets, search, sourceFilter, statusFilter, minRows, rowsSortDesc]);

  if (!ready) return <div className="p-12 text-center text-muted-foreground">加载中...</div>;
  if (!isSuperAdmin) return <div className="p-12 text-center text-destructive">需要管理员权限</div>;

  const updateForm = (patch: Partial<typeof form>) => {
    setForm((f) => ({ ...f, ...patch }));
    setProbeOk(false);
    setProbeResult(null);
    setProbeError(null);
  };

  const probeForm = async () => {
    const key = `${form.symbol}@${form.source}`;
    setBusyKey(key);
    setProbeOk(false);
    setProbeResult(null);
    setProbeError(null);
    try {
      const res = await api.probeAdminAsset(form.source, form.symbol);
      setProbeOk(true);
      setProbeResult(`读取成功：${res.first_date} ~ ${res.last_date}，${res.rows} 行，用时 ${res.elapsed_ms}ms`);
      await load();
    } catch (e) {
      setProbeError(String(e instanceof Error ? e.message : e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  const save = async () => {
    if (!probeOk) {
      window.alert("请先测试读取成功后再保存");
      return;
    }
    await api.saveAdminAsset({
      ...form,
      category: form.category || null,
      start_date: form.start_date || null,
      adjust: form.category === "etf" ? form.adjust : null,
      is_deleted: 0,
    });
    // 保留表单字段(数据源/分类/起始日/代码/名称)以便连续新增相似标的; 仅清探测状态。
    setProbeOk(false);
    setProbeResult(null);
    setProbeError(null);
    await load();
    // 失效 /builder 资产缓存, 让新加标的立即可选(失败不阻断)
    await api.revalidateAssets().catch(() => {});
  };

  const remove = async (a: AdminAsset) => {
    if (!window.confirm(`确认软删除 ${a.name || a.symbol}?`)) return;
    await api.deleteAdminAsset(a.source, a.symbol);
    await load();
    await api.revalidateAssets().catch(() => {});
  };

  const syncAll = async () => {
    try {
      const res = await api.syncAllAssets();
      setSyncAllTaskId(res.task_id);
      setSyncAllOpen(true);
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    }
  };

  const enqueueReady = async () => {
    setEnqueueBusy(true);
    try {
      const res = await api.enqueueReadyPortfolios();
      window.alert(`已排队 ${res.queued} 个组合的 T-1 更新`);
      await load();
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
    } finally {
      setEnqueueBusy(false);
    }
  };

  const probe = async (a: AdminAsset) => {
    const key = `${a.symbol}@${a.source}`;
    setBusyKey(key);
    try {
      const res = await api.probeAdminAsset(a.source, a.symbol);
      window.alert(`读取成功: ${res.first_date} ~ ${res.last_date}, ${res.rows} 行, ${res.elapsed_ms}ms`);
      await load();
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
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
      window.alert(`增量拉取完成: 写入 ${res.rows} 行（${res.detail || res.status}）`);
      await load();
    } catch (e) {
      window.alert(String(e instanceof Error ? e.message : e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  const refreshStatus = async () => {
    setLoading(true);
    try {
      await api.refreshAdminAssetStatus();
      await load();
    } finally {
      setLoading(false);
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
      window.alert(String(e instanceof Error ? e.message : e));
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  const probing = busyKey === `${form.symbol}@${form.source}`;

  return (
    <div className="flex-1 p-6 max-w-7xl mx-auto w-full space-y-6">
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
        <CardContent className="space-y-5">
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
            {/* 数据源 */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">数据源 (source)</label>
              <Select value={form.source} onValueChange={(v) => updateForm({ source: v })}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择数据源" />
                </SelectTrigger>
                <SelectContent className="max-w-[min(32rem,90vw)]">
                  {sources.map((s) => (
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
            <Button onClick={save} disabled={!form.symbol || !form.source || !form.name || !probeOk}>
              <Plus className="w-4 h-4 mr-1" /> 保存
            </Button>
            {(probeResult || probeError) && (
              <div className={`text-sm ${probeError ? "text-destructive" : "text-muted-foreground"}`}>
                {probeError || probeResult}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-base">投资品列表</CardTitle>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={enqueueReady} disabled={enqueueBusy}>
                <RefreshCw className={`w-4 h-4 mr-1 ${enqueueBusy ? "animate-spin" : ""}`} />
                重算所有就绪组合
              </Button>
              <Button variant="outline" size="sm" onClick={syncAll} disabled={loading}>
                <Download className="w-4 h-4 mr-1" />
                拉取增量数据
              </Button>
              <Button variant="outline" size="sm" onClick={refreshStatus} disabled={loading}>
                <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} />
                刷新状态
              </Button>
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
              <SelectTrigger className="w-[150px]"><SelectValue placeholder="数据源" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部数据源</SelectItem>
                {vendors.map((v) => (
                  <SelectItem key={v} value={v}>{v}</SelectItem>
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
        <CardContent className="overflow-x-auto">
          {loading ? (
            <div className="py-12 text-center text-muted-foreground">加载中...</div>
          ) : (
            <Table className="min-w-[1160px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[140px]">名称</TableHead>
                  <TableHead className="whitespace-nowrap">Symbol</TableHead>
                  <TableHead className="whitespace-nowrap">Source</TableHead>
                  <TableHead className="whitespace-nowrap">复权</TableHead>
                  <TableHead className="whitespace-nowrap">状态</TableHead>
                  <TableHead className="whitespace-nowrap">清洗截至</TableHead>
                  <TableHead className="whitespace-nowrap">
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
                  <TableHead className="min-w-[200px]">最近错误</TableHead>
                  <TableHead className="text-right whitespace-nowrap">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredAssets.map((a) => {
                  const key = `${a.symbol}@${a.source}`;
                  const disabled = a.is_selectable === false;
                  return (
                    <TableRow key={key} className={a.is_deleted ? "opacity-50" : ""}>
                      <TableCell className="font-medium">{a.name || a.symbol}</TableCell>
                      <TableCell className="font-mono">{a.symbol}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {a.vendor ? (
                          <Badge variant="secondary" className="mr-1.5 font-normal">{a.vendor}</Badge>
                        ) : null}
                        <span className="font-mono text-xs text-muted-foreground">{a.source}</span>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs">
                        {a.adjust ? (ADJUST_LABEL[a.adjust] ?? a.adjust) : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {a.is_deleted ? (
                          <Badge variant="outline" className="text-muted-foreground">已删除</Badge>
                        ) : (
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={!disabled}
                              onCheckedChange={(v) => toggleSelectable(a, v)}
                              disabled={busyKey === key}
                              aria-label="启用/停用"
                            />
                            {disabled && <Badge variant="secondary" className="text-muted-foreground font-normal">停用</Badge>}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>{a.last_clean_date || "-"}</TableCell>
                      <TableCell className="font-mono">{a.clean_rows || 0}</TableCell>
                      <TableCell className="max-w-[360px] truncate text-destructive text-sm">{a.last_error || "-"}</TableCell>
                      <TableCell className="text-right space-x-2 whitespace-nowrap">
                        <Button variant="outline" size="sm" onClick={() => probe(a)} disabled={busyKey === key}>
                          {busyKey === key ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                          测试
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => sync(a)} disabled={busyKey === key} title="立即拉取该投资品增量数据并入库">
                          {busyKey === key ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                          拉取增量
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => remove(a)} className="text-destructive">
                          <Trash2 className="w-4 h-4" /> 删除
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
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
