import {
  ChartSkeleton,
  LoadingRegion,
  StatCardsSkeleton,
  TableSkeleton,
} from "@/components/ui/loading";
import { Skeleton } from "@/components/ui/skeleton";

/** /cffex loading：尺寸对齐 CffexClient（4 张指数卡 + 9 列合约表 + 440px 图表 + 13 列统计表）。 */
export default function CffexLoading() {
  return (
    <LoadingRegion label="股指期货看板正在加载" className="min-h-screen bg-background pb-24">
      <div className="border-b border-border/40 bg-card/30 backdrop-blur-sm">
        <div className="container mx-auto max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div className="space-y-2">
              <Skeleton className="h-8 w-48 sm:h-9" />
              <Skeleton className="h-3.5 w-72 max-w-full" />
            </div>
            <div className="flex flex-col items-start gap-1 sm:items-end">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-3 w-36" />
            </div>
          </div>
        </div>
      </div>

      <div className="container mx-auto max-w-[1600px] space-y-8 px-4 py-6 sm:px-6 sm:py-8">
        <StatCardsSkeleton count={4} columns="grid-cols-2 md:grid-cols-4" cardHeight="h-[88px]" />

        <div className="overflow-hidden rounded-xl border border-border/50 bg-card/30">
          <div className="flex flex-col gap-3 border-b border-border/40 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <Skeleton className="h-5 w-24" />
            <div className="flex gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-10 rounded-md" />
              ))}
            </div>
          </div>
          <TableSkeleton rows={8} columns={9} firstColWidth="w-16" />
        </div>

        <div className="overflow-hidden rounded-xl border border-border/50 bg-card/30">
          <div className="flex items-center justify-between border-b border-border/40 px-5 py-4">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-3 w-56" />
          </div>
          <div className="px-5 pb-2 pt-4">
            <ChartSkeleton height={440} />
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-border/50 bg-card/30">
          <div className="flex flex-col gap-3 border-b border-border/40 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <Skeleton className="h-5 w-44" />
            <Skeleton className="h-8 w-64" />
          </div>
          <TableSkeleton rows={4} columns={8} firstColWidth="w-16" />
        </div>
      </div>
    </LoadingRegion>
  );
}
