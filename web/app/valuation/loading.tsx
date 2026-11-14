/**
 * /valuation 的 Suspense 骨架屏。
 *
 * 结构与 ValuationHome 的三个区块一一对应，避免数据到达时发生布局跳动：
 * 页头 → 4 张板块卡 → 宽基表 → 全部指数工具栏 + 表。
 * 使用语义 token（bg-muted / bg-card / border-border），不引入图表库。
 */
export default function ValuationLoading() {
  return (
    <div
      className="min-h-screen bg-background text-foreground"
      role="status"
      aria-live="polite"
    >
      <span className="sr-only">正在加载指数估值数据</span>

      <div className="border-b border-border/60 bg-card/30">
        <div className="mx-auto w-full max-w-[1240px] px-4 py-7 sm:px-6 sm:py-8">
          <div className="h-4 w-24 animate-pulse rounded bg-muted" />
          <div className="mt-4 h-8 w-40 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-4 w-full max-w-xl animate-pulse rounded bg-muted" />
          <div className="mt-5 h-10 w-full animate-pulse rounded-lg bg-muted" />
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1240px] space-y-10 px-4 py-6 sm:px-6 sm:py-8">
        <section aria-hidden="true">
          <div className="h-5 w-28 animate-pulse rounded bg-muted" />
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="h-[248px] animate-pulse rounded-xl border border-border bg-card"
              />
            ))}
          </div>
        </section>

        <section aria-hidden="true">
          <div className="h-5 w-28 animate-pulse rounded bg-muted" />
          <div className="mt-4 h-[560px] animate-pulse rounded-xl border border-border bg-card" />
        </section>

        <section aria-hidden="true">
          <div className="h-5 w-36 animate-pulse rounded bg-muted" />
          <div className="mt-4 h-9 w-full animate-pulse rounded-lg bg-muted" />
          <div className="mt-3 h-[820px] animate-pulse rounded-xl border border-border bg-card" />
        </section>
      </div>
    </div>
  );
}
