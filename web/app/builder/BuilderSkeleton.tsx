/**
 * /builder 的局部 loading 骨架（需求 P2-4：禁用整页 loading）。
 *
 * BuilderPageSkeleton 复刻「居中模式条 + 标题 + 步骤条 + 表单卡」布局，
 * 供 page.tsx 的 Suspense fallback、BuilderClient 的懒加载/编辑预填充与
 * BasketBuilder 首屏兜底共用；颜色/圆角沿用现网（bg-muted + animate-pulse）。
 */
import { cn } from "@/lib/utils";

function Block({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
    />
  );
}

/** 模式条 + 标题 + 步骤条 + 内容卡片的整页骨架。 */
export function BuilderPageSkeleton({
  showSteps = true,
  cards = 2,
}: {
  showSteps?: boolean;
  cards?: number;
}) {
  return (
    <div className="flex-1 bg-bg-subtle/30 pb-20 sm:pb-24">
      <div className="border-b border-border bg-background px-4 py-3 sm:px-6 md:py-6 lg:py-8 xl:py-10">
        <div className="mx-auto max-w-5xl">
          <div className="flex justify-center">
            <Block className="h-9 w-64 rounded-lg" />
          </div>
          <div className="mt-5 flex justify-center">
            <Block className="h-7 w-44" />
          </div>
          {showSteps ? (
            <div className="mt-8 flex items-center justify-center gap-6 sm:gap-16">
              {Array.from({ length: 3 }).map((_, index) => (
                <div key={index} className="flex items-center gap-2">
                  <Block className="h-7 w-7 rounded-full sm:h-8 sm:w-8" />
                  <Block className="h-4 w-16" />
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className="mx-auto mt-8 max-w-7xl p-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: cards * 2 }).map((_, index) => (
            <div
              key={index}
              className="space-y-3 rounded-xl border border-border bg-card p-4"
            >
              <Block className="h-4 w-24" />
              <Block className="h-5 w-12 rounded-full" />
              <Block className="h-10 w-full" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** 仅表单区域骨架（编辑预填充时使用，不重复画模式条）。 */
export function BuilderFormSkeleton() {
  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6" aria-busy="true">
      <div className="flex justify-center">
        <Block className="h-6 w-40" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="space-y-3 rounded-xl border border-border bg-card p-4">
            <Block className="h-4 w-24" />
            <Block className="h-10 w-full" />
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, index) => (
            <div key={index} className="space-y-2">
              <Block className="h-3 w-20" />
              <Block className="h-9 w-full" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
