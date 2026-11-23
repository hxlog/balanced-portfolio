"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getToken } from "@/lib/api";

const DATASET_LABEL: Record<string, string> = {
  a_stock: "A 股个股",
  hk_stock: "港股个股",
  etf: "场内基金（ETF/LOF）",
  fund_nav: "场外基金净值",
};

interface Coverage { covered: number; total: number }
interface OverviewItem {
  dataset: string;
  latest_trading_date: string | null;
  last_success_date: string | null;
  ready: boolean;
  backlog: number;
  coverage: Coverage | null;
  last_run: {
    run_id: number;
    trade_date: string | null;
    wave: number;
    status: string;
    achieved_coverage: number | null;
    finished_at: string | null;
  } | null;
}
interface OverviewPayload { datasets: OverviewItem[]; latest_trading_date: string | null; generated_at: string }
interface RunRow {
  run_id: number; dataset: string; trade_date: string | null; wave: number; status: string;
  achieved_coverage: number | null; rows_written: number; started_at: string | null; finished_at: string | null;
}
interface SourceRow {
  stat_date: string; dataset: string; source: string; channel: string; attempts: number;
  ok: number; failed: number; banned_count: number; avg_latency_ms: number | null; coverage_today: number | null;
}
interface IssueRow {
  issue_id: number; dataset: string; symbol: string | null; trade_date: string | null;
  kind: string; severity: string; created_at: string | null;
}

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init?.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) } });
  if (!response.ok) throw new Error(`请求失败 HTTP ${response.status}`);
  return (await response.json()) as T;
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

export function DataHealthPanel({ className }: { className?: string }) {
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [issues, setIssues] = useState<IssueRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [overviewRes, runsRes, sourcesRes, issuesRes] = await Promise.all([
        adminFetch<{ data: OverviewPayload }>("/api/admin/data-health/overview"),
        adminFetch<{ data: RunRow[] }>("/api/admin/data-health/runs?limit=10"),
        adminFetch<{ data: SourceRow[] }>("/api/admin/data-health/sources?days=7"),
        adminFetch<{ data: IssueRow[] }>("/api/admin/data-health/issues?limit=20"),
      ]);
      setOverview(overviewRes.data);
      setRuns(runsRes.data);
      setSources(sourcesRes.data);
      setIssues(issuesRes.data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const readyCount = useMemo(
    () => (overview?.datasets ?? []).filter((item) => item.ready).length,
    [overview],
  );

  const replay = useCallback(async (dataset: string) => {
    setBusy(dataset);
    try {
      await adminFetch("/api/admin/data-health/replay", {
        method: "POST",
        body: JSON.stringify({ dataset }),
      });
      setTimeout(() => void load(), 4000);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "重放失败");
    } finally {
      setBusy(null);
    }
  }, [load]);

  if (loading && !overview) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> 加载数据健康状态…
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Badge variant={readyCount === (overview?.datasets.length ?? 0) ? "default" : "destructive"}>
          {readyCount}/{overview?.datasets.length ?? 0} 数据集已追平
        </Badge>
        <span className="text-xs text-muted-foreground">
          最新交易日：{overview?.latest_trading_date ?? "—"} · 生成时间：{overview?.generated_at ?? "—"}
        </span>
        <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <RefreshCw className="mr-1 size-3.5" />}
          刷新
        </Button>
        {error ? <span className="text-xs text-destructive">{error}</span> : null}
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {(overview?.datasets ?? []).map((item) => (
          <Card key={item.dataset} className={item.ready ? "" : "border-destructive/40"}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-base">
                {DATASET_LABEL[item.dataset] ?? item.dataset}
                {item.ready ? (
                  <CheckCircle2 className="size-4 text-success" />
                ) : (
                  <AlertTriangle className="size-4 text-destructive" />
                )}
              </CardTitle>
              <CardDescription>
                最新可用交易日：{item.last_success_date ?? "—"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-xs">
              <div>
                当日覆盖：
                <span className="font-medium">
                  {item.coverage ? `${item.coverage.covered}/${item.coverage.total}` : "—"}
                </span>
                {item.coverage && item.coverage.total > 0
                  ? `（${((item.coverage.covered / item.coverage.total) * 100).toFixed(2)}%）`
                  : ""}
              </div>
              <div>待追赶条目：{item.backlog}</div>
              <div>
                最近波次：{item.last_run ? `#${item.last_run.run_id} ${item.last_run.status}（${pct(item.last_run.achieved_coverage)}）` : "—"}
              </div>
              <div className="pt-1">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy === item.dataset}
                  onClick={() => void replay(item.dataset)}
                >
                  {busy === item.dataset ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : null}
                  重放一波次
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="mt-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">最近运行</CardTitle>
          <CardDescription>最新 10 个波次（catching_up 表示继续无限追赶，不是失败终止）</CardDescription>
        </CardHeader>
        <CardContent className="max-h-64 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="text-left">
                <th className="py-1 pr-3">run</th>
                <th className="py-1 pr-3">dataset</th>
                <th className="py-1 pr-3">trade_date</th>
                <th className="py-1 pr-3">波次</th>
                <th className="py-1 pr-3">状态</th>
                <th className="py-1 pr-3">覆盖</th>
                <th className="py-1">行数</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className="border-t border-border/50">
                  <td className="py-1 pr-3 font-mono">{run.run_id}</td>
                  <td className="py-1 pr-3">{run.dataset}</td>
                  <td className="py-1 pr-3">{run.trade_date ?? "—"}</td>
                  <td className="py-1 pr-3">{run.wave}</td>
                  <td className="py-1 pr-3">{run.status}</td>
                  <td className="py-1 pr-3">{pct(run.achieved_coverage)}</td>
                  <td className="py-1">{run.rows_written}</td>
                </tr>
              ))}
              {runs.length === 0 ? (
                <tr><td colSpan={7} className="py-2 text-muted-foreground">暂无运行记录</td></tr>
              ) : null}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">源可用性（近 7 天）</CardTitle>
            <CardDescription>按 dataset × source × channel 聚合；封禁/失败会触发熔断与降级</CardDescription>
          </CardHeader>
          <CardContent className="max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="text-left">
                  <th className="py-1 pr-2">dataset</th>
                  <th className="py-1 pr-2">source</th>
                  <th className="py-1 pr-2">通道</th>
                  <th className="py-1 pr-2">ok/failed</th>
                  <th className="py-1 pr-2">封禁</th>
                  <th className="py-1">覆盖</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((row, index) => (
                  <tr key={`${row.stat_date}-${row.dataset}-${row.source}-${row.channel}-${index}`} className="border-t border-border/50">
                    <td className="py-1 pr-2">{row.dataset}</td>
                    <td className="py-1 pr-2">{row.source}</td>
                    <td className="py-1 pr-2">{row.channel}</td>
                    <td className="py-1 pr-2">{row.ok}/{row.failed}</td>
                    <td className="py-1 pr-2">{row.banned_count}</td>
                    <td className="py-1">{pct(row.coverage_today)}</td>
                  </tr>
                ))}
                {sources.length === 0 ? (
                  <tr><td colSpan={6} className="py-2 text-muted-foreground">暂无源健康数据</td></tr>
                ) : null}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">待处理质量问题</CardTitle>
            <CardDescription>OHLC 非法 / 覆盖率不足 / 交叉源偏差 / 比率漂移</CardDescription>
          </CardHeader>
          <CardContent className="max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="text-left">
                  <th className="py-1 pr-2">dataset</th>
                  <th className="py-1 pr-2">标的</th>
                  <th className="py-1 pr-2">kind</th>
                  <th className="py-1">级别</th>
                </tr>
              </thead>
              <tbody>
                {issues.map((issue) => (
                  <tr key={issue.issue_id} className="border-t border-border/50">
                    <td className="py-1 pr-2">{issue.dataset}</td>
                    <td className="py-1 pr-2">{issue.symbol ?? "—"}</td>
                    <td className="py-1 pr-2">{issue.kind}</td>
                    <td className={issue.severity === "error" ? "py-1 text-destructive" : "py-1"}>
                      {issue.severity === "error" ? <XCircle className="size-3.5" /> : issue.severity}
                    </td>
                  </tr>
                ))}
                {issues.length === 0 ? (
                  <tr><td colSpan={4} className="py-2 text-muted-foreground">暂无未解决质量问题</td></tr>
                ) : null}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
