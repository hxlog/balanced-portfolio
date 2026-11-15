"use client";

/**
 * /dashboard 的「篮子组合」区块：展示已保存的 basket，
 * 支持打开（编辑）、复制、删除（与四象限组合的操作入口保持一致）。
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { Copy, ExternalLink, Loader2, Layers, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { basketMethodLabel, type BasketRecord } from "@/lib/basket-types";
import { copyBasket, deleteBasket, listBaskets, basketErrorMessage } from "@/lib/basket-api";

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function summaryOf(record: BasketRecord): string {
  const result = (record.latest_result ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof result.annualized_return === "number") {
    parts.push("年化 " + (result.annualized_return * 100).toFixed(2) + "%");
  }
  if (typeof result.max_drawdown === "number") {
    parts.push("回撤 " + (result.max_drawdown * 100).toFixed(2) + "%");
  }
  if (typeof result.sharpe === "number") {
    parts.push("夏普 " + result.sharpe.toFixed(2));
  }
  return parts.length > 0 ? parts.join(" · ") : "尚未回测";
}

export function DashboardBaskets() {
  const [baskets, setBaskets] = useState<BasketRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listBaskets<BasketRecord>();
      setBaskets(rows);
    } catch (err) {
      setError(basketErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const onCopy = async (record: BasketRecord) => {
    setBusyId(record.basket_id);
    try {
      const created = await copyBasket(record.basket_id);
      toast.success("已复制篮子");
      await load();
      window.open("/builder?mode=basket&basket=" + created.basket_id, "_blank");
    } catch (err) {
      toast.error(basketErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (record: BasketRecord) => {
    if (!window.confirm("确定删除篮子「" + record.name + "」？该操作不可撤销。")) return;
    setBusyId(record.basket_id);
    try {
      await deleteBasket(record.basket_id);
      toast.success("已删除");
      await load();
    } catch (err) {
      toast.error(basketErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card className="mt-6">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Layers className="h-4 w-4" /> 篮子组合
          </CardTitle>
          <CardDescription>
            在「篮子模式」保存的单层配置，可打开编辑、复制或删除（与四象限组合分开管理）。
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/builder?mode=basket">
            新建篮子
            <ExternalLink className="ml-1 h-3.5 w-3.5" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex h-24 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载篮子…
          </div>
        ) : error ? (
          <p className="text-sm text-destructive">
            {error}（登录后可见自己的篮子）
          </p>
        ) : baskets.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            还没有保存的篮子。前往{" "}
            <Link className="text-primary underline" href="/builder?mode=basket">
              篮子模式
            </Link>{" "}
            配置并保存。
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {baskets.map((record) => (
              <div key={record.basket_id} className="rounded-lg border border-border bg-card p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{record.name}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {basketMethodLabel(record.method)} · {record.assets.length} 项资产 · 更新 {formatDate(record.updated_at)}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                    #{record.basket_id}
                  </span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{summaryOf(record)}</p>
                <div className="mt-3 flex items-center gap-2">
                  <Button asChild size="sm" className="h-7 text-xs">
                    <Link href={"/builder?mode=basket&basket=" + record.basket_id}>
                      打开
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => void onCopy(record)}
                    disabled={busyId === record.basket_id}
                  >
                    <Copy className="mr-1 h-3 w-3" /> 复制
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-destructive"
                    onClick={() => void onDelete(record)}
                    disabled={busyId === record.basket_id}
                  >
                    <Trash2 className="mr-1 h-3 w-3" /> 删除
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
