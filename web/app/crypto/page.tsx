import { Suspense } from "react";
import { connection } from "next/server";
import type { Metadata } from "next";
import { getCachedCryptoCorrelation } from "@/lib/cached-data";
import {
  getCachedCryptoFuturesContracts,
  getCachedCryptoFuturesSummary,
} from "@/lib/crypto-futures-data";
import type { CryptoFuturesContract, CryptoFuturesSummary } from "@/lib/crypto-futures-types";
import type { CryptoCorrelationResponse } from "@/lib/api";
import { ChartSkeleton, TableSkeleton } from "@/components/ui/loading";
import { Skeleton } from "@/components/ui/skeleton";
import { CryptoClient } from "./CryptoClient";
import { CryptoFuturesHome } from "../crypto-futures/CryptoFuturesHome";

export const metadata: Metadata = {
  title: "加密货币看板 — 合约监控与 BTC 相关性",
  description:
    "加密合约监控（OI、资金费率、大户多空、Smart Money 乖离）与 BTC 90 日滚动相关性（黄金/标普500/纳斯达克100/DXY）。",
  alternates: { canonical: "/crypto" },
  openGraph: {
    title: "加密货币看板 | Balanced Portfolio",
    description:
      "加密合约监控（OI、资金费率、大户多空、Smart Money 乖离）与 BTC 相关性分析。",
    url: "/crypto",
  },
};

/** 合约监控段局部骨架：尺寸对齐 CryptoFuturesHome（5 张指标卡 + 双 560px 图）。 */
function FuturesSectionSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 min-[1100px]:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 min-[1100px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Skeleton className="h-[560px] rounded-xl" />
        <Skeleton className="h-[560px] rounded-xl" />
      </div>
    </div>
  );
}

/** BTC 相关性段局部骨架：尺寸对齐 CryptoClient（工具条 + 快照/相关性卡 + 双 440px 图 + 数据表）。 */
function CorrelationSectionSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 rounded-xl border border-border/60 bg-card/40 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex gap-2">
          <Skeleton className="h-5 w-52 rounded-full" />
          <Skeleton className="h-5 w-24 rounded-full" />
        </div>
        <div className="flex gap-3">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-8 w-60" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-[76px] rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[92px] rounded-xl" />
        ))}
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="border-b border-border/40 px-5 py-4">
          <Skeleton className="h-6 w-72 max-w-full" />
        </div>
        <div className="px-3 pb-2 pt-4">
          <ChartSkeleton height={440} />
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="border-b border-border/40 px-5 py-4">
          <Skeleton className="h-5 w-32" />
        </div>
        <div className="py-2">
          <TableSkeleton rows={4} columns={5} firstColWidth="w-24" />
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="border-b border-border/40 px-5 py-4">
          <Skeleton className="h-6 w-52 max-w-full" />
        </div>
        <div className="px-3 pb-2 pt-4">
          <ChartSkeleton height={440} />
        </div>
      </div>
    </div>
  );
}

async function CryptoFuturesSection() {
  await connection();
  const [summaryResult, contractsResult] = await Promise.allSettled([
    getCachedCryptoFuturesSummary(),
    getCachedCryptoFuturesContracts(),
  ]);
  const summary: CryptoFuturesSummary | null =
    summaryResult.status === "fulfilled" ? summaryResult.value : null;
  const contracts: CryptoFuturesContract[] =
    contractsResult.status === "fulfilled" ? contractsResult.value : [];
  return <CryptoFuturesHome summary={summary} contracts={contracts} contractsUnavailable={contractsResult.status === "rejected"} />;
}

async function CryptoCorrelationSection() {
  await connection();
  let data: CryptoCorrelationResponse | null = null;
  try {
    data = await getCachedCryptoCorrelation();
  } catch (error) {
    console.error("crypto SSR fetch failed:", error);
  }
  return <CryptoClient data={data} />;
}

export default function CryptoPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">加密货币看板</h1>
            <p className="mt-1 text-xs text-muted-foreground">合约监控 · 大户因子 · 现货相关性（一页看全）</p>
          </div>
          <span className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground">每 5 分钟更新</span>
        </header>

        <section className="mt-5" aria-label="加密合约监控">
          <Suspense fallback={<FuturesSectionSkeleton />}>
            <CryptoFuturesSection />
          </Suspense>
        </section>

        <section className="mt-10 border-t border-border pt-6" aria-label="BTC 相关性">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold">BTC 相关性</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">与黄金 / 标普500 / 纳斯达克100 / DXY 的 90 日滚动相关</p>
            </div>
          </div>
          <Suspense fallback={<CorrelationSectionSkeleton />}>
            <CryptoCorrelationSection />
          </Suspense>
        </section>
      </div>
    </div>
  );
}
