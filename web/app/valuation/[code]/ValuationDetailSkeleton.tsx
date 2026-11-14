/**
 * `/valuation/[code]` 的 Suspense 骨架屏。
 *
 * 结构与详情页首屏（页头 + Tab 栏 + 左图右栏）一一对应，避免数据到达时布局跳动。
 * 仅使用语义 token，不引入图表库。
 */
export function ValuationDetailSkeleton() {
  return (
    <div
      className="min-h-screen bg-background text-foreground"
      role="status"
      aria-live="polite"
    >
      <span className="sr-only">正在加载指数估值详情</span>

      <div className="border-b border-border/60 bg-card/30">
        <div className="mx-auto w-full max-w-[1240px] px-4 py-7 sm:px-6 sm:py-8">
          <div className="h-3.5 w-28 animate-pulse rounded bg-muted" />
          <div className="mt-4 flex flex-wrap gap-2">
            <div className="h-5 w-16 animate-pulse rounded-full bg-muted" />
            <div className="h-5 w-20 animate-pulse rounded-full bg-muted" />
            <div className="h-5 w-14 animate-pulse rounded-full bg-muted" />
          </div>
          <div className="mt-4 h-8 w-56 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-4 w-full max-w-xl animate-pulse rounded bg-muted" />
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1240px] px-4 py-6 sm:px-6 sm:py-8">
        <div className="h-10 w-full max-w-sm animate-pulse rounded-md bg-muted" />

        <div className="mt-6 grid grid-cols-1 gap-6 min-[1100px]:grid-cols-[minmax(0,1fr)_360px]">
          <div className="h-[480px] animate-pulse rounded-xl border border-border bg-card" />
          <div className="space-y-6">
            <div className="h-[248px] animate-pulse rounded-xl border border-border bg-card" />
            <div className="h-[280px] animate-pulse rounded-xl border border-border bg-card" />
          </div>
        </div>
      </div>
    </div>
  );
}
