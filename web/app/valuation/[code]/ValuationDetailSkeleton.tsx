/**
 * `/valuation/[code]` 的 Suspense 骨架屏。
 *
 * 结构与详情页首屏（页头 + 4 指标 + Tab 栏 + 左图右栏）一一对应，避免布局跳动。
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

      <div className="mx-auto w-full max-w-[1440px] px-4 pb-4 pt-6 sm:px-6 sm:pt-8 lg:px-8">
        <div className="h-3.5 w-20 animate-pulse rounded bg-muted" />
        <div className="mt-3 h-3 w-32 animate-pulse rounded bg-muted" />
        <div className="mt-2 h-8 w-52 animate-pulse rounded bg-muted" />
        <div className="mt-2 h-3 w-56 animate-pulse rounded bg-muted" />
      </div>

      <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="h-[112px] animate-pulse rounded-xl border border-border bg-card"
            />
          ))}
        </div>

        <div className="mt-6 h-9 w-full max-w-xs animate-pulse rounded-md bg-muted" />

        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)]">
          <div className="h-[340px] animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-[340px] animate-pulse rounded-xl border border-border bg-card" />
        </div>
      </div>
    </div>
  );
}
