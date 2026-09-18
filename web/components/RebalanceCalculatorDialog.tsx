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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

/** 调仓计算器的一行: 目标权重来自当日最优化结果, 金额由用户输入。 */
export type CalcRow = {
  key: string;
  name: string;
  /** 当天最优目标权重 (0~1) */
  targetWeight: number;
};

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

/**
 * 调仓计算器: 输入当前持仓金额 → 自动换算为组合权重 → 与当天最优目标权重对比,
 * 输出每只标的的买卖金额(差值)与总调仓金额。
 *
 * 隐私: 全部在浏览器本地计算, 金额不上传、不存储、不进任何请求。
 */
export function RebalanceCalculatorDialog({
  rows,
  asOf,
}: {
  rows: CalcRow[];
  /** 目标权重对应的日期, 用于标题与说明 */
  asOf?: string;
}) {
  const [open, setOpen] = useState(false);
  // key -> 用户输入的金额字符串(保留原始文本以便输入过程中的中间态)
  const [amounts, setAmounts] = useState<Record<string, string>>({});

  const hasNegative = useMemo(
    () => Object.values(amounts).some((v) => v.trim() !== "" && Number(v) < 0),
    [amounts],
  );

  const total = useMemo(
    () =>
      rows.reduce((s, r) => {
        const n = Number(amounts[r.key]);
        return s + (Number.isFinite(n) && n > 0 ? n : 0);
      }, 0),
    [rows, amounts],
  );

  const computed = useMemo(
    () =>
      rows.map((r) => {
        const raw = amounts[r.key];
        const amt = raw != null && raw.trim() !== "" ? Number(raw) : null;
        const valid = amt != null && Number.isFinite(amt) && amt > 0;
        // 当前权重: 金额 / 总金额
        const curWeight = valid && total > 0 ? amt / total : null;
        // 差值: (目标权重 - 当前权重) × 总金额
        const diff =
          curWeight != null ? (r.targetWeight - curWeight) * total : null;
        return { ...r, amt: valid ? amt : null, curWeight, diff };
      }),
    [rows, amounts, total],
  );

  /**
   * 舍入噪声下限: 金额只能取整数元, 每行残差 ≤ 0.5 元 → n 行合计残差下限约 n/2 元。
   * 即使完全按目标权重填, 17 行也会算出「¥2」这种纯噪声 —— 若只在汇总处归零, 明细里
   * 仍会单独显示「买入 ¥2」, 表头与明细再次自相矛盾。故**汇总与逐行共用同一下限**:
   * 低于总额 0.01%(且不足 1 元)的差额一律视为 0。
   */
  const noiseFloor = useMemo(() => Math.max(1, total * 0.0001), [total]);

  const totalTurnover = useMemo(() => {
    const raw = computed.reduce(
      (s, r) => s + (r.diff == null ? 0 : Math.abs(r.diff)),
      0,
    );
    return raw < noiseFloor ? 0 : raw;
  }, [computed, noiseFloor]);

  const anyFilled = computed.some((r) => r.amt != null);

  /**
   * 按目标权重 × 总额度快速填充, 方便用户先看一个示例。
   *
   * 逐行四舍五入会让各行之和偏离总额(如 17 行各差 0.5 元 → 汇总差 2 元), 而换算权重
   * = 金额/总额 是逐行算的, 于是"完全按目标权重填"反而显示出一笔凭空出现的调仓额。
   * 故把舍入残差一次性补到权重最大的那一行(对它的权重影响最小), 使 Σ金额 === 总额。
   * 另: 后端权重按 6 位小数落库, Σtarget_weights 通常为 0.999999 而非严格 1, 逐行
   * 四舍五入后会残留 ≤ 0.5 元的差额 —— 归入同一处残差修正, 一并消掉。
   */
  const fillByTarget = () => {
    const base = total > 0 ? total : 1_000_000;
    const rounded = rows.map((r) => ({ key: r.key, amt: Math.round(r.targetWeight * base) }));
    const drift = Math.round(base) - rounded.reduce((s, x) => s + x.amt, 0);
    if (drift !== 0 && rounded.length > 0) {
      // 权重最大(金额最大)的行吸收残差, 相对误差最小
      let big = 0;
      rounded.forEach((x, i) => {
        if (x.amt > rounded[big].amt) big = i;
      });
      rounded[big].amt = Math.max(0, rounded[big].amt + drift);
    }
    const next: Record<string, string> = {};
    rounded.forEach((x) => {
      next[x.key] = String(x.amt);
    });
    setAmounts(next);
  };

  const reset = () => setAmounts({});

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Calculator className="h-3.5 w-3.5" />
          调仓计算器
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>调仓计算器</DialogTitle>
          <DialogDescription>
            输入当前持仓金额，按{asOf ? ` ${asOf} ` : "当日"}最优化权重自动算出每只标的的买卖金额
            {totalTurnover > 0 && (
              <>
                {" "}
                · 总调仓金额{" "}
                <span className="font-mono font-semibold text-foreground">
                  ¥{yuan(totalTurnover)}
                </span>
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Lock className="h-3.5 w-3.5" />
            全部在您的浏览器本地计算，金额不会上传服务器、不会被存储。
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="gap-1.5" onClick={fillByTarget}>
              按目标权重填充示例
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5"
              onClick={reset}
              disabled={!anyFilled}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              清空
            </Button>
          </div>
        </div>

        <div className="max-h-[52vh] overflow-auto min-w-0">
          <Table className="min-w-[720px]">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-0">标的</TableHead>
                <TableHead className="text-right whitespace-nowrap">
                  最优化权重
                </TableHead>
                <TableHead className="text-right whitespace-nowrap">
                  当前持仓金额（元）
                </TableHead>
                <TableHead className="text-right whitespace-nowrap">
                  自动换算权重
                </TableHead>
                <TableHead className="text-right pr-0 whitespace-nowrap">
                  差值买卖金额
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {computed.map((r) => (
                <TableRow key={r.key}>
                  <TableCell className="pl-0 font-medium">{r.name}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {pct(r.targetWeight)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Input
                      type="number"
                      min={0}
                      step={100}
                      inputMode="numeric"
                      className="ml-auto h-8 w-36 text-right font-mono"
                      placeholder="0"
                      aria-label={`${r.name} 当前持仓金额`}
                      value={amounts[r.key] ?? ""}
                      onChange={(e) =>
                        setAmounts((prev) => ({
                          ...prev,
                          [r.key]: e.target.value,
                        }))
                      }
                    />
                  </TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {r.curWeight != null ? pct(r.curWeight) : "—"}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono pr-0 ${r.diff == null ? "text-muted-foreground" : r.diff > 0 ? "text-up" : r.diff < 0 ? "text-down" : "text-muted-foreground"}`}
                  >
                    {r.diff == null
                      ? "—"
                      : Math.abs(r.diff) < noiseFloor
                        ? "-"
                        : `${r.diff > 0 ? "买入" : "卖出"} ¥${yuan(Math.abs(r.diff))}`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-sm">
          <span className="text-muted-foreground">
            当前组合总金额{" "}
            <span className="font-mono text-foreground">
              ¥{yuan(total)}
            </span>
            {hasNegative && (
              <span className="ml-2 text-destructive">
                金额请填非负数
              </span>
            )}
          </span>
          <span className="text-muted-foreground">
            总调仓金额{" "}
            <span className="font-mono font-semibold text-foreground">
              ¥{yuan(totalTurnover)}
            </span>
            <span className="ml-1 text-xs">
              （买卖绝对值合计，不含交易成本）
            </span>
          </span>
        </div>

        <p className="text-xs text-muted-foreground leading-relaxed">
          说明：换算权重 = 该标的金额 ÷ 组合总金额；差值 = (最优化权重 − 换算权重) × 组合总金额，
          正数=需买入、负数=需卖出。结果仅供执行参考，未计入申赎费、佣金、滑点与最小交易单位，
          实际下单请按券商规则取整。
        </p>
      </DialogContent>
    </Dialog>
  );
}
