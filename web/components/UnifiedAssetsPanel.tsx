"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { getToken } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";

interface AssetRow {
  type: string;
  type_label: string;
  code: string;
  name: string;
  market: string;
  category: string;
  last_date: string | null;
  adjust_available: boolean;
  adjustments: Array<{ value: string; label: string }>;
}

const TYPE_FILTERS = [
  { value: "", label: "全部" },
  { value: "stock", label: "股票" },
  { value: "index", label: "指数" },
  { value: "fund", label: "基金" },
  { value: "etf", label: "ETF" },
];

const ADJUST_OPTIONS = [
  { value: "bfq", label: "不复权" },
  { value: "hfq", label: "后复权" },
];

export function UnifiedAssetsPanel({ className }: { className?: string }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [adjust, setAdjust] = useState("bfq");
  const [rows, setRows] = useState<AssetRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(60);

  const load = useCallback(async (nextLimit: number) => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (type) params.set("type", type);
    params.set("adjust", adjust);
    params.set("limit", String(nextLimit));
    try {
      const token = getToken();
      const response = await fetch("/api/assets/unified?" + params.toString(), {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!response.ok) throw new Error("请求失败");
      const payload = await response.json();
      setRows((payload?.data ?? []) as AssetRow[]);
      setTotal(Number(payload?.meta?.total ?? 0));
    } catch {
      setError("资产池数据获取失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }, [q, type, adjust]);

  useEffect(() => {
    const timer = setTimeout(() => void load(limit), 250);
    return () => clearTimeout(timer);
  }, [load, limit]);

  const summary = useMemo(() => {
    const counts = { stock: 0, index: 0, fund: 0, etf: 0 } as Record<string, number>;
    for (const row of rows) counts[row.type] = (counts[row.type] ?? 0) + 1;
    return counts;
  }, [rows]);

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="搜索代码 / 名称（如 600519、沪深300、红利）"
            aria-label="搜索资产代码或名称"
            className="pl-8"
          />
        </div>
        <select
          value={adjust}
          onChange={(event) => setAdjust(event.target.value)}
          aria-label="复权口径"
          className="h-9 rounded-md border border-border bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {ADJUST_OPTIONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <span className="text-[11px] text-muted-foreground">回测默认使用<span className="mx-1 font-medium text-foreground">后复权（hfq）</span>：保持历史价格连续，避免分红/拆股造成假信号</span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {TYPE_FILTERS.map((item) => (
          <button
            key={item.value || "all"}
            type="button"
            aria-pressed={type === item.value}
            onClick={() => { setType(item.value); setLimit(60); }}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              type === item.value ? "border-foreground bg-foreground text-background" : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            {item.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-muted-foreground">
          共 {total} 项 · 当前页 股票 {summary.stock} / 指数 {summary.index} / 基金 {summary.fund} / ETF {summary.etf}
        </span>
      </div>

      {error ? (
        <p className="mt-4 text-sm text-destructive">{error}</p>
      ) : (
        <div className="mt-3 overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">类型</th>
                <th className="px-3 py-2 text-left font-medium">代码</th>
                <th className="px-3 py-2 text-left font-medium">名称</th>
                <th className="px-3 py-2 text-left font-medium">市场</th>
                <th className="px-3 py-2 text-left font-medium">分类</th>
                <th className="px-3 py-2 text-right font-medium">最新行情</th>
                <th className="px-3 py-2 text-left font-medium">复权口径</th>
                <th className="px-3 py-2 text-left font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, rowIndex) => (
                  <tr key={`sk-${rowIndex}`} className="border-b border-border/50">
                    {Array.from({ length: 8 }).map((__, colIndex) => (
                      <td key={colIndex} className="px-3 py-2.5">
                        <Skeleton className={colIndex === 2 ? "h-4 w-32" : colIndex === 1 ? "h-4 w-14" : "h-4 w-16"} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3">
                    <EmptyState
                      compact
                      icon={Search}
                      title="没有匹配的资产"
                      description="试试调整关键词或类型筛选。"
                    />
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.type + ":" + row.code} className="border-b border-border/50 last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-2 text-xs text-muted-foreground">{row.type_label}</td>
                    <td className="px-3 py-2 font-mono text-xs">{row.code}</td>
                    <td className="px-3 py-2 text-sm">{row.name}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{row.market || "—"}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{row.category || "—"}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">{row.last_date ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {row.adjustments.map((item) => item.label).join(" / ")}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.last_date ? (
                        <span className="text-success">可取数</span>
                      ) : row.type === "stock" ? (
                        <span className="text-warning">待回填</span>
                      ) : (
                        <span className="text-muted-foreground">待接入</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {rows.length < total ? (
        <div className="mt-3 text-center">
          <button
            type="button"
            onClick={() => setLimit((value) => value + 100)}
            className="rounded-md border border-border px-4 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            显示更多（{rows.length}/{total}）
          </button>
        </div>
      ) : null}
    </div>
  );
}
