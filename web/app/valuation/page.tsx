import type { Metadata } from "next";
import { Suspense } from "react";
import { connection } from "next/server";
import { ValuationHome } from "./ValuationHome";
import {
  getCachedValuationHistory,
  getCachedValuationIndices,
  getCachedValuationOverview,
} from "@/lib/cached-data";
import {
  mapBroadProxy,
  mapIndexRow,
  mapMarketCard,
  mapValuationHistory,
} from "@/lib/valuation-api-map";
import type {
  BroadProxyCard,
  IndexQuoteRow,
  MarketValuationCard,
  PercentileWindow,
  ValuationHistory,
} from "@/lib/valuation-types";

const DEFAULT_WINDOW: PercentileWindow = "5y";
const DEFAULT_PROXY = "000300";

export const metadata: Metadata = {
  title: "指数估值 — PE/PB 分位与风险溢价",
  description:
    "指数估值看板：沪深300、中证500、中证1000 等宽基与行业指数的 PE/PB 历史分位、股息率与风险溢价。",
  alternates: { canonical: "/valuation" },
  openGraph: {
    title: "指数估值 | Balanced Portfolio",
    description:
      "指数估值看板：沪深300、中证500、中证1000 等宽基与行业指数的 PE/PB 历史分位、股息率与风险溢价。",
    url: "/valuation",
  },
};

/** 骨架屏：SSR 首屏占位，数据流式到达后替换。 */
function ValuationSkeleton() {
  return (
    <div className="min-h-screen bg-background text-foreground" role="status">
      <span className="sr-only">正在加载指数估值数据</span>
      <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        <div className="h-8 w-40 animate-pulse rounded bg-muted" />
        <div className="mt-2 h-4 w-72 max-w-full animate-pulse rounded bg-muted" />
        <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="h-[156px] animate-pulse rounded-xl border border-border bg-card"
            />
          ))}
        </div>
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
          {Array.from({ length: 2 }).map((_, index) => (
            <div
              key={index}
              className="h-[304px] animate-pulse rounded-xl border border-border bg-card"
            />
          ))}
        </div>
        <div className="mt-6 h-[520px] animate-pulse rounded-xl border border-border bg-card" />
      </div>
    </div>
  );
}

/** 数据层：连接后端读取预计算表；后端不可用时回退示例数据。 */
async function ValuationData() {
  // PPR：显式声明请求期数据，避免构建期预渲染去连后端。
  await connection();
  let rows: IndexQuoteRow[] = [];
  let cards: MarketValuationCard[] = [];
  let proxies: BroadProxyCard[] = [];
  let history: ValuationHistory | null = null;
  let asOf = "";
  try {
    const [indices, overview, historyPayload] = await Promise.all([
      getCachedValuationIndices(1000, DEFAULT_WINDOW, "pe_ttm"),
      getCachedValuationOverview(DEFAULT_WINDOW),
      getCachedValuationHistory(DEFAULT_PROXY, "pe_ttm", DEFAULT_WINDOW),
    ]);
    rows = (indices.data ?? []).map(mapIndexRow).filter((row) => row.index_code);
    asOf = indices.meta?.as_of
      ? String(indices.meta.as_of)
      : rows.find((row) => row.trade_date)?.trade_date || "";
    cards = (overview.data ?? []).map(mapMarketCard);
    const rawProxies = overview.meta?.proxies;
    proxies = Array.isArray(rawProxies)
      ? rawProxies.map((item) => mapBroadProxy(item as Record<string, unknown>))
      : [];
    history = mapValuationHistory(DEFAULT_PROXY, historyPayload, "pe_ttm", DEFAULT_WINDOW);
  } catch {
    // 后端不可用时不伪造数据：页面展示空状态与错误提示
  }
  return (
    <ValuationHome
      rows={rows}
      proxies={proxies}
      boards={cards}
      history={history}
      asOf={asOf}
      total={rows.length}
      defaultWindow={DEFAULT_WINDOW}
    />
  );
}

export default function ValuationPage() {
  return (
    <Suspense fallback={<ValuationSkeleton />}>
      <ValuationData />
    </Suspense>
  );
}
