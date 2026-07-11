import { Suspense } from "react";
import type { Metadata } from "next";
import { getCachedDemoResult } from "@/lib/cached-data";
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

export default function DashboardPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  return (
    <Suspense fallback={<div className="p-12 text-center text-muted-foreground">加载中...</div>}>
      <DashboardLoader searchParams={searchParams} />
    </Suspense>
  );
}

async function DashboardLoader({ searchParams }: { searchParams: SearchParams }) {
  const { id } = await searchParams;
  const portfolioId = id ? Number(id) : null;
  const initialDemo =
    portfolioId == null || Number.isNaN(portfolioId)
      ? await getCachedDemoResult()
      : null;

  return <DashboardClient initialDemo={initialDemo} />;
}
