import { Suspense } from "react";
import type { Metadata } from "next";
import { getCachedAssets } from "@/lib/cached-data";
import BuilderClient from "./BuilderClient";

export const metadata: Metadata = {
  title: "组合构建器",
  description:
    "在达利欧四象限中放入自选资产做风险平价回测，或切换到一篮子模式，对单层资产池做风险平价 / 最大夏普等六种优化。",
  alternates: { canonical: "/builder" },
  openGraph: {
    title: "组合构建器 | Balanced Portfolio",
    description:
      "四象限组合构建与一篮子资产（风险平价）模式：选择资产与优化方法，自动计算权重并回测。",
    url: "/builder",
  },
};

export default function BuilderPage() {
  return (
    <Suspense fallback={<div className="p-12 text-center text-muted-foreground">加载中...</div>}>
      <BuilderLoader />
    </Suspense>
  );
}

async function BuilderLoader() {
  const initialAssets = await getCachedAssets();
  return <BuilderClient initialAssets={initialAssets} />;
}
