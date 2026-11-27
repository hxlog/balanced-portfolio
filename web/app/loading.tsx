import {
  ChartSkeleton,
  LoadingRegion,
  PageHeaderSkeleton,
  StatCardsSkeleton,
  TableSkeleton,
} from "@/components/ui/loading";

/** 全站兜底 loading：任何未自带 loading.tsx 的路由在流式加载时显示骨架，而非纯文本「加载中」。 */
export default function RootLoading() {
  return (
    <LoadingRegion label="页面正在加载" className="w-full flex-1">
      <div className="mx-auto w-full max-w-[1600px] space-y-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <PageHeaderSkeleton />
        <StatCardsSkeleton />
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <TableSkeleton rows={6} columns={5} />
        </div>
        <ChartSkeleton height={320} />
      </div>
    </LoadingRegion>
  );
}
