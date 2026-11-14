import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";
import type {
  DetailTrackerFund,
  PercentileSummary,
} from "@/lib/valuation-detail-types";
import type {
  MarketBoard,
  ValuationLevel,
} from "@/lib/valuation-types";

/** 板块卡的固定展示顺序（API 按 board 字母序返回，这里还原产品顺序）。 */
export const BOARD_ORDER: readonly MarketBoard[] = [
  "all",
  "main",
  "chinext",
  "star",
  "bse",
];

export const boardRank = (board: MarketBoard): number => {
  const index = BOARD_ORDER.indexOf(board);
  return index < 0 ? BOARD_ORDER.length : index;
};

/** 统一卡片表面：border + 极浅背景，零投影。 */
export function Surface({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-border bg-card", className)}
      {...props}
    />
  );
}

/**
 * 分位语气色（0~100 口径）：<30 便宜=success，30~70 中性=primary，>70 贵=destructive。
 * 与涨跌方向色 text-up/text-down 解耦。
 */
export function percentileTone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "text-muted-foreground";
  if (value < 30) return "text-success";
  if (value > 70) return "text-destructive";
  return "text-primary";
}

export function percentileLabel(
  value: number | null | undefined,
): "低估" | "中性" | "高估" | null {
  if (value == null || !Number.isFinite(value)) return null;
  if (value < 30) return "低估";
  if (value > 70) return "高估";
  return "中性";
}

const LEVEL_TONE: Record<ValuationLevel, string> = {
  低估: "border-success/25 bg-success/10 text-success",
  中性: "border-primary/20 bg-primary/5 text-primary",
  高估: "border-destructive/25 bg-destructive/10 text-destructive",
};

export function LevelBadge({
  level,
  prefix,
}: {
  level: ValuationLevel | null;
  prefix?: string;
}) {
  if (!level) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        LEVEL_TONE[level],
      )}
    >
      {prefix}
      {level}
    </span>
  );
}

export function isUsablePercentile(
  stats: PercentileSummary | null | undefined,
): stats is PercentileSummary & { pct: number } {
  return Boolean(
    stats &&
      stats.pct != null &&
      Number.isFinite(stats.pct) &&
      stats.sample_size >= 120,
  );
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

/**
 * 全站统一的分位刻度条（本页的 signature 元素）：
 * 三段语义底色 + 当前位置标记，卡片 / 表格 / 详情三处复用。
 */
export function PercentileBar({
  value,
  className,
  barClassName,
  showLabels = true,
  label,
}: {
  value: number | null | undefined;
  className?: string;
  barClassName?: string;
  showLabels?: boolean;
  label?: string;
}) {
  const usable = value != null && Number.isFinite(value);
  const pct = usable ? clampPercent(value) : null;
  const markerTone =
    pct == null
      ? "bg-muted-foreground"
      : pct < 30
        ? "bg-success"
        : pct > 70
          ? "bg-destructive"
          : "bg-primary";
  const tone = percentileTone(value);

  return (
    <div className={cn("min-w-0", className)}>
      <div
        className={cn("relative h-2 rounded-full bg-muted", barClassName)}
        role="img"
        aria-label={
          pct == null
            ? `${label ?? "分位"}样本不足`
            : `${label ?? "分位"} ${pct.toFixed(1)}%`
        }
      >
        <div className="absolute inset-0 overflow-hidden rounded-full">
          <div className="absolute inset-y-0 left-0 w-[30%] bg-success/20" />
          <div className="absolute inset-y-0 left-[30%] w-[40%] bg-primary/15" />
          <div className="absolute inset-y-0 left-[70%] right-0 bg-destructive/20" />
        </div>
        {pct != null && (
          <div
            className={cn(
              "absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-background",
              markerTone,
            )}
            style={{ left: `${pct}%` }}
          />
        )}
      </div>
      {showLabels && (
        <div className="mt-1.5 flex items-baseline justify-between gap-2 text-[10px] leading-none text-muted-foreground">
          <span className="tabular-nums">0</span>
          <span className={cn("truncate tabular-nums", tone)}>
            {pct == null ? "样本不足" : `${label ? `${label} ` : ""}${pct.toFixed(1)}%`}
          </span>
          <span className="tabular-nums">100</span>
        </div>
      )}
    </div>
  );
}

/** 顶部核心指标卡：text-2xl/3xl 数字 + text-xs 标签 + 极细的分位条。 */
export function MetricCard({
  label,
  value,
  hint,
  percentile,
  valueClassName,
}: {
  label: string;
  value: string;
  hint?: ReactNode;
  percentile?: number | null;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1.5 text-2xl font-semibold leading-none tracking-tight tabular-nums sm:text-3xl",
          valueClassName,
        )}
      >
        {value}
      </div>
      {hint && (
        <div className="mt-2 truncate text-[11px] tabular-nums text-muted-foreground">
          {hint}
        </div>
      )}
      {percentile !== undefined && (
        <PercentileBar
          value={percentile}
          showLabels={false}
          barClassName="h-1.5"
          className="mt-2.5"
        />
      )}
    </div>
  );
}

export function SectionHeading({
  id,
  title,
  hint,
  className,
}: {
  id?: string;
  title: string;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1",
        className,
      )}
    >
      <h2 id={id} className="text-sm font-medium tracking-tight">
        {title}
      </h2>
      {hint != null && (
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {hint}
        </span>
      )}
    </div>
  );
}

/** 图表卡：标题 + 一行说明 + 图表本体。 */
export function ChartCard({
  title,
  hint,
  aside,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  hint?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cn("overflow-hidden rounded-xl border border-border bg-card", className)}
    >
      <div className="flex items-start justify-between gap-3 px-4 pt-4 sm:px-5">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium tracking-tight">{title}</h2>
          {hint != null && (
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {hint}
            </p>
          )}
        </div>
        {aside}
      </div>
      <div className={cn("px-3 pb-2 pt-1", bodyClassName)}>{children}</div>
    </section>
  );
}

/** 跟踪基金规模合计（元）；无有效规模时返回 null。 */
export function sumAum(funds: readonly DetailTrackerFund[]): number | null {
  let total: number | null = null;
  for (const fund of funds) {
    if (fund.aum != null && Number.isFinite(fund.aum)) {
      total = (total ?? 0) + fund.aum;
    }
  }
  return total;
}
