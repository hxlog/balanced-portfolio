import type { Metadata } from "next";
import { Suspense } from "react";
import { connection } from "next/server";
import { getValuationHomeData } from "@/lib/valuation-server-data";
import type {
  PercentileWindow,
  ValuationMetric,
} from "@/lib/valuation-types";
import { ValuationHomeV2 } from "./ValuationHomeV2";
import { DataFreshnessBadge } from "./_components/valuation-freshness-badge";

export const metadata: Metadata = {
  title: "指数估值 — Valuation Band 与分位矩阵",
  description:
    "指数估值看板：代表性宽基与 521 只指数的 PE/PB/股息率/风险溢价分位、Valuation Band、红利指数吸引力与估值矩阵。",
  alternates: { canonical: "/valuation" },
  openGraph: {
    title: "指数估值 | Balanced Portfolio",
    description:
      "指数估值看板：Valuation Band、多窗口分位、红利指数吸引力与估值矩阵。",
    url: "/valuation",
  },
};

const WINDOWS = new Set<PercentileWindow>(["1y", "3y", "5y", "10y", "all"]);
const METRICS = new Set<ValuationMetric>(["pe_ttm", "pb", "dividend_yield_ttm", "erp"]);

function normalizeWindow(value: string | string[] | undefined): PercentileWindow {
  const text = Array.isArray(value) ? value[0] : value;
  return text && WINDOWS.has(text as PercentileWindow) ? (text as PercentileWindow) : "5y";
}

function normalizeMetric(value: string | string[] | undefined): ValuationMetric {
  const text = Array.isArray(value) ? value[0] : value;
  return text && METRICS.has(text as ValuationMetric) ? (text as ValuationMetric) : "pe_ttm";
}

async function ValuationContent({
  window,
  metric,
}: {
  window: PercentileWindow;
  metric: ValuationMetric;
}) {
  await connection();
  // 服务端一次取数：新快照接口（4 指标分位）+ 默认指数 4 指标历史 + MVI。
  // 任一接口失败只降级对应区块，页面其余部分照常渲染（不伪造数据）。
  const data = await getValuationHomeData({ window, metric });
  return (
    <ValuationHomeV2
      rows={data.rows}
      proxies={data.proxies}
      histories={data.histories}
      mvi={data.mvi}
      window={window}
      metric={metric}
    />
  );
}

function ContentSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 pb-16 pt-4 sm:px-6 lg:px-8" role="status">
      <span className="sr-only">正在加载估值数据</span>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="h-[120px] animate-pulse rounded-xl border border-border bg-muted/40" />
        ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="h-[340px] animate-pulse rounded-xl border border-border bg-muted/40 xl:col-span-2" />
        <div className="h-[340px] animate-pulse rounded-xl border border-border bg-muted/40" />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="h-[320px] animate-pulse rounded-xl border border-border bg-muted/40 xl:col-span-2" />
        <div className="h-[320px] animate-pulse rounded-xl border border-border bg-muted/40" />
      </div>
      <div className="mt-4 h-[420px] animate-pulse rounded-xl border border-border bg-muted/40" />
    </div>
  );
}

export default async function ValuationPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const window = normalizeWindow(params.window);
  const metric = normalizeMetric(params.metric);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1600px] px-4 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-4">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">指数估值</h1>
          <DataFreshnessBadge />
        </header>
      </div>
      <Suspense fallback={<ContentSkeleton />}>
        <ValuationContent window={window} metric={metric} />
      </Suspense>
    </div>
  );
}
