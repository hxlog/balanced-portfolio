/**
 * /valuation/[code] 的 Suspense 骨架屏。
 *
 * 结构与详情页首屏一一对应：面包屑 + 头部 → 4 个指标卡 → 控制器 → 左图右栏 →
 * 跟踪基金卡，避免数据到达时发生布局跳动。仅使用语义 token，不引入图表库。
 */
export function ValuationDetailSkeleton() {
  return (
    <div
      className="min-h-screen bg-background text-foreground"
      role="status"
      aria-live="polite"
    >
      <span className="sr-only">正在加载指数估值详情</span>

      <div className="mx-auto w-full max-w-[1600px] px-4 pb-4 pt-6 sm:px-6 sm:pt-8 lg:px-8">
        <div className="h-3.5 w-20 animate-pulse rounded bg-muted" />
        <div className="mt-3 h-8 w-56 animate-pulse rounded bg-muted" />
        <div className="mt-2 h-3 w-64 animate-pulse rounded bg-muted" />
      </div>

      <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="h-[112px] animate-pulse rounded-xl border border-border bg-card"
            />
          ))}
        </div>

        <div className="mt-3 h-10 w-full animate-pulse rounded bg-muted" />

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="space-y-4 xl:col-span-2">
            <div className="h-[360px] animate-pulse rounded-xl border border-border bg-card" />
            <div className="h-[220px] animate-pulse rounded-xl border border-border bg-card" />
            <div className="h-[240px] animate-pulse rounded-xl border border-border bg-card" />
          </div>
          <div className="space-y-4">
            <div className="h-[180px] animate-pulse rounded-xl border border-border bg-card" />
            <div className="h-[220px] animate-pulse rounded-xl border border-border bg-card" />
            <div className="h-[180px] animate-pulse rounded-xl border border-border bg-card" />
          </div>
        </div>

        <div className="mt-4 h-[320px] animate-pulse rounded-xl border border-border bg-card" />
      </div>
    </div>
  );
}
