"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { findPercentile } from "@/lib/valuation-detail-api-map";
import {
  EMPTY_DISPLAY,
  formatNumber,
  formatPlainPct,
  formatSignedPct,
} from "@/lib/valuation-detail-format";
import type {
  DetailPercentile,
  ValuationDetailData,
  ValuationHistoryData,
} from "@/lib/valuation-detail-types";
import {
  isUsablePercentile,
  LevelBadge,
  MetricCard,
  percentileTone,
  Surface,
} from "../_components/valuation-ui";
import { ConstituentsTab } from "./ConstituentsTab";
import { FundsTab } from "./FundsTab";
import { MetricsTab } from "./MetricsTab";

const TAB_KEYS = ["metrics", "constituents", "funds"] as const;
type DetailTab = (typeof TAB_KEYS)[number];

function isDetailTab(value: string | null): value is DetailTab {
  return value === "metrics" || value === "constituents" || value === "funds";
}

/**
 * Tab 状态与 URL 双向保持：
 * - 首屏从 `?tab=` 读取（可分享链接）；
 * - 切换时用 History API `replaceState` 更新 URL，不触发 Next 路由跳转/整页刷新；
 * - `useSearchParams` 在前进/后退或外部导航时把 URL 重新同步回状态。
 */
function useDetailTab(): [DetailTab, (value: string) => void] {
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tabFromUrl: DetailTab = isDetailTab(rawTab) ? rawTab : "metrics";
  const [tab, setTab] = useState<DetailTab>(tabFromUrl);

  useEffect(() => {
    setTab(tabFromUrl);
  }, [tabFromUrl]);

  const changeTab = (value: string) => {
    const next: DetailTab = isDetailTab(value) ? value : "metrics";
    setTab(next);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (next === "metrics") {
      url.searchParams.delete("tab");
    } else {
      url.searchParams.set("tab", next);
    }
    window.history.replaceState(window.history.state, "", url.toString());
  };

  return [tab, changeTab];
}

function percentileHint(
  stats: DetailPercentile | null,
  label: string,
): ReactNode {
  if (!isUsablePercentile(stats)) {
    return <span className="text-muted-foreground">分位样本不足</span>;
  }
  return (
    <span className={percentileTone(stats.pct)}>
      {label}分位 {stats.pct.toFixed(1)}%
    </span>
  );
}

function DetailHeader({ detail }: { detail: ValuationDetailData }) {
  return (
    <header className="mx-auto w-full max-w-[1440px] px-4 pb-4 pt-6 sm:px-6 sm:pt-8 lg:px-8">
      <Link
        href="/valuation"
        className="inline-flex items-center gap-1.5 rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        指数估值
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="font-mono tabular-nums">{detail.index_code}</span>
            <span aria-hidden="true">·</span>
            <span>{detail.index_type}</span>
            {detail.market && (
              <>
                <span aria-hidden="true">·</span>
                <span>{detail.market}</span>
              </>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              {detail.name}
            </h1>
            <LevelBadge level={detail.level_pe} prefix="PE " />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {detail.publisher ?? "发布机构未知"} · 数据截至{" "}
            <span className="tabular-nums text-foreground/80">
              {detail.trade_date ?? EMPTY_DISPLAY}
            </span>
          </p>
        </div>
      </div>
    </header>
  );
}

function ErrorState({ code }: { code: string }) {
  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-[1440px] items-center justify-center px-4 py-16 sm:px-6 lg:px-8">
      <Surface className="w-full max-w-md p-8 text-center">
        <AlertTriangle
          className="mx-auto h-7 w-7 text-warning"
          aria-hidden="true"
        />
        <h1 className="mt-3 text-lg font-semibold tracking-tight">
          估值数据加载失败
        </h1>
        <p className="mt-1 text-xs text-muted-foreground">
          未能读取指数{" "}
          <span className="font-mono tabular-nums text-foreground">{code}</span>{" "}
          的数据。
        </p>
        <div className="mt-5 flex items-center justify-center gap-2">
          <Button asChild size="sm">
            <Link href="/valuation">返回指数估值</Link>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => window.location.reload()}
          >
            重新加载
          </Button>
        </div>
      </Surface>
    </div>
  );
}

export function ValuationDetailClient({
  code,
  detail,
  history,
}: {
  code: string;
  detail: ValuationDetailData | null;
  history: ValuationHistoryData | null;
}) {
  // hooks 必须在条件 return 之前调用；错误态也保持稳定 hook 顺序。
  const [tab, changeTab] = useDetailTab();

  if (!detail) {
    return (
      <div className="min-h-screen bg-background text-foreground">
        <ErrorState code={code} />
      </div>
    );
  }

  const peStats = findPercentile(detail.percentiles, "pe_ttm");
  const pbStats = findPercentile(detail.percentiles, "pb");
  const dividendStats = findPercentile(
    detail.percentiles,
    "dividend_yield_ttm",
  );
  const erpStats = findPercentile(detail.percentiles, "erp");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <DetailHeader detail={detail} />

      <main className="mx-auto w-full max-w-[1440px] px-4 pb-16 sm:px-6 lg:px-8">
        <section
          aria-label="核心估值指标"
          className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4"
        >
          <MetricCard
            label="PE (TTM)"
            value={formatNumber(detail.pe_ttm)}
            hint={percentileHint(peStats, "PE ")}
            percentile={peStats?.pct ?? null}
          />
          <MetricCard
            label="PB"
            value={formatNumber(detail.pb)}
            hint={percentileHint(pbStats, "PB ")}
            percentile={pbStats?.pct ?? null}
          />
          <MetricCard
            label="股息率 TTM"
            value={formatPlainPct(detail.dividend_yield_ttm)}
            hint={percentileHint(dividendStats, "股息率")}
            percentile={dividendStats?.pct ?? null}
          />
          <MetricCard
            label="风险溢价"
            value={formatSignedPct(detail.erp)}
            hint={percentileHint(erpStats, "风险溢价")}
            percentile={erpStats?.pct ?? null}
          />
        </section>

        <Tabs value={tab} onValueChange={changeTab} className="mt-6">
          <div className="overflow-x-auto">
            <TabsList
              className="h-9 w-full justify-start sm:w-auto"
              aria-label="指数详情分区"
            >
              <TabsTrigger value="metrics" className="px-3 text-xs">
                指标
              </TabsTrigger>
              <TabsTrigger value="constituents" className="px-3 text-xs">
                成分
              </TabsTrigger>
              <TabsTrigger value="funds" className="px-3 text-xs">
                ETF
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="metrics" className="mt-4">
            <MetricsTab detail={detail} history={history} />
          </TabsContent>
          <TabsContent value="constituents" className="mt-4">
            <ConstituentsTab detail={detail} />
          </TabsContent>
          <TabsContent value="funds" className="mt-4">
            <FundsTab detail={detail} />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
