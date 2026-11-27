import { Suspense } from "react";
import type { Metadata } from "next";
import BuilderClient from "./BuilderClient";
import { BuilderPageSkeleton } from "./BuilderSkeleton";

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
  // 不在服务端阻塞资产清单：BuilderClient 内部会自行拉取 /api/assets。
  // 这样即使后端慢/不可用，页面壳与模式切换也能立即交互（避免整页停在“加载中”）。
  return (
    <Suspense fallback={<BuilderPageSkeleton />}>
      <BuilderClient initialAssets={[]} />
    </Suspense>
  );
}
