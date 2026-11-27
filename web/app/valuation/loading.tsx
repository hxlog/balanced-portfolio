/**
 * /valuation 路由级 Suspense 骨架屏。
 *
 * 结构与新首页（页头徽标 → 窗口工具条 → 5 张宽基卡 → Valuation Band + 行业热力 →
 * 红利吸引力 + MVI → 两张估值矩阵 → 指数列表）一一对应，避免数据到达时布局跳动。
 * 只使用语义 token（bg-muted / bg-card / border-border），不引入图表库。
 */
export default function ValuationLoading() {
  return (
    <div
      className="min-h-screen bg-background text-foreground"
      role="status"
      aria-live="polite"
    >
      <span className="sr-only">正在加载指数估值数据</span>

      <div className="mx-auto w-full max-w-[1600px] px-4 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-4">
          <div className="h-8 w-32 animate-pulse rounded bg-muted" />
          <div className="h-6 w-40 animate-pulse rounded-full bg-muted" />
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 sm:px-6 lg:px-8">
        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="h-4 w-56 animate-pulse rounded bg-muted" />
          <div className="h-7 w-64 animate-pulse rounded-full bg-muted" />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="h-[120px] animate-pulse rounded-xl border border-border bg-card" />
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="h-[400px] animate-pulse rounded-xl border border-border bg-card xl:col-span-2" />
          <div className="h-[400px] animate-pulse rounded-xl border border-border bg-card" />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="h-[380px] animate-pulse rounded-xl border border-border bg-card xl:col-span-2" />
          <div className="h-[380px] animate-pulse rounded-xl border border-border bg-card" />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="h-[340px] animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-[340px] animate-pulse rounded-xl border border-border bg-card" />
        </div>

        <div className="mt-6 space-y-3">
          <div className="h-5 w-32 animate-pulse rounded bg-muted" />
          <div className="h-[420px] animate-pulse rounded-xl border border-border bg-card" />
        </div>
      </div>
    </div>
  );
}
