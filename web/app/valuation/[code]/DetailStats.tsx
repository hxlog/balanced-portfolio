"use client";

/**
 * 详情页「描述统计」与「基金对比」模块（v3）。
 *
 * - 描述统计：日收益率分布 + 年化波动率 / Beta / Pearson / Spearman，基准可切换（默认沪深300）。
 * - 基金对比：勾选最多 5 只基金、自定义区间（默认年初至今），对比收益/波动/回撤/跟踪误差/信息比率。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { EChart } from "@/components/EChart";
import { cn } from "@/lib/utils";
import type { DetailTrackerFund } from "@/lib/valuation-detail-types";

const BENCHMARK_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "000300", label: "沪深300" },
  { value: "000905", label: "中证500" },
  { value: "000016", label: "上证50" },
  { value: "000852", label: "中证1000" },
  { value: "000510", label: "中证A500" },
];

interface BenchmarkStats {
  as_of: string;
  benchmark_code: string;
  benchmark_name: string;
  n_obs: number;
  ann_vol: number;
  beta: number | null;
  pearson: number | null;
  spearman: number | null;
  mean_daily_pct: number | null;
  std_daily_pct: number | null;
  skew: number | null;
  kurtosis: number | null;
  histogram: Array<{ bin: number; count: number }>;
}

function fmt(value: number | null | undefined, digits = 2, suffix = "") {
  return value == null ? "—" : value.toFixed(digits) + suffix;
}

export function DetailStats({ indexCode }: { indexCode: string }) {
  const [benchmark, setBenchmark] = useState("000300");
  const [stats, setStats] = useState<BenchmarkStats | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (bench: string) => {
    setLoading(true);
    try {
      const response = await fetch("/api/valuation/" + indexCode + "/benchmark-stats?benchmark=" + bench);
      if (response.ok) {
        const payload = await response.json();
        setStats((payload?.data ?? null) as BenchmarkStats | null);
      }
    } catch {
      // 保留上一次数据
    } finally {
      setLoading(false);
    }
  }, [indexCode]);

  useEffect(() => {
    void load(benchmark);
  }, [benchmark, load]);

  const option = useMemo(() => {
    const bins = stats?.histogram ?? [];
    return {
      animation: false,
      grid: { left: 8, right: 10, top: 18, bottom: 22, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: bins.map((item) => item.bin.toFixed(1)),
        axisLabel: { fontSize: 9, color: "#94a3b8" },
        axisLine: { lineStyle: { color: "#e2e8f0" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "#f1f5f9" } },
        axisLabel: { fontSize: 9, color: "#94a3b8" },
      },
      series: [
        {
          type: "bar",
          data: bins.map((item) => item.count),
          barWidth: "82%",
          itemStyle: { color: "#6366f1", borderRadius: [2, 2, 0, 0] },
        },
      ],
    };
  }, [stats]);

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">描述统计 · 日收益率分布</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            基准可切换 · 近 1 年日收益 · 样本 {stats?.n_obs ?? "—"} 日
            {loading ? " · 加载中…" : ""}
          </p>
        </div>
        <select
          value={benchmark}
          onChange={(event) => setBenchmark(event.target.value)}
          className="h-8 rounded-md border border-border bg-background px-2 text-xs"
        >
          {BENCHMARK_OPTIONS.map((item) => (
            <option key={item.value} value={item.value}>
              vs {item.label}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { label: "年化波动率", value: fmt(stats?.ann_vol, 2, "%") },
          { label: "Beta", value: fmt(stats?.beta, 3) },
          { label: "Pearson 相关", value: fmt(stats?.pearson, 3) },
          { label: "Spearman 相关", value: fmt(stats?.spearman, 3) },
        ].map((item) => (
          <div key={item.label} className="rounded-lg border border-border bg-muted/30 p-2.5">
            <div className="text-[11px] text-muted-foreground">{item.label}</div>
            <div className="mt-0.5 font-mono text-sm font-medium tabular-nums">{item.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-3">
        {stats && stats.histogram.length > 0 ? (
          <EChart option={option} style={{ height: 150, width: "100%" }} />
        ) : (
          <div className="flex h-[120px] items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
            暂无足够行情数据
          </div>
        )}
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground/80">
        偏度 {fmt(stats?.skew, 2)} · 峰度 {fmt(stats?.kurtosis, 2)} · 日均 {fmt(stats?.mean_daily_pct, 3, "%")} · 日波动{" "}
        {fmt(stats?.std_daily_pct, 3, "%")}（未扣无风险利率）
      </p>
    </section>
  );
}

interface CompareItem {
  fund_code: string;
  name: string | null;
  total_return_pct: number;
  ann_return_pct: number | null;
  ann_vol_pct: number;
  max_dd_pct: number;
  tracking_error_pct: number | null;
  info_ratio: number | null;
  excess_return_pct: number | null;
  n_obs: number;
}

export function CompareFundsDialog({
  funds,
  benchmark,
}: {
  funds: DetailTrackerFund[];
  benchmark: string;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rows, setRows] = useState<CompareItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (code: string) => {
    setSelected((current) => {
      if (current.includes(code)) return current.filter((item) => item !== code);
      if (current.length >= 5) return current;
      return [...current, code];
    });
  };

  const compare = async () => {
    if (selected.length < 2) {
      setError("请至少选择 2 只基金");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ codes: selected.join(","), benchmark });
      if (start) params.set("start", start);
      if (end) params.set("end", end);
      const response = await fetch("/api/valuation/funds/compare?" + params.toString());
      if (!response.ok) throw new Error("请求失败");
      const payload = await response.json();
      setRows((payload?.items ?? []) as CompareItem[]);
    } catch {
      setError("对比数据获取失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 text-xs">
          基金对比
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>基金对比</DialogTitle>
          <DialogDescription>
            最多选择 5 只基金；默认区间为年初至今，可自定义起止日期；基准 {benchmark}。
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-44 space-y-1 overflow-auto rounded-lg border border-border p-2">
          {funds.map((fund) => (
            <label key={fund.fund_code} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-muted">
              <input
                type="checkbox"
                checked={selected.includes(fund.fund_code)}
                onChange={() => toggle(fund.fund_code)}
                className="size-3.5"
              />
              <span className="font-mono text-muted-foreground">{fund.fund_code}</span>
              <span className="truncate">{fund.name}</span>
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[11px] text-muted-foreground">
            开始
            <Input type="date" value={start} onChange={(event) => setStart(event.target.value)} className="mt-1 h-8 w-36 text-xs" />
          </label>
          <label className="text-[11px] text-muted-foreground">
            结束
            <Input type="date" value={end} onChange={(event) => setEnd(event.target.value)} className="mt-1 h-8 w-36 text-xs" />
          </label>
          <Button size="sm" className="h-8 text-xs" onClick={compare} disabled={loading}>
            {loading ? "计算中…" : "开始对比"}
          </Button>
          <span className="text-[11px] text-muted-foreground">已选 {selected.length}/5</span>
        </div>
        {error ? <p className="text-xs text-down">{error}</p> : null}
        {rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">基金</th>
                  <th className="py-1.5 text-right font-medium">区间收益</th>
                  <th className="py-1.5 text-right font-medium">年化收益</th>
                  <th className="py-1.5 text-right font-medium">年化波动</th>
                  <th className="py-1.5 text-right font-medium">最大回撤</th>
                  <th className="py-1.5 text-right font-medium">跟踪误差</th>
                  <th className="py-1.5 text-right font-medium">信息比率</th>
                  <th className="py-1.5 text-right font-medium">超额收益</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.fund_code} className="border-b border-border/50 last:border-0">
                    <td className="py-1.5">
                      <span className="font-mono text-muted-foreground">{row.fund_code}</span> {row.name}
                    </td>
                    {[
                      { value: row.total_return_pct, digits: 2 },
                      { value: row.ann_return_pct, digits: 2 },
                      { value: row.ann_vol_pct, digits: 2 },
                      { value: row.max_dd_pct, digits: 2 },
                      { value: row.tracking_error_pct, digits: 2 },
                      { value: row.info_ratio, digits: 2 },
                      { value: row.excess_return_pct, digits: 2 },
                    ].map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className={cn(
                          "py-1.5 text-right font-mono tabular-nums",
                          cellIndex === 0 || cellIndex === 1
                            ? (cell.value ?? 0) >= 0
                              ? "text-up"
                              : "text-down"
                            : "",
                        )}
                      >
                        {cell.value == null ? "—" : cell.value.toFixed(cell.digits) + "%"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[10px] text-muted-foreground">
              区间：{start || "年初"} ~ {end || "今天"}；跟踪误差/信息比率基于与基准 {benchmark} 的日收益差计算。
            </p>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
