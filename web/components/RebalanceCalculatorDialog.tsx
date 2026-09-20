"use client";

import { useMemo, useState } from "react";
import { Calculator, Lock, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useIsMobile } from "@/components/ui/use-mobile";
import {
  LOT_SIZE,
  applyShares,
  computeFees,
  computeLines,
  computeTotals,
  defaultCurrentByPrev,
  targetAmounts,
  type CalcRow,
  type Rates,
} from "@/lib/rebalance-calc";

export type { CalcRow };

function yuan(x: number): string {
  if (!Number.isFinite(x)) return "-";
  return x.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function pct(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "-";
  return `${(x * 100).toFixed(digits)}%`;
}

const AMOUNT_STORAGE_PREFIX = "bp_calc_amount:";

function readStoredAmount(key: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AMOUNT_STORAGE_PREFIX + key);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null; // 隐私模式/存储被禁
  }
}

function writeStoredAmount(key: string, value: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AMOUNT_STORAGE_PREFIX + key, String(value));
  } catch {
    /* 忽略 */
  }
}

/**
 * 调仓计算器: 输入当前持仓与计划持仓金额 → 逐行算出买入/卖出金额与 ETF 可成交份额。
 *
 * 金额算法全部来自 `@/lib/rebalance-calc`(纯函数、已单测), 本组件只负责渲染与输入。
 * 隐私: 金额在浏览器本地计算不上传; 仅按标的代码取最新收盘价(该请求不含金额)。
 */
export function RebalanceCalculatorDialog({
  rows,
  asOf,
  defaultAmount = 1_000_000,
  currentByKey,
  priceByKey,
  rates,
  storageKey,
}: {
  rows: CalcRow[];
  /** 目标权重对应的日期, 用于标题与说明 */
  asOf?: string;
  /** 拟投资金额初值 */
  defaultAmount?: number;
  /** 「当前持仓」的预设值(最近交易日模式传入 actual_holdings 市值) */
  currentByKey?: Record<string, number>;
  /** 每标的清洗收盘价(CNY); 缺失则不显示份额 */
  priceByKey: Record<string, number>;
  /** 组合自身的三项费率 */
  rates: Rates;
  /** localStorage 键(按组合区分) */
  storageKey: string;
}) {
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState<number>(() => readStoredAmount(storageKey) ?? defaultAmount);
  // key -> 用户输入的金额字符串(保留原始文本以便输入过程中的中间态)
  const [current, setCurrent] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<Record<string, string>>({});

  // 打开时(或行集/预设变化时)把「当前持仓」「计划持仓」初始化到默认值
  const initKey = `${rows.map((r) => r.key).join("|")}|${currentByKey ? "actual" : "prev"}|${amount}`;
  const [initSig, setInitSig] = useState<string>("");

  const currentAmounts = useMemo<Record<string, number>>(() => {
    const out: Record<string, number> = {};
    for (const r of rows) {
      const raw = current[r.key];
      out[r.key] = raw == null || raw.trim() === "" ? 0 : Number(raw);
    }
    return out;
  }, [rows, current]);

  const planAmounts = useMemo<Record<string, number>>(() => {
    const out: Record<string, number> = {};
    for (const r of rows) {
      const raw = plan[r.key];
      out[r.key] = raw == null || raw.trim() === "" ? 0 : Number(raw);
    }
    return out;
  }, [rows, plan]);

  const lines = useMemo(
    () => applyShares(computeLines(rows, currentAmounts, planAmounts), rows, priceByKey),
    [rows, currentAmounts, planAmounts, priceByKey],
  );
  const totals = useMemo(() => computeTotals(lines), [lines]);
  const fees = useMemo(
    () => computeFees(totals.buyTotal, totals.sellTotal, rates),
    [totals, rates],
  );
  // 手数合计 = Σ 各行取整后可成交份额 / 100(仅 ETF 有份额)
  const lots = useMemo(() => {
    let buy = 0;
    let sell = 0;
    for (const l of lines) {
      if (l.buyShares != null) buy += l.buyShares;
      if (l.sellShares != null) sell += l.sellShares;
    }
    return { buy: buy / LOT_SIZE, sell: sell / LOT_SIZE };
  }, [lines]);
  const hasAnyPrice = Object.values(priceByKey).some((p) => Number.isFinite(p) && p > 0);
  /**
   * 提示的触发条件不是「一个价都没取到」, 而是「有 ETF 行拿不到价」。
   *
   * `applyShares` 只给 `category === "etf"` 且价格有效的行填份额, 所以份额列缺的成因
   * 精确地是「某个 ETF 行没有价」——它可能是全站取价失败, 也可能只是这一只标的新股/停牌,
   * 而后一种情形下 `hasAnyPrice` 仍为真, 用 `!hasAnyPrice` 当门控会漏掉提示。
   * 反过来, 纯指数/商品组合本就没有份额列, 若按「有行 + 无价」提示, 就会告诉用户
   * 一个从未存在过的东西不可用 —— 故也不能用 `rows.length > 0` 兜底。
   */
  const showShareHint = rows.some(
    (r) => r.category === "etf" && !(Number.isFinite(priceByKey[r.key]) && priceByKey[r.key] > 0),
  );

  const applyDefaults = () => {
    const cur = currentByKey ?? defaultCurrentByPrev(rows, amount);
    const tgt = targetAmounts(rows, amount);
    setCurrent(Object.fromEntries(Object.entries(cur).map(([k, v]) => [k, String(v)])));
    setPlan(Object.fromEntries(rows.map((r) => [r.key, String(tgt[r.key] ?? 0)])));
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        // 打开时按默认值填充一次; 关闭时保留用户输入, 便于再次打开继续编辑
        if (v && initSig !== initKey) {
          applyDefaults();
          setInitSig(initKey);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Calculator className="h-3.5 w-3.5" />
          调仓计算器
        </Button>
      </DialogTrigger>
      <DialogContent className="w-[calc(100vw-2rem)] sm:max-w-5xl max-h-[85vh] flex flex-col gap-3 overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>调仓计算器</DialogTitle>
          <DialogDescription>
            输入当前持仓金额，按{asOf ? ` ${asOf} ` : "当日"}最优化权重自动算出每只标的的买卖金额
            {totals.turnover > 0 && (
              <>
                {" "}
                · 总调仓金额{" "}
                <span className="font-mono font-semibold text-foreground">
                  ¥{yuan(totals.turnover)}
                </span>
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="shrink-0 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Lock className="h-3.5 w-3.5 shrink-0" />
            金额在您的浏览器本地计算，不会上传服务器；仅按标的代码查询最新收盘价以换算份额。
            {showShareHint && (
              <span className="text-xs text-muted-foreground">（未取到价格，份额暂不可用）</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              拟投资金额
              <Input
                type="number"
                min={0}
                step={10_000}
                inputMode="numeric"
                className="h-8 w-32 text-right font-mono"
                value={amount}
                aria-label="拟投资金额"
                onChange={(e) => {
                  const v = Number(e.target.value);
                  const next = Number.isFinite(v) && v > 0 ? v : 0;
                  setAmount(next);
                  writeStoredAmount(storageKey, next);
                  // 金额变化即自动重算计划持仓
                  const tgt = targetAmounts(rows, next);
                  setPlan(Object.fromEntries(rows.map((r) => [r.key, String(tgt[r.key] ?? 0)])));
                }}
              />
              元
            </label>
            <Button variant="ghost" size="sm" className="gap-1.5" onClick={applyDefaults}>
              按目标权重填充
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5"
              onClick={() => {
                setCurrent({});
                setPlan({});
              }}
              disabled={lines.length === 0}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              清空
            </Button>
          </div>
        </div>

        {isMobile ? (
          <div className="flex-1 min-h-0 overflow-auto space-y-2">
            {lines.map((l) => {
              const r = rows.find((x) => x.key === l.key)!;
              return (
                <div key={l.key} className="rounded-lg border border-border p-3 space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium truncate">{r.name}</span>
                    <span className="text-xs text-muted-foreground font-mono shrink-0">
                      {r.symbol}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    最优化权重{" "}
                    <span className="font-mono text-foreground">{pct(l.targetWeight)}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">当前持仓（元）</span>
                      <Input
                        type="number"
                        min={0}
                        step={100}
                        inputMode="numeric"
                        className="h-9 w-full text-right font-mono"
                        placeholder="0"
                        aria-label={`${r.name} 当前持仓金额`}
                        value={current[l.key] ?? ""}
                        onChange={(e) => setCurrent((p) => ({ ...p, [l.key]: e.target.value }))}
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">计划持仓（元）</span>
                      <Input
                        type="number"
                        min={0}
                        step={100}
                        inputMode="numeric"
                        className="h-9 w-full text-right font-mono"
                        placeholder="0"
                        aria-label={`${r.name} 计划持仓金额`}
                        value={plan[l.key] ?? ""}
                        onChange={(e) => setPlan((p) => ({ ...p, [l.key]: e.target.value }))}
                      />
                    </label>
                  </div>
                  <div className="flex items-baseline justify-between gap-2 pt-1 border-t border-border text-sm">
                    {l.buy > 0.5 ? (
                      <span className="font-mono text-success">买入 ¥{yuan(l.buy)}</span>
                    ) : l.sell > 0.5 ? (
                      <span className="font-mono text-warning">卖出 ¥{yuan(l.sell)}</span>
                    ) : (
                      <span className="text-muted-foreground">无需调仓</span>
                    )}
                    {l.buyShares != null && l.buyShares > 0 && (
                      <span
                        className="text-xs text-muted-foreground font-mono"
                        title={`${l.buyShares / LOT_SIZE} 手`}
                      >
                        {l.buyShares.toLocaleString("zh-CN")} 份
                      </span>
                    )}
                    {l.sellShares != null && l.sellShares > 0 && (
                      <span
                        className="text-xs text-muted-foreground font-mono"
                        title={`${l.sellShares / LOT_SIZE} 手`}
                      >
                        {l.sellShares.toLocaleString("zh-CN")} 份
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex-1 min-h-0 overflow-auto">
            <Table className="min-w-[880px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-0">标的</TableHead>
                  <TableHead className="text-right whitespace-nowrap">最优化权重</TableHead>
                  <TableHead className="text-right whitespace-nowrap">当前持仓（元）</TableHead>
                  <TableHead className="text-right whitespace-nowrap">计划持仓（元）</TableHead>
                  <TableHead className="text-right whitespace-nowrap">买入</TableHead>
                  <TableHead className="text-right whitespace-nowrap">卖出</TableHead>
                  {hasAnyPrice && (
                    <TableHead className="text-right pr-0 whitespace-nowrap">份额</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((l) => {
                  const r = rows.find((x) => x.key === l.key)!;
                  return (
                    <TableRow key={l.key}>
                      <TableCell className="pl-0 font-medium">
                        <span className="block truncate max-w-[12rem]">{r.name}</span>
                        <span className="block text-xs text-muted-foreground font-mono">
                          {r.symbol}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono text-muted-foreground">
                        {pct(l.targetWeight)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Input
                          type="number"
                          min={0}
                          step={100}
                          inputMode="numeric"
                          className="ml-auto h-8 w-26 text-right font-mono"
                          placeholder="0"
                          aria-label={`${r.name} 当前持仓金额`}
                          value={current[l.key] ?? ""}
                          onChange={(e) => setCurrent((p) => ({ ...p, [l.key]: e.target.value }))}
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Input
                          type="number"
                          min={0}
                          step={100}
                          inputMode="numeric"
                          className="ml-auto h-8 w-26 text-right font-mono"
                          placeholder="0"
                          aria-label={`${r.name} 计划持仓金额`}
                          value={plan[l.key] ?? ""}
                          onChange={(e) => setPlan((p) => ({ ...p, [l.key]: e.target.value }))}
                        />
                      </TableCell>
                      <TableCell className="text-right font-mono whitespace-nowrap">
                        {l.buy > 0.5 ? (
                          <span className="text-success">买入 ¥{yuan(l.buy)}</span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono whitespace-nowrap">
                        {l.sell > 0.5 ? (
                          <span className="text-warning">卖出 ¥{yuan(l.sell)}</span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      {hasAnyPrice && (
                        <TableCell className="text-right pr-0 font-mono text-xs whitespace-nowrap text-muted-foreground">
                          {l.buyShares ? (
                            <span title={`${l.buyShares / LOT_SIZE} 手`}>
                              买 {l.buyShares.toLocaleString("zh-CN")} 份
                            </span>
                          ) : null}
                          {l.buyShares && l.sellShares ? " / " : ""}
                          {l.sellShares ? (
                            <span title={`${l.sellShares / LOT_SIZE} 手`}>
                              卖 {l.sellShares.toLocaleString("zh-CN")} 份
                            </span>
                          ) : null}
                          {!l.buyShares && !l.sellShares ? "-" : ""}
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        <div className="shrink-0 rounded-lg border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
            <span className="text-muted-foreground">
              交易费用
              <span className="ml-2 text-xs">
                （佣金 {pct(rates.feeRate, 3)} / 滑点 {pct(rates.slippageRate, 3)} / 印花税{" "}
                {pct(rates.stampDutyRate, 3)}，来自组合参数）
              </span>
            </span>
            <span className="font-mono font-semibold text-foreground">
              合计 ¥{yuan(fees.total)}
            </span>
          </div>
          <dl className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs">
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">预计佣金</dt>
              <dd className="font-mono">¥{yuan(fees.commission)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">滑点成本</dt>
              <dd className="font-mono">¥{yuan(fees.slippage)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">印花税</dt>
              <dd className="font-mono">¥{yuan(fees.stampDuty)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">取整剩余现金</dt>
              <dd className="font-mono">¥{yuan(totals.remainder)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">买入手数合计</dt>
              <dd className="font-mono">{lots.buy.toLocaleString("zh-CN")} 手</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">卖出手数合计</dt>
              <dd className="font-mono">{lots.sell.toLocaleString("zh-CN")} 手</dd>
            </div>
          </dl>
        </div>

        <div className="shrink-0 border-t pt-3">
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-muted-foreground">
              买入合计{" "}
              <span className="font-mono text-foreground">¥{yuan(totals.buyTotal)}</span>
              <span className="mx-2">·</span>
              卖出合计{" "}
              <span className="font-mono text-foreground">¥{yuan(totals.sellTotal)}</span>
              <span className="mx-2">·</span>
              总调仓金额{" "}
              <span className="font-mono font-semibold text-foreground">
                ¥{yuan(totals.turnover)}
              </span>
            </span>
            <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
              关闭
            </Button>
          </div>
        </div>

        <p className="shrink-0 text-xs text-muted-foreground leading-relaxed">
          说明：计划持仓 = 最优化权重 × 拟投资金额；买入 = max(0, 计划 − 当前)，卖出 =
          max(0, 当前 − 计划)。ETF 份额按 100 份/手向下取整，未成交的零头计入「取整剩余现金」。
          交易费用按组合自身费率参数计算，与回测成本口径一致（佣金/滑点双边、印花税仅卖出）。
          结果仅供执行参考。
        </p>
      </DialogContent>
    </Dialog>
  );
}
