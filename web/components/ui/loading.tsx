import * as React from "react";

import { cn } from "@/lib/utils";
import { Skeleton, SkeletonText } from "./skeleton";

/**
 * 局部 loading 组合件：由路由 loading.tsx 与页内异步区块共用。
 * 所有尺寸都对齐真实内容（页面标题 / 统计卡 / 图表 / 表格），减少 layout shift。
 */

/** 无障碍包装：屏幕阅读器播报「正在加载…」，视觉上由内部骨架承担。 */
export function LoadingRegion({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={className}
    >
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/** 页面标题区：对齐 text-2xl/3xl 标题 + 一行说明（含可选右侧徽章位）。 */
export function PageHeaderSkeleton({
  withActions = true,
  className,
}: {
  withActions?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between",
        className,
      )}
    >
      <div className="space-y-2">
        <Skeleton className="h-8 w-40 sm:h-9 sm:w-48" />
        <Skeleton className="h-3.5 w-64 max-w-full" />
      </div>
      {withActions ? <Skeleton className="h-7 w-32 rounded-full" /> : null}
    </div>
  );
}

/** 统计卡片栅格；columns 直接传真实栅格类名，保证列数与断点一致。 */
export function StatCardsSkeleton({
  count = 4,
  columns = "grid-cols-2 md:grid-cols-4",
  cardHeight = "h-[86px]",
  className,
}: {
  count?: number;
  columns?: string;
  cardHeight?: string;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-4", columns, className)} aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className={cn(
            "rounded-xl border border-border bg-card p-4 sm:p-5",
            cardHeight,
          )}
        >
          <Skeleton className="mb-2 h-3 w-20" />
          <Skeleton className="h-6 w-28" />
        </div>
      ))}
    </div>
  );
}

/** 图表骨架：高度必须与真实 EChart 一致（默认 320；CFFEX/Crypto 为 440）。 */
export function ChartSkeleton({
  height = 320,
  withLegend = true,
  className,
}: {
  height?: number;
  withLegend?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn("w-full", className)}
      style={{ height }}
      aria-hidden="true"
    >
      <div className="flex h-full flex-col justify-end gap-3 rounded-lg bg-muted/20 p-4">
        <div className="flex flex-1 items-end gap-2">
          {[38, 58, 44, 72, 52, 84, 64, 92, 70, 78, 60, 88].map((h, i) => (
            <Skeleton
              key={i}
              className="flex-1 rounded-b-none"
              style={{ height: `${h}%` }}
            />
          ))}
        </div>
        {withLegend ? (
          <div className="flex items-center justify-center gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-2.5 w-16" />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** 表格骨架：列宽按 columns 均分，行高对齐 ui/table 的 p-4 行。 */
export function TableSkeleton({
  rows = 6,
  columns = 5,
  className,
  firstColWidth = "w-28",
}: {
  rows?: number;
  columns?: number;
  className?: string;
  firstColWidth?: string;
}) {
  return (
    <div className={cn("w-full overflow-hidden", className)} aria-hidden="true">
      <div className="flex items-center gap-4 border-b border-border bg-muted/30 px-4 py-3">
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton
            key={index}
            className={cn("h-3", index === 0 ? firstColWidth : "flex-1")}
          />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div
          key={rowIndex}
          className="flex items-center gap-4 border-b border-border/60 px-4 py-4 last:border-0"
        >
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton
              key={colIndex}
              className={cn("h-4", colIndex === 0 ? firstColWidth : "flex-1")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** 卡片内容骨架（表格/图表之外的普通 Card 内容）。 */
export function CardSkeleton({
  className,
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card", className)}>
      <div className="space-y-2 border-b border-border/60 p-5">
        <Skeleton className="h-4 w-28" />
        <SkeletonText lines={1} className="max-w-xs" />
      </div>
      <div className="p-5" aria-hidden="true">
        {children ?? <Skeleton className="h-24 w-full" />}
      </div>
    </div>
  );
}
