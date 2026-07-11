import { Suspense } from "react";
import type { Metadata } from "next";
import { getCachedAssets } from "@/lib/cached-data";
import BuilderClient from "./BuilderClient";

export const metadata: Metadata = {
  title: "组合构建器",
  description:
    "在达利欧四象限中放入自选资产，选择优化方法与回测参数，生成可复制的风险平价配置并触发回测。",
  alternates: { canonical: "/builder" },
  openGraph: {
    title: "组合构建器 | Balanced Portfolio",
    description:
      "在达利欧四象限中放入自选资产，选择优化方法与回测参数，生成可复制的风险平价配置并触发回测。",
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
