"use client";

/**
 * /dashboard 的「一篮子资产」区块（需求 P2-2）：
 * - 列表分「示例 / 我的」两区；示例带「示例 · 只读 · 可复制」徽标；
 * - 匿名可查看示例；复制/保存提示登录；仅 admin 可编辑示例（并可服务端重算 latest_result）；
 * - 局部 loading（卡片 skeleton），不再整块转圈；错误态可重试；空态给下一步入口。
 *
 * 数据来源：GET /api/baskets（ddl 78 契约：匿名 = 示例；登录 = 示例 + 自己；admin = 全部）。
 * 旧后端缺 is_demo 时按「我的」处理（兼容降级）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Copy, Layers, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useAuth } from "@/lib/auth";
import {
  basketErrorMessage,
  copyBasket,
  deleteBasket,
  listBaskets,
  recomputeBasket,
} from "@/lib/basket-api";
import {
  DEMO_BASKET_SECTION_HINT,
  basketAccess,
  basketCopyGuard,
  basketOpenLabel,
  basketSummaryText,
  basketUpdatedDate,
  basketViewerFromAuth,
  isDemoBasket,
  splitBasketBoard,
  type BasketAccess,
  type BasketViewer,
} from "@/lib/basket-demo";
import { basketMethodLabel, type BasketRecord } from "@/lib/basket-types";
import { SkeletonBlock } from "./DashboardSkeleton";

const REQUEST_TIMEOUT_MS = 12_000;

function withTimeout<T>(promise: Promise<T>): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("请求超时，请重试")), REQUEST_TIMEOUT_MS),
    ),
  ]);
}

function DemoBadge() {
  return (
    <Badge
      variant="outline"
      className="shrink-0 border-primary/40 bg-primary/5 px-1.5 text-[10px] font-normal text-primary"
    >
      示例 · 只读 · 可复制
    </Badge>
  );
}

function BasketCard({
  record,
  access,
  busyId,
  onCopy,
  onDelete,
  onRecompute,
}: {
  record: BasketRecord;
  access: BasketAccess;
  busyId: number | null;
  onCopy: (record: BasketRecord) => void;
  onDelete: (record: BasketRecord) => void;
  onRecompute: (record: BasketRecord) => void;
}) {
  const summary = basketSummaryText(record.latest_result);
  const isDemo = isDemoBasket(record);
  const busy = busyId === record.basket_id;
  return (
    <div className="flex flex-col rounded-lg border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <p className="truncate text-sm font-medium">{record.name}</p>
            {isDemo ? <DemoBadge /> : null}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {basketMethodLabel(record.method)} · {record.assets.length} 项资产 ·
            更新 {basketUpdatedDate(record)}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
          #{record.basket_id}
        </span>
      </div>
      <p className="mt-2 min-h-4 text-xs text-muted-foreground">
        {summary || "尚未回测"}
      </p>
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
        <Button asChild size="sm" className="h-7 text-xs">
          <Link
            href={"/builder?mode=basket&basket=" + record.basket_id}
            prefetch={!access.readOnly}
          >
            {basketOpenLabel(access)}
          </Link>
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          onClick={() => onCopy(record)}
          disabled={busy}
          title={access.canCopy ? "复制为自己的篮子" : "登录后可复制示例篮子"}
        >
          <Copy className="mr-1 h-3 w-3" /> 复制
        </Button>
        {access.isDemo && access.canEdit ? (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onRecompute(record)}
            disabled={busy}
            title="服务端按当前参数重算示例篮子的最新结果"
          >
            {busy ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3 w-3" />
            )}
            重算
          </Button>
        ) : null}
        {access.canDelete ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs text-destructive hover:text-destructive"
            onClick={() => onDelete(record)}
            disabled={busy}
          >
            <Trash2 className="mr-1 h-3 w-3" /> 删除
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function SectionSkeleton({ title }: { title: string }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <SkeletonBlock className="h-5 w-10 rounded-full" />
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="space-y-2 rounded-lg border border-border bg-card p-3">
            <SkeletonBlock className="h-4 w-32" />
            <SkeletonBlock className="h-3 w-44" />
            <SkeletonBlock className="h-8 w-full" />
            <div className="flex gap-2 pt-1">
              <SkeletonBlock className="h-7 w-14" />
              <SkeletonBlock className="h-7 w-14" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function DashboardBaskets() {
  const router = useRouter();
  const { userId, isSuperAdmin, ready } = useAuth();
  const viewer: BasketViewer = useMemo(
    () => basketViewerFromAuth({ userId, isSuperAdmin }),
    [userId, isSuperAdmin],
  );

  const [records, setRecords] = useState<BasketRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BasketRecord | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await withTimeout(listBaskets<BasketRecord>());
      setRecords(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setError(basketErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // 等 auth 恢复完成再拉列表：匿名/登录可见范围不同，避免先按游客拉一次、登录后列表缺「我的」。
  // userId 变化（登录/登出/切换账号）时重新拉取。
  const loadedForUserRef = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (!ready) return;
    if (loadedForUserRef.current === userId) return;
    loadedForUserRef.current = userId;
    void load();
  }, [ready, userId, load]);

  const board = useMemo(
    () => splitBasketBoard(records, viewer),
    [records, viewer],
  );

  const requireLogin = useCallback((action: string) => {
    toast.error("请先登录后" + action, {
      description: "登录后可复制示例为自己的篮子，并保存编辑。",
    });
  }, []);

  const onCopy = useCallback(
    async (record: BasketRecord) => {
      const guard = basketCopyGuard(viewer);
      if (!guard.allowed) {
        requireLogin("复制示例篮子");
        return;
      }
      setBusyId(record.basket_id);
      try {
        const created = await copyBasket(record.basket_id);
        toast.success("已复制为自己的篮子", {
          description: "可以在构建器里修改并保存。",
        });
        router.push("/builder?mode=basket&basket=" + created.basket_id);
      } catch (err) {
        toast.error(basketErrorMessage(err));
      } finally {
        setBusyId(null);
      }
    },
    [requireLogin, router, viewer],
  );

  const onDelete = useCallback(
    async (record: BasketRecord) => {
      if (!basketAccess(record, viewer).canDelete) return;
      setBusyId(record.basket_id);
      setDeleting(true);
      try {
        await deleteBasket(record.basket_id);
        toast.success("已删除");
        setDeleteTarget(null);
        await load();
      } catch (err) {
        toast.error(basketErrorMessage(err));
      } finally {
        setDeleting(false);
        setBusyId(null);
      }
    },
    [load, viewer],
  );

  const onRecompute = useCallback(
    async (record: BasketRecord) => {
      setBusyId(record.basket_id);
      try {
        await recomputeBasket(record.basket_id);
        toast.success("已重算示例篮子", {
          description: "列表里的指标已更新为服务端最新结果。",
        });
        await load();
      } catch (err) {
        toast.error(basketErrorMessage(err));
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const loginHint = !viewer.userId ? (
    <p className="text-xs text-muted-foreground">
      当前为游客视图：示例篮子可查看；<span className="text-foreground">复制 / 保存需先登录</span>（右上角登录）。
    </p>
  ) : null;

  if (loading) {
    return (
      <div className="space-y-6">
        <SectionSkeleton title="示例" />
        <SectionSkeleton title="我的篮子" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <span className="min-w-0 break-words">
          加载篮子失败：{error}
        </span>
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void load()}>
          重试
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-muted-foreground" />
          <h1 className="text-base font-semibold">一篮子资产</h1>
          <Badge variant="secondary" className="font-normal">
            {board.demos.length + board.mine.length} 个
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          单层配置 · 风险平价 / 最大夏普等方法 · 与四象限组合分开管理
        </p>
      </div>
      {loginHint ? <div className="mb-4">{loginHint}</div> : null}

      <div className="space-y-8">
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-semibold">示例</h2>
              <span className="text-xs text-muted-foreground">
                {board.demos.length} 个 · {DEMO_BASKET_SECTION_HINT}
              </span>
            </div>
            {board.demos.length === 0 ? (
              <span className="text-xs text-muted-foreground">
                示例尚未发布（后端 seed 后匿名可见）
              </span>
            ) : null}
          </div>
          {board.demos.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-bg-subtle/40 px-4 py-8 text-center text-sm text-muted-foreground">
              暂无示例篮子。管理员可运行示例 seed（A 股核心资产 12 只）后在此查看。
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {board.demos.map((record) => (
                <BasketCard
                  key={record.basket_id}
                  record={record}
                  access={basketAccess(record, viewer)}
                  busyId={busyId}
                  onCopy={onCopy}
                  onDelete={setDeleteTarget}
                  onRecompute={onRecompute}
                />
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-semibold">
                {viewer.isSuperAdmin ? "全部篮子" : "我的篮子"}
              </h2>
              <span className="text-xs text-muted-foreground">
                {viewer.userId ? board.mine.length + " 个" : "登录后显示"}
              </span>
            </div>
          </div>
          {!viewer.userId ? (
            <div className="rounded-lg border border-dashed border-border bg-bg-subtle/40 px-4 py-8 text-center text-sm text-muted-foreground">
              登录后在这里管理自己保存的篮子；也可以用「新建篮子」从示例复制一份。
            </div>
          ) : board.mine.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-bg-subtle/40 px-4 py-8 text-center text-sm text-muted-foreground">
              还没有保存的篮子。前往{" "}
              <Link className="text-primary underline" href="/builder?mode=basket">
                篮子模式
              </Link>{" "}
              配置并保存，或复制一个示例开始。
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {board.mine.map((record) => (
                <BasketCard
                  key={record.basket_id}
                  record={record}
                  access={basketAccess(record, viewer)}
                  busyId={busyId}
                  onCopy={onCopy}
                  onDelete={setDeleteTarget}
                  onRecompute={onRecompute}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      <AlertDialog
        open={deleteTarget != null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除篮子？</AlertDialogTitle>
            <AlertDialogDescription>
              确定删除篮子「{deleteTarget?.name ?? ""}」？该操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleting}
              onClick={(event) => {
                event.preventDefault();
                if (deleteTarget) void onDelete(deleteTarget);
              }}
            >
              {deleting ? "删除中…" : "确认删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
