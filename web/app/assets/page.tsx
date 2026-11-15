import type { Metadata } from "next";
import { AssetsClient } from "./AssetsClient";

export const metadata: Metadata = {
  title: "资产池 — 股票 / 指数 / 基金 / ETF 统一搜索",
  description: "统一资产池：A 股 5,200+、指数 521、基金/ETF；支持不复权 / 前复权 / 后复权三口径查看，回测默认后复权。",
  alternates: { canonical: "/assets" },
};

export default function AssetsPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">资产池</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              股票 / 指数 / 基金 / ETF 统一搜索 · 三口径复权状态 · 数据覆盖
            </p>
          </div>
        </header>
        <AssetsClient />
      </div>
    </div>
  );
}
