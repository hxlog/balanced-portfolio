"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  formatFundingRate,
  formatNotional,
  formatPercent,
  formatPercentile,
  formatPrice,
  formatRatio,
  formatSignedPct,
  formatThousands,
  getLongShortPercentile30,
  sortContractsByOi,
} from "@/lib/crypto-futures-format";
import type {
  CryptoFuturesContract,
  CryptoFuturesPercentile,
} from "@/lib/crypto-futures-types";
import { CryptoFuturesChart } from "./CryptoFuturesChart";

function longShortTone(value: number | null): string {
  if (value == null) return "text-muted-foreground";
  if (value > 1) return "text-success";
  if (value < 1) return "text-destructive";
  return "text-foreground";
}

function basisTone(value: number | null): string {
  if (value == null) return "text-muted-foreground";
  if (value > 0) return "text-up";
  if (value < 0) return "text-down";
  return "text-muted-foreground";
}

/** 30 日分位迷你条：文本已给出百分比，条形只做第二编码。 */
function PercentileBar({ percentile }: { percentile: CryptoFuturesPercentile | null }) {
  if (!percentile || percentile.pct == null) {
    return (
      <div className="mt-1 whitespace-nowrap text-[10px] text-muted-foreground">
        30D 样本积累中
      </div>
    );
  }

  const width = Math.min(100, Math.max(0, percentile.pct));
  return (
    <div
      className="mt-1 flex items-center justify-end gap-1.5"
      title={`30 日分位 ${percentile.pct.toFixed(1)}%（样本 ${percentile.sample_size ?? 0}）`}
    >
      <div
        className="h-1.5 w-12 overflow-hidden rounded-full bg-muted"
        aria-hidden="true"
      >
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
        {formatPercentile(percentile.pct)}
      </span>
    </div>
  );
}

function replaceSymbolInUrl(code: string) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("symbol", code);
  // 不触发 Next 路由跳转，仅让链接可分享；选中态由组件 state 驱动。
  window.history.replaceState(window.history.state, "", url.toString());
}

export function CryptoFuturesBoard({
  contracts,
}: {
  contracts: readonly CryptoFuturesContract[];
}) {
  const searchParams = useSearchParams();
  const symbolParam = searchParams.get("symbol");
  const requestedSymbol = symbolParam ? symbolParam.toUpperCase() : null;
  const [sortKey, setSortKey] = useState<"oi" | "funding" | "ls" | "smart">("oi");
  const sortedContracts = useMemo(() => {
    const base = sortContractsByOi(contracts);
    if (sortKey === "oi") return base;
    const valueOf = (contract: CryptoFuturesContract) => {
      if (sortKey === "funding") return contract.funding_rate ?? -Infinity;
      if (sortKey === "ls") return contract.long_short_ratio ?? -Infinity;
      return contract.smart_money_divergence ?? -Infinity;
    };
    return [...base].sort((a, b) => valueOf(b) - valueOf(a));
  }, [contracts, sortKey]);
  const sortButton = (key: typeof sortKey, label: string) => (
    <button
      type="button"
      onClick={() => setSortKey(key)}
      className={cn("inline-flex items-center gap-1 hover:text-foreground", sortKey === key && "text-foreground")}
      title="点击按该列降序排序"
    >
      {label}
    </button>
  );

  const [selectedCode, setSelectedCode] = useState<string | null>(
    () => requestedSymbol ?? sortedContracts[0]?.contract_code ?? null,
  );

  // 分享链接 / 浏览器前进后退：URL 里的 symbol 变化时同步选中行。
  useEffect(() => {
    if (!requestedSymbol) return;
    if (sortedContracts.some((contract) => contract.contract_code === requestedSymbol)) {
      setSelectedCode(requestedSymbol);
    }
  }, [requestedSymbol, sortedContracts]);

  const selectedContract =
    sortedContracts.find((contract) => contract.contract_code === selectedCode)
    ?? sortedContracts[0]
    ?? null;

  // 首次进入没有 ?symbol 时补上默认合约，确保地址栏始终可分享。
  useEffect(() => {
    if (!selectedContract || typeof window === "undefined") return;
    const current = new URLSearchParams(window.location.search).get("symbol");
    if (
      !current
      || !sortedContracts.some(
        (contract) => contract.contract_code === current.toUpperCase(),
      )
    ) {
      replaceSymbolInUrl(selectedContract.contract_code);
    }
  }, [selectedContract, sortedContracts]);

  const selectContract = (code: string) => {
    setSelectedCode(code);
    replaceSymbolInUrl(code);
  };

  return (
    <div className="grid grid-cols-1 gap-6 min-[1100px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <Card className="min-w-0 overflow-hidden border-border/60 bg-card/60">
        <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/60 px-5 py-4">
          <div className="min-w-0">
            <CardTitle className="text-base">合约监控</CardTitle>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              点击表头排序 · 点击任意行切换右侧序列
            </p>
          </div>
          <Badge variant="outline" className="shrink-0 font-mono tabular-nums">
            {sortedContracts.length} 个
          </Badge>
        </CardHeader>

        <CardContent className="p-0 sm:p-0">
          <div className="max-h-[640px] overflow-auto overscroll-contain">
            <table className="w-full min-w-[660px] border-collapse text-sm">
              <caption className="sr-only">
                合约监控：排名、标记价、OI、资金费率及 30 日分位、多空账户比、大户持仓比、Smart Money 乖离、基差
              </caption>
              <thead className="sticky top-0 z-10 bg-muted/95 backdrop-blur">
                <tr className="border-b border-border text-[11px] text-muted-foreground">
                  <th scope="col" className="w-12 px-3 py-2.5 text-right font-medium">
                    排名
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-left font-medium">
                    合约
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    标记价
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    {sortButton("oi", "OI 名义值")}
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    {sortButton("funding", "资金费率")}
                    <span className="ml-1 font-normal text-muted-foreground/80">30D 分位</span>
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    {sortButton("ls", "多空账户比")}
                    <span className="ml-1 font-normal text-muted-foreground/80">30D 分位</span>
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    大户持仓比
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    {sortButton("smart", "Smart 乖离")}
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    基差
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedContracts.map((contract, index) => {
                  const selected = contract.contract_code === selectedContract?.contract_code;
                  const percentile = getLongShortPercentile30(contract);
                  return (
                    <tr
                      key={contract.contract_code}
                      onClick={() => selectContract(contract.contract_code)}
                      aria-current={selected ? "true" : undefined}
                      className={cn(
                        "cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-muted/40",
                        selected && "bg-primary/5 hover:bg-primary/10",
                      )}
                    >
                      <td
                        className="px-3 py-2.5 text-right font-mono text-xs tabular-nums text-muted-foreground"
                        title="按当前 OI 名义值排序"
                      >
                        {index + 1}
                      </td>
                      <th scope="row" className="px-3 py-2.5 text-left font-normal">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            selectContract(contract.contract_code);
                          }}
                          aria-label={`查看 ${contract.contract_code} 的 24 小时序列`}
                          className="inline-flex items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        >
                          <span
                            className={cn(
                              "h-1.5 w-1.5 shrink-0 rounded-full",
                              selected ? "bg-primary" : "bg-transparent",
                            )}
                            aria-hidden="true"
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium text-foreground">
                              {contract.base_asset}
                            </span>
                            <span className="block font-mono text-[10px] text-muted-foreground">
                              {contract.contract_code}
                            </span>
                          </span>
                        </button>
                      </th>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                        {formatPrice(contract.mark_price)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums" title={formatNotional(contract.oi_notional)}>
                        {formatThousands(contract.oi_notional)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div className={cn("font-mono tabular-nums", contract.funding_rate != null && contract.funding_rate > 0 ? "text-up" : "text-muted-foreground")}>
                          {formatFundingRate(contract.funding_rate)}
                        </div>
                        <div className="mt-1 whitespace-nowrap text-[10px] text-muted-foreground">
                          {contract.funding_percentile_30d == null ? "样本积累中" : "30D 分位 " + contract.funding_percentile_30d.toFixed(0) + "%"}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div
                          className={cn(
                            "font-mono tabular-nums",
                            longShortTone(contract.long_short_ratio),
                          )}
                        >
                          {formatRatio(contract.long_short_ratio, 3)}
                        </div>
                        <PercentileBar percentile={percentile} />
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                        {formatRatio(contract.top_position_ratio ?? null, 3)}
                      </td>
                      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums", (contract.smart_money_divergence ?? 0) > 0 ? "text-up" : "text-muted-foreground")}>
                        {contract.smart_money_divergence == null ? "—" : (contract.smart_money_divergence > 0 ? "+" : "") + contract.smart_money_divergence.toFixed(3)}
                      </td>
                      <td
                        className={cn(
                          "px-3 py-2.5 text-right font-mono tabular-nums",
                          basisTone(contract.basis_pct),
                        )}
                      >
                        {formatSignedPct(contract.basis_pct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 px-5 py-3 text-[11px] text-muted-foreground">
            <span>多空比分位窗口：30 天 · 缺失显示「样本积累中」</span>
            <span className="font-mono tabular-nums">价格 / OI 单位：USDT</span>
          </div>
        </CardContent>
      </Card>

      {selectedContract && (
        <CryptoFuturesChart
          key={selectedContract.contract_code}
          contract={selectedContract}
        />
      )}
    </div>
  );
}
