"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { LayoutGrid, PieChart } from "lucide-react";
import { modeHref, type PageMode } from "@/lib/basket-mode";
import { cn } from "@/lib/utils";

/** /builder 与 /dashboard 共用的页面顶层模式（历史命名保留）。 */
export type BuilderMode = PageMode;

const MODES: { value: BuilderMode; label: string; icon: typeof LayoutGrid }[] = [
  { value: "quadrant", label: "四象限组合", icon: LayoutGrid },
  { value: "basket", label: "一篮子资产", icon: PieChart },
];

/**
 * 「四象限组合 / 一篮子资产」pill 切换（URL 驱动）。
 *
 * 速度与正确性（需求：切换响应 ≤300ms）：
 * - 用 next/link + prefetch 预热两种模式的页面，点击不再是 <a> 整页刷新；
 * - 允许调用方传 `onSelect` 做「局部 shell」：拦截默认导航，URL 用原生
 *   history.pushState 同步（Next 把 pushState 集成进 router，useSearchParams 会跟着变，
 *   但不发 RSC 请求），页面壳保持不动、只切换内容区 → 切换即时生效；
 * - 未传 onSelect 时（/builder）退回 Link 软导航，prefetch 已把 RSC 载荷准备好。
 *
 * URL 参数保持：只改 mode / basket，保留 id、copy 等编辑参数；切回四象限时删掉
 * `basket`（它只在 basket 模式有意义）。
 */
export function ModeSwitch({
  mode,
  basePath = "/builder",
  onSelect,
  className,
  ariaLabel = "组合构建模式",
}: {
  mode: BuilderMode;
  /** 复用的页面路径：/builder 或 /dashboard。 */
  basePath?: string;
  /** 局部 shell：由调用方接管切换（应同步更新 URL），不传则走 Link 软导航。 */
  onSelect?: (next: BuilderMode) => void;
  className?: string;
  ariaLabel?: string;
}) {
  const searchParams = useSearchParams();
  const query = searchParams.toString();

  const handleSelect = (
    event: React.MouseEvent<HTMLAnchorElement>,
    next: BuilderMode,
  ) => {
    if (!onSelect) return;
    if (next === mode) {
      event.preventDefault();
      return;
    }
    // 新标签页 / 中键等默认行为交还给浏览器，保证可分享、可多开。
    if (
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      event.button !== 0
    ) {
      return;
    }
    event.preventDefault();
    onSelect(next);
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center rounded-lg border border-border bg-muted/60 p-1",
        className,
      )}
    >
      {MODES.map(({ value, label, icon: Icon }) => {
        const active = value === mode;
        return (
          <Link
            key={value}
            href={modeHref(basePath, query, value)}
            prefetch
            scroll={false}
            role="tab"
            aria-selected={active}
            aria-current={active ? "page" : undefined}
            onClick={(event) => handleSelect(event, value)}
            data-mode={value}
            {...(onSelect ? { "data-local-shell": "true" } : {})}
            className={cn(
              // 两颗 pill 固定等宽（两模式标签均 5 字），切换时模式条宽度/位置不抖动。
              "inline-flex min-w-[7.5rem] items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap sm:min-w-[8.5rem] sm:text-sm",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
            title={active ? undefined : `切换到${label}`}
          >
            <Icon className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            {label}
          </Link>
        );
      })}
    </div>
  );
}
