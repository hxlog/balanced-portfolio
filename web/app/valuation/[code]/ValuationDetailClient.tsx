"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { EMPTY_DISPLAY, formatNumber } from "@/lib/valuation-detail-format";
import type {
  ValuationDetailData,
  ValuationHistoryData,
} from "@/lib/valuation-detail-types";
import type { ValuationLevel } from "@/lib/valuation-types";
import { levelClass } from "@/lib/valuation-mock";
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

const LEVEL_BADGE_BG: Record<ValuationLevel, string> = {
  低估: "border-success/30 bg-success/10",
  中性: "border-warning/30 bg-warning/10",
  高估: "border-destructive/30 bg-destructive/10",
};

function LevelBadge({ level }: { level: ValuationLevel | null }) {
  if (!level) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        levelClass(level),
        LEVEL_BADGE_BG[level],
      )}
    >
      PE {level}
    </span>
  );
}

function DetailHeader({ detail }: { detail: ValuationDetailData }) {
  return (
    <header className="border-b border-border/60 bg-card/30">
      <div className="mx-auto w-full max-w-[1240px] px-4 py-7 sm:px-6 sm:py-8">
        <Link
          href="/valuation"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          返回指数估值
        </Link>

        <div className="mt-4 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className="border-primary/30 bg-primary/5 text-primary"
              >
                指数估值
              </Badge>
              <Badge variant="outline">{detail.index_type}</Badge>
              <Badge
                variant="outline"
                className="font-mono tabular-nums"
              >
                {detail.index_code}
              </Badge>
              <LevelBadge level={detail.level_pe} />
            </div>

            <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
              {detail.name}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {detail.publisher ?? "发布机构未知"} · 数据截至{" "}
              <span className="tabular-nums">
                {detail.trade_date ?? EMPTY_DISPLAY}
              </span>
              {detail.pe_ttm != null && (
                <>
                  {" "}
                  · PE (TTM){" "}
                  <span className="font-mono tabular-nums text-foreground">
                    {formatNumber(detail.pe_ttm)}
                  </span>
                </>
              )}
            </p>
          </div>

          <dl className="grid shrink-0 grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4 lg:max-w-lg">
            <div>
              <dt className="text-muted-foreground">基日</dt>
              <dd className="mt-0.5 font-mono tabular-nums">
                {detail.base_date ?? EMPTY_DISPLAY}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">基点</dt>
              <dd className="mt-0.5 font-mono tabular-nums">
                {formatNumber(detail.base_point)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">收益方式</dt>
              <dd className="mt-0.5">{detail.income_method ?? EMPTY_DISPLAY}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">市场</dt>
              <dd className="mt-0.5">{detail.market ?? EMPTY_DISPLAY}</dd>
            </div>
          </dl>
        </div>

        {detail.intro && (
          <p className="mt-4 max-w-4xl text-xs leading-relaxed text-muted-foreground line-clamp-3">
            {detail.intro}
          </p>
        )}
      </div>
    </header>
  );
}

function ErrorState({ code }: { code: string }) {
  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-[1240px] items-center justify-center px-4 py-16 sm:px-6">
      <Card className="w-full max-w-xl">
        <CardContent className="p-8 text-center">
          <AlertTriangle
            className="mx-auto h-8 w-8 text-warning"
            aria-hidden="true"
          />
          <h1 className="mt-4 text-xl font-semibold tracking-tight">
            指数估值数据加载失败
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            未能读取指数{" "}
            <span className="font-mono tabular-nums text-foreground">
              {code}
            </span>{" "}
            的估值数据。可能是后端暂不可用，或该指数尚未入库。
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Button asChild>
              <Link href="/valuation">返回指数估值</Link>
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => window.location.reload()}
            >
              重新加载
            </Button>
          </div>
        </CardContent>
      </Card>
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

  return (
    <div className="min-h-screen bg-background text-foreground">
      <DetailHeader detail={detail} />

      <div className="mx-auto w-full max-w-[1240px] px-4 py-6 sm:px-6 sm:py-8">
        <Tabs value={tab} onValueChange={changeTab}>
          <div className="overflow-x-auto">
            <TabsList
              className="h-10 w-full justify-start sm:w-auto"
              aria-label="指数详情分区"
            >
              <TabsTrigger value="metrics" className="px-4">
                指数指标
              </TabsTrigger>
              <TabsTrigger value="constituents" className="px-4">
                成分与业绩
              </TabsTrigger>
              <TabsTrigger value="funds" className="px-4">
                ETF 资金
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="metrics" className="mt-6">
            <MetricsTab detail={detail} history={history} />
          </TabsContent>
          <TabsContent value="constituents" className="mt-6">
            <ConstituentsTab detail={detail} />
          </TabsContent>
          <TabsContent value="funds" className="mt-6">
            <FundsTab detail={detail} />
          </TabsContent>
        </Tabs>

        <p className="mt-10 text-[11px] leading-relaxed text-muted-foreground">
          口径：PE/PB 分位为近 5 年历史分位，样本不足 120 个交易日时显示「样本不足」；
          股息率、风险溢价与 ROE 为百分数点；跟踪基金规模按最新交易日 aum
          换算为亿元。缺失值显示「—」，不以 0 代替。本页仅供研究，不构成投资建议。
        </p>
      </div>
    </div>
  );
}
