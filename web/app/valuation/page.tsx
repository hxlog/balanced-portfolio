import type { Metadata } from "next";
import { Suspense } from "react";
import { connection } from "next/server";
import { ValuationHome } from "./ValuationHome";
import { getCachedValuationIndices, getCachedValuationOverview } from "@/lib/cached-data";
import { mapIndexRow, mapMarketCard } from "@/lib/valuation-api-map";
import type { IndexQuoteRow, MarketValuationCard } from "@/lib/valuation-types";

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
    <div className="mx-auto max-w-[1240px] px-4 py-8 sm:px-6">
      <div className="h-8 w-48 animate-pulse rounded bg-muted" />
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-28 animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
      <div className="mt-6 h-64 animate-pulse rounded-xl bg-muted" />
    </div>
  );
}

/** 数据层：连接后端读取预计算表；后端不可用时回退示例数据。 */
async function ValuationData() {
  // PPR：显式声明请求期数据，避免构建期预渲染去连后端。
  await connection();
  let rows: IndexQuoteRow[] | undefined;
  let cards: MarketValuationCard[] | undefined;
  let asOf: string | undefined;
  try {
    const [indices, overview] = await Promise.all([
      getCachedValuationIndices(),
      getCachedValuationOverview(),
    ]);
    const mapped = (indices.data ?? []).map(mapIndexRow).filter((row) => row.index_code);
    if (mapped.length > 0) {
      rows = mapped;
      asOf = indices.meta?.as_of ? String(indices.meta.as_of) : undefined;
      const mappedCards = (overview.data ?? []).map(mapMarketCard);
      if (mappedCards.length > 0) cards = mappedCards;
    }
  } catch {
    // 后端不可用/未落库时回退到示例数据，页面仍可访问。
  }
  const broadRows = rows ? rows.filter((row) => row.category === "宽基").slice(0, 8) : undefined;
  return (
    <ValuationHome
      rows={rows}
      cards={cards}
      broadRows={broadRows && broadRows.length > 0 ? broadRows : undefined}
      asOf={asOf}
      isLive={Boolean(rows)}
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
