import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getCachedDemoResult, resolveDefaultPortfolioId } from "@/lib/cached-data";
import DashboardClient from "./DashboardClient";

export const metadata: Metadata = {
  title: "产品 Dashboard",
  description:
    "查看风险平价组合的回测结果：净值曲线、调仓记录、绩效指标、绩效归因与相关性矩阵。可切换优化方法与对比基准。",
  alternates: { canonical: "/dashboard" },
  openGraph: {
    title: "产品 Dashboard | Balanced Portfolio",
    description:
      "查看风险平价组合的回测结果：净值曲线、调仓记录、绩效指标、绩效归因与相关性矩阵。",
    url: "/dashboard",
  },
};

type SearchParams = Promise<{ id?: string }>;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { id } = await searchParams;
  const portfolioId = id ? Number(id) : null;

  // 需求2 + 性能修复: 登录用户无 id 时, 在页面顶层(而非 Suspense 内)直接 307 重定向到其默认组合,
  // 避免「先渲染 demo → 客户端再 router.replace」的二次请求与闪烁。
  // 必须放在 Suspense 之外: redirect() 在 PPR 的 Suspense 边界内不会产生 3xx。
  if (portfolioId == null || Number.isNaN(portfolioId)) {
    const defaultId = await resolveDefaultPortfolioId();
    if (defaultId != null) {
      redirect(`/dashboard?id=${defaultId}`);
    }
  }

  const initialDemo =
    portfolioId == null || Number.isNaN(portfolioId)
      ? await getCachedDemoResult()
      : null;

  return (
    <Suspense fallback={<div className="p-12 text-center text-muted-foreground">加载中...</div>}>
      <DashboardClient initialDemo={initialDemo} />
    </Suspense>
  );
}
