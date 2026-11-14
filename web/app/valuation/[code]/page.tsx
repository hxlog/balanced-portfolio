import type { Metadata } from "next";
import { Suspense } from "react";
import { connection } from "next/server";
import {
  findPercentile,
  mapValuationDetail,
  mapValuationHistory,
} from "@/lib/valuation-detail-api-map";
import {
  getCachedValuationDetail,
  getCachedValuationHistory,
} from "@/lib/valuation-detail-data";
import type {
  ValuationDetailData,
  ValuationHistoryData,
} from "@/lib/valuation-detail-types";
import { ValuationDetailClient } from "./ValuationDetailClient";
import { ValuationDetailSkeleton } from "./ValuationDetailSkeleton";

interface ValuationDetailPageProps {
  params: Promise<{ code: string }>;
}

/** 动态 metadata：指数名 + PE + PE 分位；后端不可用时回退通用标题。 */
export async function generateMetadata({
  params,
}: ValuationDetailPageProps): Promise<Metadata> {
  const { code } = await params;

  try {
    const response = await getCachedValuationDetail(code);
    const detail = mapValuationDetail(response.data);
    if (!detail) throw new Error("invalid valuation detail payload");

    const stats = findPercentile(detail.percentiles, "pe_ttm");
    const peText =
      detail.pe_ttm != null ? `PE ${detail.pe_ttm.toFixed(2)}` : "PE —";
    const pctText =
      stats?.pct != null && stats.sample_size >= 120
        ? `PE 分位 ${stats.pct.toFixed(2)}%`
        : "PE 分位样本不足";
    const title = `${detail.name}（${detail.index_code}）估值 — ${peText} · ${pctText}`;
    const description = `${detail.name} 指数估值详情：PE/PB、股息率、风险溢价与近 5 年历史分位。${peText}，${pctText}。数据截至 ${detail.trade_date ?? "—"}。`;
    const canonical = `/valuation/${encodeURIComponent(detail.index_code)}`;

    return {
      title,
      description,
      alternates: { canonical },
      openGraph: {
        title: `${title} | Balanced Portfolio`,
        description,
        url: canonical,
        type: "article",
      },
    };
  } catch {
    const canonical = `/valuation/${encodeURIComponent(code)}`;
    return {
      title: `指数估值详情（${code}）`,
      description: `指数 ${code} 的 PE/PB、股息率与历史分位详情。`,
      alternates: { canonical },
      openGraph: {
        title: "指数估值详情 | Balanced Portfolio",
        description: `指数 ${code} 的 PE/PB、股息率与历史分位详情。`,
        url: canonical,
        type: "article",
      },
    };
  }
}

/** 数据层：显式请求期取数；任一接口失败时交给客户端展示错误态/空态。 */
async function ValuationDetailData({ code }: { code: string }) {
  // PPR：显式声明请求期数据，避免构建期预渲染去连后端。
  await connection();

  let detail: ValuationDetailData | null = null;
  let history: ValuationHistoryData | null = null;

  try {
    const [detailResult, historyResult] = await Promise.allSettled([
      getCachedValuationDetail(code),
      getCachedValuationHistory(code),
    ]);

    if (detailResult.status === "fulfilled") {
      detail = mapValuationDetail(detailResult.value.data);
    } else {
      console.error("valuation detail SSR fetch failed:", detailResult.reason);
    }

    if (historyResult.status === "fulfilled") {
      history = mapValuationHistory(historyResult.value.data);
    } else {
      console.error("valuation history SSR fetch failed:", historyResult.reason);
    }
  } catch (error) {
    console.error("valuation detail SSR failed:", error);
  }

  return (
    <ValuationDetailClient code={code} detail={detail} history={history} />
  );
}

export default async function ValuationDetailPage({
  params,
}: ValuationDetailPageProps) {
  const { code } = await params;

  return (
    <Suspense fallback={<ValuationDetailSkeleton />}>
      <ValuationDetailData code={code} />
    </Suspense>
  );
}
