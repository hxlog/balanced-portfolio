import {
  LoadingRegion,
  PageHeaderSkeleton,
  StatCardsSkeleton,
  TableSkeleton,
} from "@/components/ui/loading";

/** /admin loading：管理页通用骨架（标题 + 卡片 + 表格）。 */
export default function AdminLoading() {
  return (
    <LoadingRegion label="管理后台正在加载" className="w-full flex-1">
      <div className="mx-auto w-full max-w-[1600px] space-y-6 p-6">
        <PageHeaderSkeleton withActions={false} className="border-b-0 pb-0" />
        <StatCardsSkeleton count={3} columns="grid-cols-1 md:grid-cols-3" />
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <TableSkeleton rows={6} columns={6} />
        </div>
      </div>
    </LoadingRegion>
  );
}
