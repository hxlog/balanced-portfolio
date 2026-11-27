import { LoadingRegion } from "@/components/ui/loading";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

/** /methodology loading：文档阅读栏（正文 + 右侧目录）骨架，避免编译 MDX 期间白屏。 */
export default function MethodologyLoading() {
  return (
    <LoadingRegion label="方法论文档正在加载" className="w-full flex-1">
      <div className="mx-auto flex max-w-6xl items-start gap-16 px-4 py-8 sm:px-6 sm:py-12">
        <div className="min-w-0 flex-1 space-y-6">
          <Skeleton className="h-9 w-64 max-w-full" />
          <SkeletonText lines={3} />
          <div className="space-y-3 pt-4">
            <Skeleton className="h-6 w-52" />
            <SkeletonText lines={4} />
          </div>
          <div className="space-y-3 pt-4">
            <Skeleton className="h-6 w-40" />
            <SkeletonText lines={5} />
          </div>
          <div className="space-y-3 pt-4">
            <Skeleton className="h-6 w-44" />
            <SkeletonText lines={3} />
          </div>
        </div>
        <div className="hidden w-44 shrink-0 space-y-2 lg:block">
          <Skeleton className="h-4 w-20" />
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-full" />
          ))}
        </div>
      </div>
    </LoadingRegion>
  );
}
