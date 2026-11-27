import {
  LoadingRegion,
  TableSkeleton,
} from "@/components/ui/loading";
import { Skeleton } from "@/components/ui/skeleton";

/** /otc-derivatives-pricing loading：对齐「标题卡 + 迷你日历 / 参数表单 / 簿记表」三段。 */
export default function OtcDerivativesPricingLoading() {
  return (
    <LoadingRegion
      label="场外衍生品定价页正在加载"
      className="mx-auto w-full max-w-[1600px] flex-1 space-y-4 px-4 py-4 sm:space-y-6 sm:p-6"
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-3 rounded-xl border border-border bg-card p-5 lg:col-span-2">
          <div className="flex items-center gap-2">
            <Skeleton className="h-5 w-5 rounded" />
            <Skeleton className="h-6 w-36" />
            <Skeleton className="h-5 w-52 rounded-full" />
          </div>
          <Skeleton className="h-3.5 w-full max-w-2xl" />
          <Skeleton className="h-3.5 w-2/3 max-w-xl" />
          <div className="flex gap-2 pt-1">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-20 rounded-full" />
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-6 w-24" />
          </div>
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: 35 }).map((_, i) => (
              <Skeleton key={i} className="h-6" />
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border/60 px-5 py-4">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-8 w-40 rounded-full" />
        </div>
        <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border/60 px-5 py-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-3 w-24" />
        </div>
        <TableSkeleton rows={5} columns={9} firstColWidth="w-24" />
      </div>
    </LoadingRegion>
  );
}
