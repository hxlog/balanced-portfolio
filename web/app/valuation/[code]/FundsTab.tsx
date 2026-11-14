"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  EMPTY_DISPLAY,
  formatAumYi,
  formatNumber,
} from "@/lib/valuation-detail-format";
import type {
  DetailTrackerFund,
  ValuationDetailData,
} from "@/lib/valuation-detail-types";

function sumAum(funds: readonly DetailTrackerFund[]): number | null {
  let total: number | null = null;
  for (const fund of funds) {
    if (fund.aum != null && Number.isFinite(fund.aum)) {
      total = (total ?? 0) + fund.aum;
    }
  }
  return total;
}

export function FundsTab({ detail }: { detail: ValuationDetailData }) {
  const funds = detail.tracker_funds;
  const total = sumAum(funds);
  const asOf =
    funds.find((fund) => fund.trade_date)?.trade_date ?? detail.trade_date;

  return (
    <div className="space-y-6">
      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-end sm:justify-between sm:p-6">
          <div>
            <div className="text-xs text-muted-foreground">
              跟踪基金合计规模
            </div>
            <div className="mt-1 flex flex-wrap items-baseline gap-1.5">
              <span className="text-3xl font-semibold tabular-nums tracking-tight">
                {formatAumYi(total)}
              </span>
              <span className="text-sm text-muted-foreground">亿元</span>
            </div>
          </div>
          <dl className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
            <div>
              <dt>跟踪基金</dt>
              <dd className="mt-0.5 font-mono tabular-nums text-foreground">
                {formatNumber(funds.length, 0)} 只
              </dd>
            </div>
            <div>
              <dt>数据截至</dt>
              <dd className="mt-0.5 font-mono tabular-nums text-foreground">
                {asOf ?? EMPTY_DISPLAY}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">跟踪基金明细</CardTitle>
          <p className="text-xs text-muted-foreground">
            规模按最新交易日 aum 汇总并换算为亿元；缺失显示「—」。
          </p>
        </CardHeader>
        <CardContent className="pt-2">
          {funds.length > 0 ? (
            <div className="overflow-x-auto overscroll-x-contain rounded-lg border border-border">
              <table className="w-full min-w-[760px] border-collapse text-sm">
                <caption className="sr-only">
                  跟踪该指数的基金列表，含代码、名称、基金公司、风险等级与规模
                </caption>
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      基金代码
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      基金名称
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      基金公司
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-left font-medium"
                    >
                      风险等级
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-right font-medium"
                    >
                      规模（亿元）
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {funds.map((fund) => (
                    <tr
                      key={fund.fund_code}
                      className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                    >
                      <td className="px-4 py-3 font-mono text-xs tabular-nums">
                        {fund.fund_code}
                      </td>
                      <td className="px-4 py-3 font-medium">{fund.name}</td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {fund.company_name ?? EMPTY_DISPLAY}
                      </td>
                      <td className="px-4 py-3">
                        {fund.risk_grade ? (
                          <span className="inline-flex items-center rounded border border-border px-1.5 py-0.5 text-[11px] tabular-nums text-muted-foreground">
                            {fund.risk_grade}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">
                            {EMPTY_DISPLAY}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">
                        {formatAumYi(fund.aum)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-10 text-center">
              <p className="text-sm font-medium">暂无跟踪基金数据</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                后端尚未落库该指数的跟踪 ETF/联接基金快照。
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
