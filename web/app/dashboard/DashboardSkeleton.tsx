/**
 * Dashboard 局部 loading 骨架（需求 P2-4：每个卡片独立 skeleton，禁用整页 loading）。
 *
 * 只做「占位形状」不引业务逻辑：
 * - SkeletonKpi / SkeletonChart / SkeletonTable 按卡片内容类型分开；
 * - DashboardContentSkeleton 复刻真实页面的 TOC + 内容列布局，首屏加载与
 *   Suspense fallback 共用，避免从「居中一行加载中」跳到两栏布局的布局位移。
 *
 * 视觉沿用现网：animate-pulse + bg-muted + 同圆角，不引新色值。
 */
import type { CSSProperties } from "react";
import { cn } from "@/lib/utils";

export function SkeletonBlock({
  className,
  style,
}: {
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden="true"
      style={style}
      className={cn("animate-pulse rounded-md bg-muted", className)}
    />
  );
}

/** KPI / 指标卡：一个标题行 + 一个大数字 + 一行注释。 */
export function SkeletonKpi({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-4", className)}>
      <SkeletonBlock className="h-3 w-16" />
      <SkeletonBlock className="mt-2 h-7 w-24" />
      <SkeletonBlock className="mt-2 h-3 w-20" />
    </div>
  );
}

/** 图表卡：标题 + 绘图区。 */
export function SkeletonChart({
  height = 300,
  className,
}: {
  height?: number;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card", className)}>
      <div className="space-y-2 px-5 pt-5">
        <SkeletonBlock className="h-4 w-32" />
        <SkeletonBlock className="h-3 w-52" />
      </div>
      <div className="px-5 pb-5 pt-4">
        <SkeletonBlock className="w-full" style={{ height }} />
      </div>
    </div>
  );
}

/** 表格卡：标题 + 若干行 × 若干列。 */
export function SkeletonTable({
  rows = 6,
  cols = 4,
  className,
}: {
  rows?: number;
  cols?: number;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card", className)}>
      <div className="space-y-2 px-5 pt-5">
        <SkeletonBlock className="h-4 w-28" />
      </div>
      <div className="space-y-3 px-5 pb-5 pt-4">
        <div className="flex gap-3">
          {Array.from({ length: cols }).map((_, index) => (
            <SkeletonBlock key={index} className="h-3 flex-1" />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, row) => (
          <div key={row} className="flex gap-3">
            {Array.from({ length: cols }).map((_, col) => (
              <SkeletonBlock key={col} className="h-3 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 顶部信息卡（组合名 / 描述 / 参数 / 组合下拉区域）。 */
function SkeletonTopBar() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-col gap-4 px-5 pt-5 pb-4 sm:flex-row sm:justify-between">
        <div className="min-w-0 flex-1 space-y-2">
          <SkeletonBlock className="h-6 w-48" />
          <SkeletonBlock className="h-3 w-full max-w-xl" />
        </div>
        <SkeletonBlock className="h-8 w-24 rounded-full" />
      </div>
      <div className="flex flex-col gap-3 border-t border-border bg-muted/20 px-5 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col items-center gap-1 sm:flex-row sm:justify-center">
          <SkeletonBlock className="h-3 w-8" />
          <SkeletonBlock className="h-8 w-full max-w-[22rem]" />
        </div>
        <div className="flex gap-2">
          <SkeletonBlock className="h-8 w-16" />
          <SkeletonBlock className="h-8 w-16" />
        </div>
      </div>
    </div>
  );
}

/** 「组合参数」栅格卡（KPI 语义：多列标签 + 值）。 */
function SkeletonParamsCard() {
  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="space-y-2 px-5 pt-5">
        <SkeletonBlock className="h-4 w-24" />
        <SkeletonBlock className="h-3 w-56" />
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 px-5 pb-5 pt-4 md:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 12 }).map((_, index) => (
          <div key={index} className="space-y-1.5">
            <SkeletonBlock className="h-3 w-16" />
            <SkeletonBlock className="h-4 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** 四象限矩阵卡：2×2 网格。 */
function SkeletonQuadrantCard() {
  return (
    <div className="rounded-xl border border-border bg-card lg:col-span-2">
      <div className="space-y-2 px-5 pt-5">
        <SkeletonBlock className="h-4 w-40" />
        <SkeletonBlock className="h-3 w-full max-w-lg" />
      </div>
      <div className="px-5 pb-5 pt-4">
        <div className="grid grid-cols-2 grid-rows-2 gap-px overflow-hidden rounded-lg border border-border bg-border">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="space-y-2 bg-bg-subtle p-4">
              <SkeletonBlock className="h-3 w-20" />
              <div className="flex flex-wrap gap-1.5">
                <SkeletonBlock className="h-5 w-16 rounded-full" />
                <SkeletonBlock className="h-5 w-20 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** 当期持仓卡：环形图 + 表格。 */
function SkeletonHoldingsCard() {
  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="space-y-3 px-5 pt-5">
        <div className="flex items-center justify-between">
          <SkeletonBlock className="h-4 w-20" />
          <SkeletonBlock className="h-7 w-28" />
        </div>
        <SkeletonBlock className="h-3 w-40" />
        <SkeletonBlock className="h-3 w-36" />
      </div>
      <div className="space-y-4 px-5 pb-5 pt-4">
        <SkeletonBlock className="mx-auto h-[180px] w-[180px] rounded-full" />
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="flex justify-between gap-4">
            <SkeletonBlock className="h-3 w-28" />
            <SkeletonBlock className="h-3 w-12" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** 方法切换条骨架。 */
function SkeletonMethodBar() {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-2">
      <SkeletonBlock className="mx-2 h-3 w-16" />
      {Array.from({ length: 4 }).map((_, index) => (
        <SkeletonBlock key={index} className="h-8 w-28 rounded-lg" />
      ))}
    </div>
  );
}

/**
 * Dashboard 内容列骨架：与真实页面同布局（TOC 列 + 内容列 + 各卡片）。
 * 用于首屏加载 / 模式 Suspense fallback，替换原来的整页「正在加载回测结果...」。
 */
export function DashboardContentSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1600px] flex-1 space-y-4 px-4 py-4 sm:space-y-6 sm:p-6">
      <div className="flex gap-6">
        {/* TOC 列占位（lg 起显示，与真实 DashboardToc 同宽） */}
        <div className="hidden w-44 shrink-0 space-y-2 lg:block">
          <SkeletonBlock className="h-3 w-16" />
          {Array.from({ length: 11 }).map((_, index) => (
            <SkeletonBlock key={index} className="h-6 w-full" />
          ))}
        </div>
        <div className="min-w-0 flex-1 space-y-4 sm:space-y-6">
          <SkeletonTopBar />
          <SkeletonParamsCard />
          <SkeletonMethodBar />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <SkeletonQuadrantCard />
            <SkeletonHoldingsCard />
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SkeletonChart height={300} />
            <SkeletonTable rows={7} cols={4} />
          </div>
          <SkeletonTable rows={5} cols={9} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SkeletonTable rows={9} cols={3} />
            <SkeletonChart height={260} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** 「一篮子资产」列表面板骨架（Dashboard basket 模式 / Suspense fallback）。 */
export function BasketBoardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="space-y-2 px-5 pt-5">
        <SkeletonBlock className="h-5 w-32" />
        <SkeletonBlock className="h-3 w-full max-w-xl" />
      </div>
      <div className="grid grid-cols-1 gap-3 px-5 pb-5 pt-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="space-y-2 rounded-lg border border-border p-3">
            <SkeletonBlock className="h-4 w-32" />
            <SkeletonBlock className="h-3 w-48" />
            <SkeletonBlock className="h-3 w-40" />
            <div className="flex gap-2 pt-2">
              <SkeletonBlock className="h-7 w-16" />
              <SkeletonBlock className="h-7 w-16" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
/**
 * Dashboard 路由级 Suspense fallback（page.tsx 使用）：
 * 先渲染模式条骨架，再按模式渲染对应内容骨架 —— 替换原来整页「加载中...」。
 */
export function DashboardPageSkeleton({
  mode = "quadrant",
}: {
  mode?: "quadrant" | "basket";
}) {
  return (
    <>
      <div className="mx-auto w-full max-w-[1600px] px-4 pt-6 sm:px-6">
        <div className="lg:pl-[12.5rem]">
          <div className="flex min-h-9 items-center justify-center">
            <SkeletonBlock className="h-9 w-64 rounded-lg" />
          </div>
        </div>
      </div>
      {mode === "basket" ? (
        <div className="mx-auto w-full max-w-[1600px] px-4 pt-4 pb-12 sm:px-6">
          <div className="lg:pl-[12.5rem]">
            <BasketBoardSkeleton />
          </div>
        </div>
      ) : (
        <DashboardContentSkeleton />
      )}
    </>
  );
}
