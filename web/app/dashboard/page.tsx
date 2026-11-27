import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getCachedDemoResult, resolveDefaultPortfolioId } from "@/lib/cached-data";
import { DashboardModeGate } from "./DashboardModeGate";
import { DashboardPageSkeleton } from "./DashboardSkeleton";

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

type SearchParams = Promise<{ id?: string; mode?: string }>;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { id, mode: rawMode } = await searchParams;
  const mode = rawMode === "basket" ? "basket" : "quadrant";
  const portfolioId = id ? Number(id) : null;

  // 一篮子资产模式不需要默认组合同步重定向与 demo 回测结果。
  if (mode === "quadrant" && (portfolioId == null || Number.isNaN(portfolioId))) {
    // 需求2 + 性能修复: 登录用户无 id 时, 在页面顶层(而非 Suspense 内)直接 307 重定向到其默认组合,
    // 避免「先渲染 demo → 客户端再 router.replace」的二次请求与闪烁。
    // 必须放在 Suspense 之外: redirect() 在 PPR 的 Suspense 边界内不会产生 3xx。
    const defaultId = await resolveDefaultPortfolioId();
    if (defaultId != null) {
      redirect(`/dashboard?id=${defaultId}`);
    }
  }

  const initialDemo =
    mode === "quadrant" && (portfolioId == null || Number.isNaN(portfolioId))
      ? await getCachedDemoResult()
      : null;

  return (
    <Suspense fallback={<DashboardPageSkeleton mode={mode} />}>
      <DashboardModeGate mode={mode} initialDemo={initialDemo} />
    </Suspense>
  );
}
