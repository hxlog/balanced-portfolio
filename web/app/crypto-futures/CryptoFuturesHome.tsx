import { Suspense, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Clock,
  Layers,
  Percent,
  Scale,
  TrendingUp,
  Users,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  formatCount,
  formatFundingRate,
  formatNotional,
  formatPercent,
  formatRatio,
  formatShanghaiDateTime,
  formatThousands,
  latestContractCapturedAt,
} from "@/lib/crypto-futures-format";
import type {
  CryptoFuturesContract,
  CryptoFuturesSummary,
} from "@/lib/crypto-futures-types";
import { CryptoFuturesBoard } from "./CryptoFuturesBoard";
import { CryptoFuturesRefreshButton } from "./CryptoFuturesRefresh";

function longShortTone(value: number | null): string {
  if (value == null) return "text-muted-foreground";
  if (value > 1) return "text-success";
  if (value < 1) return "text-destructive";
  return "text-foreground";
}

function SummaryCard({
  label,
  value,
  hint,
  icon,
  valueClassName,
}: {
  label: string;
  value: ReactNode;
  hint: string;
  icon: ReactNode;
  valueClassName?: string;
}) {
  return (
    <Card className="border-border/60 bg-card/60">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className="text-muted-foreground/70" aria-hidden="true">
            {icon}
          </span>
        </div>
        <div
          className={cn(
            "mt-2 font-mono text-2xl font-semibold tracking-tight tabular-nums",
            valueClassName,
          )}
        >
          {value}
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          {hint}
        </p>
      </CardContent>
    </Card>
  );
}

function BoardFallback() {
  return (
    <div className="grid grid-cols-1 gap-6 min-[1100px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="h-[560px] animate-pulse rounded-xl border border-border/60 bg-muted/70" />
      <div className="h-[560px] animate-pulse rounded-xl border border-border/60 bg-muted/70" />
    </div>
  );
}

function ContractsUnavailable() {
  return (
    <Card className="border-destructive/30 bg-destructive/5">
      <CardContent className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center sm:px-6 sm:py-16">
        <AlertTriangle
          className="h-8 w-8 text-destructive"
          aria-hidden="true"
        />
        <div>
          <p className="text-sm font-medium">合约榜数据暂不可用</p>
          <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
            后端接口未响应或数据尚未落库。页面每 60 秒会自动重试，也可以立即重试。
          </p>
        </div>
        <CryptoFuturesRefreshButton />
      </CardContent>
    </Card>
  );
}

function ContractsEmpty() {
  return (
    <Card className="border-dashed border-border/70 bg-card/40">
      <CardContent className="flex flex-col items-center justify-center gap-2 px-6 py-20 text-center sm:px-6 sm:py-20">
        <Layers
          className="h-8 w-8 text-muted-foreground/60"
          aria-hidden="true"
        />
        <p className="text-sm font-medium">暂无合约快照</p>
        <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
          首次部署或采集任务尚未完成时会出现此状态。5 分钟快照落库后，页面会自动刷新。
        </p>
      </CardContent>
    </Card>
  );
}

export function CryptoFuturesHome({
  summary,
  contracts,
  contractsUnavailable,
}: {
  summary: CryptoFuturesSummary | null;
  contracts: readonly CryptoFuturesContract[];
  contractsUnavailable: boolean;
}) {
  const latestCapturedAt =
    summary?.latest_captured_at ?? latestContractCapturedAt(contracts);

  return (
    <div className="space-y-6">
      <section aria-labelledby="crypto-futures-summary-heading">
        <h2 id="crypto-futures-summary-heading" className="sr-only">
          加密合约市场汇总
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 min-[1100px]:grid-cols-5">
          <SummaryCard
            label="总 OI 名义值"
            value={summary ? formatThousands(summary.total_oi_notional) + " USD" : "—"}
            hint={(summary?.contracts ? summary.contracts + " 个合约合计" : "全市场合计") + " · 未平仓名义值"}
            icon={<Activity className="h-4 w-4" />}
          />
          <SummaryCard
            label="加权多空比"
            value={summary ? formatRatio(summary.weighted_long_short_ratio, 2) : "—"}
            hint={summary?.weighted_long_short_note ?? "按 OI 加权 · 全市场多空账户数比"}
            icon={<Scale className="h-4 w-4" />}
            valueClassName={longShortTone(summary?.weighted_long_short_ratio ?? null)}
          />
          <SummaryCard
            label="加权资金费率"
            value={summary ? formatFundingRate(summary.weighted_funding_rate) : "—"}
            hint="当前 8h 费率 · 正=多头付费"
            icon={<Percent className="h-4 w-4" />}
          />
          <SummaryCard
            label="OI 24h 变化"
            value={summary ? formatPercent(summary.total_oi_change_24h_pct) : "—"}
            hint="上升=增仓，下降=减仓"
            icon={<TrendingUp className="h-4 w-4" />}
            valueClassName={longShortTone(summary?.total_oi_change_24h_pct ?? null)}
          />
          <SummaryCard
            label="Smart Money 乖离"
            value={summary && summary.smart_money_divergence != null ? summary.smart_money_divergence.toFixed(3) : "—"}
            hint="大户持仓比 − 全市场账户比 · 正=大户更偏多"
            icon={<Users className="h-4 w-4" />}
            valueClassName={longShortTone(summary?.smart_money_divergence ?? null)}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          {!summary && (
            <span className="mr-auto text-warning">
              汇总接口暂不可用，顶部指标留空；合约榜与图表仍可查看。
            </span>
          )}
          <span className="tabular-nums">
            数据时间：{formatShanghaiDateTime(latestCapturedAt)}（上海时间）
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" aria-hidden="true" />
            5 分钟更新
          </span>
        </div>
      </section>

      {contractsUnavailable ? (
        <ContractsUnavailable />
      ) : contracts.length === 0 ? (
        <ContractsEmpty />
      ) : (
        <Suspense fallback={<BoardFallback />}>
          <CryptoFuturesBoard contracts={contracts} />
        </Suspense>
      )}
    </div>
  );
}
