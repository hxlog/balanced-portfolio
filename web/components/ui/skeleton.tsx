import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 统一骨架屏原语。
 *
 * 约定：
 * - 尺寸由调用方通过 className 指定，且必须与真实内容尺寸一致（避免 layout shift）；
 * - 低对比 bg-muted + pulse，不改变现有色板；
 * - prefers-reduced-motion 下关闭脉冲动画；
 * - aria-hidden 由本组件自带，语义播报交给外层 LoadingRegion（role="status"）。
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "animate-pulse rounded-md bg-muted motion-reduce:animate-none",
        className,
      )}
      {...props}
    />
  );
}
Skeleton.displayName = "Skeleton";

/** 多行文本骨架：最后一行默认 60% 宽，模拟真实段落。 */
function SkeletonText({
  lines = 1,
  className,
  lineClassName,
}: {
  lines?: number;
  className?: string;
  lineClassName?: string;
}) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn(
            "h-3.5 w-full",
            index === lines - 1 && lines > 1 && "w-3/5",
            lineClassName,
          )}
        />
      ))}
    </div>
  );
}
SkeletonText.displayName = "SkeletonText";

export { Skeleton, SkeletonText };
