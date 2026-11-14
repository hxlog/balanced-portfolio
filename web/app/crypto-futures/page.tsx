import type { Metadata } from "next";
import { Suspense } from "react";
import { connection } from "next/server";
import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  getCachedCryptoFuturesContracts,
  getCachedCryptoFuturesSummary,
} from "@/lib/crypto-futures-data";
import type { CryptoFuturesContract, CryptoFuturesSummary } from "@/lib/crypto-futures-types";
import { CryptoFuturesHome } from "./CryptoFuturesHome";
import {
  CryptoFuturesAutoRefresh,
  CryptoFuturesRefreshButton,
} from "./CryptoFuturesRefresh";

export const metadata: Metadata = {
  title: "加密合约看板",
  description:
    "USDT 永续合约看板：OI 名义值、加权多空比、主动买卖比与基差，支持合约 24 小时微观序列。",
  alternates: { canonical: "/crypto-futures" },
  openGraph: {
    type: "website",
    title: "加密合约看板 | Balanced Portfolio",
    description:
      "USDT 永续合约看板：OI 名义值、加权多空比、主动买卖比与基差，支持合约 24 小时微观序列。",
    url: "/crypto-futures",
    siteName: "Balanced Portfolio",
  },
};

function CryptoFuturesSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">正在加载加密合约数据…</span>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 min-[1100px]:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className="h-28 animate-pulse rounded-xl border border-border/60 bg-muted/70"
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 min-[1100px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="h-[560px] animate-pulse rounded-xl border border-border/60 bg-muted/70" />
        <div className="h-[560px] animate-pulse rounded-xl border border-border/60 bg-muted/70" />
      </div>
    </div>
  );
}

function CryptoFuturesUnavailable() {
  return (
    <Card className="border-destructive/30 bg-destructive/5">
      <CardContent className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center sm:px-6 sm:py-20">
        <AlertTriangle
          className="h-9 w-9 text-destructive"
          aria-hidden="true"
        />
        <div>
          <p className="text-sm font-medium">加密合约数据暂不可用</p>
          <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
            后端接口未响应或数据尚未落库。页面每 60 秒会自动重试；也可立即重试或稍后刷新。
          </p>
        </div>
        <CryptoFuturesRefreshButton />
      </CardContent>
    </Card>
  );
}

/**
 * 数据层：PPR 下显式声明请求期数据（构建期不连后端）。
 * 两个接口分别 try/catch，任一成功都尽量渲染局部内容；全部失败才显示整页错误态。
 */
async function CryptoFuturesData() {
  await connection();

  const [summaryResult, contractsResult] = await Promise.allSettled([
    getCachedCryptoFuturesSummary(),
    getCachedCryptoFuturesContracts(),
  ]);

  if (summaryResult.status === "rejected") {
    console.error("crypto futures summary fetch failed:", summaryResult.reason);
  }
  if (contractsResult.status === "rejected") {
    console.error("crypto futures contracts fetch failed:", contractsResult.reason);
  }

  const summary: CryptoFuturesSummary | null =
    summaryResult.status === "fulfilled" ? summaryResult.value : null;
  const contracts: CryptoFuturesContract[] | null =
    contractsResult.status === "fulfilled" ? contractsResult.value : null;

  if (!summary && !contracts) {
    return <CryptoFuturesUnavailable />;
  }

  return (
    <CryptoFuturesHome
      summary={summary}
      contracts={contracts ?? []}
      contractsUnavailable={contracts === null}
    />
  );
}

function CryptoFuturesHeader() {
  return (
    <header className="border-b border-border/60 bg-card/30">
      <div className="mx-auto w-full max-w-[1440px] px-4 py-7 sm:px-6 sm:py-8 lg:px-8">
        <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className="border-primary/30 bg-primary/5 text-primary"
              >
                加密合约
              </Badge>
              <span className="text-xs text-muted-foreground">
                Binance USDT 永续 · OI 活跃合约池
              </span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
              加密合约看板
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              跟踪 USDT 永续合约的未平仓名义值、多空账户比、主动买卖比与基差，
              识别杠杆水位与交易情绪的变化。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="tabular-nums">
              5 分钟快照
            </Badge>
            <Badge variant="outline" className="tabular-nums">
              60 秒自动刷新
            </Badge>
          </div>
        </div>
      </div>
    </header>
  );
}

export default function CryptoFuturesPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <CryptoFuturesHeader />
      <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <Suspense fallback={<CryptoFuturesSkeleton />}>
          <CryptoFuturesData />
        </Suspense>
        <CryptoFuturesAutoRefresh />
      </div>
    </div>
  );
}
