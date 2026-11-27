import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

/**
 * /valuation/[code] 静态壳（2026-11-27 第二轮反馈 B5）。
 *
 * 页面容器与返回链接不依赖数据：路由 loading 与页内 Suspense fallback 都复用它，
 * 打开详情时先出现可点击的静态壳 + 内容骨架，数据到达后只有内容区域被替换，
 * 不会整页闪烁。保持现视觉（container / 间距 / 字号不变）。
 */
export function ValuationDetailShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-6 sm:px-6 sm:pt-8 lg:px-8">
        <Link
          href="/valuation"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          指数估值
        </Link>
        {children}
      </div>
    </div>
  );
}
