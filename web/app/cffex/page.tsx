import { Suspense } from "react";
import type { Metadata } from "next";
import { CffexClient } from "./CffexClient";

export const metadata: Metadata = {
  title: "期货看板 — 中金所股指期货",
  description:
    "中金所股指期货实时行情看板：IF/IH/IC/IM 实时合约监控、历史年化升贴水率走势、统计分位分析。",
  alternates: { canonical: "/cffex" },
  openGraph: {
    title: "期货看板 | Balanced Portfolio",
    description:
      "中金所股指期货实时行情看板：IF/IH/IC/IM 实时合约监控、历史年化升贴水率走势、统计分位分析。",
    url: "/cffex",
  },
};

export default function CffexPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background flex items-center justify-center">
          <div className="text-muted-foreground text-sm">加载中...</div>
        </div>
      }
    >
      <CffexClient />
    </Suspense>
  );
}
