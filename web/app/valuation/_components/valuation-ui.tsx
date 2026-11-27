"use client";

import {
  useEffect,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { HelpCircle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  percentileLabel,
  percentileTone,
  sumTrackerFundScale,
} from "@/lib/valuation-detail-format";
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
 * 分位语气色 / 标签：阈值与详情页共用 `@/lib/valuation-detail-format` 的唯一实现，
 * 这里只 re-export（历史调用点较多，保留导出名），禁止再复制第二套阈值。
 */
export { percentileLabel, percentileTone };

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

/**
 * 指标说明 `?`：hover/键盘 focus 显示公式/口径 tooltip。
 * 页面内私有原语（不改 web/components/ui 共享组件）。
 */
export function InfoTip({
  label,
  children,
  side = "top",
  className,
}: {
  /** 屏幕阅读器用的说明对象，如「估值分」。 */
  label: string;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label + " 说明"}
          className={cn(
            "inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <HelpCircle className="size-3.5" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side={side}
        sideOffset={6}
        className="max-w-[300px] bg-popover text-[11px] leading-relaxed text-popover-foreground [&>svg]:fill-popover [&>svg]:bg-popover"
      >
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

/** 图表局部 skeleton（只占图表区域，不整页 loading）。 */
export function ChartSkeleton({
  height = 240,
  label = "图表加载中",
  className,
}: {
  height?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("relative overflow-hidden rounded-lg", className)}
      style={{ height }}
    >
      <span className="sr-only">{label}</span>
      <div className="absolute inset-0 animate-pulse rounded-lg border border-border bg-muted/30" />
    </div>
  );
}

/** 数值/统计条局部 skeleton。 */
export function ValueSkeleton({
  lines = 1,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div role="status" aria-live="polite" className={cn("space-y-1.5", className)}>
      <span className="sr-only">数值加载中</span>
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className={cn(
            "h-3 animate-pulse rounded bg-muted",
            index === 0 ? "w-32" : "w-20",
          )}
        />
      ))}
    </div>
  );
}

/** 统一空态卡（成分/行业/基金等「数据建设中」场景共用，禁止显示空表格骨架）。 */
export function DataEmptyState({
  title,
  description,
  icon,
  className,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-10 text-center",
        className,
      )}
    >
      {icon ? <div className="mb-2 text-muted-foreground">{icon}</div> : null}
      <p className="text-sm font-medium">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : null}
    </div>
  );
}

/**
 * 150ms 交叉淡入容器：切换 key 时先把内容淡出到 0.35，再在下一帧淡入，
 * 让「指标/指数本地切换」有明确的过渡反馈（不发起请求、不整页闪）。
 */
export function CrossFade({
  fadeKey,
  children,
  className,
  durationMs = 150,
}: {
  fadeKey: string;
  children: ReactNode;
  className?: string;
  durationMs?: number;
}) {
  const [opacity, setOpacity] = useState(1);
  const frameRef = useRef<number | null>(null);
  const previousKey = useRef(fadeKey);

  useEffect(() => {
    if (previousKey.current === fadeKey) return;
    previousKey.current = fadeKey;
    setOpacity(0);
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = window.requestAnimationFrame(() => setOpacity(1));
    });
    return () => {
      if (frameRef.current != null) window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };
  }, [fadeKey]);

  return (
    <div
      className={cn("transition-opacity ease-out", className)}
      style={{ opacity, transitionDuration: durationMs + "ms" }}
    >
      {children}
    </div>
  );
}

/**
 * 跟踪基金规模合计（元）；无有效规模时返回 null。
 *
 * 口径与明细表 / Top10 条形图一致：`fund_scale ?? aum`（见 lib 的 trackerFundScale），
 * 不再只累加 aum —— 否则「规模合计」与逐行规模相加对不上。
 */
export function sumAum(funds: readonly DetailTrackerFund[]): number | null {
  return sumTrackerFundScale(funds);
}
