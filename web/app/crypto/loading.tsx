import { LoadingRegion } from "@/components/ui/loading";
import { Skeleton } from "@/components/ui/skeleton";

/** /crypto loading：对齐页面两段（合约监控 5 卡 + 双 560px 图；BTC 相关性 420px 图）。 */
export default function CryptoLoading() {
  return (
    <LoadingRegion label="加密货币看板正在加载" className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
          <div className="space-y-2">
            <Skeleton className="h-8 w-44 sm:h-9" />
            <Skeleton className="h-3.5 w-72 max-w-full" />
          </div>
          <Skeleton className="h-6 w-24 rounded-full" />
        </div>

        <div className="mt-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 min-[1100px]:grid-cols-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-28 rounded-xl" />
            ))}
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 min-[1100px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <Skeleton className="h-[560px] rounded-xl" />
            <Skeleton className="h-[560px] rounded-xl" />
          </div>
        </div>

        <div className="mt-10 border-t border-border pt-6">
          <div className="mb-3 space-y-2">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-3 w-64" />
          </div>
          <Skeleton className="h-[420px] rounded-xl" />
        </div>
      </div>
    </LoadingRegion>
  );
}
