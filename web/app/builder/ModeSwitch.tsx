"use client";

import { useSearchParams } from "next/navigation";
import { LayoutGrid, PieChart } from "lucide-react";
import { cn } from "@/lib/utils";

export type BuilderMode = "quadrant" | "basket";

const MODES: { value: BuilderMode; label: string; icon: typeof LayoutGrid }[] = [
  { value: "quadrant", label: "四象限组合", icon: LayoutGrid },
  { value: "basket", label: "一篮子资产", icon: PieChart },
];

/**
 * /builder 的顶层模式切换（URL 驱动）。
 *
 * 用普通 <a> 整页导航（而不是 router.replace / soft navigation）：
 * - 与 Next.js App Router 的 URL 状态模型一致，返回/刷新/分享都可复原；
 * - 模式是页面级分支（两套独立构建器），整页导航能保证 URL 与渲染树严格一致，
 *   避免 cacheComponents + 多层 Suspense 下 soft navigation 偶发不提交的问题；
 * - 切到四象限时删除 mode/basket，保留 id/copy 等编辑参数。
 */
export function ModeSwitch({ mode }: { mode: BuilderMode }) {
  const searchParams = useSearchParams();

  const hrefFor = (next: BuilderMode) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "basket") params.set("mode", "basket");
    else {
      params.delete("mode");
      params.delete("basket");
    }
    const qs = params.toString();
    return "/builder" + (qs ? "?" + qs : "");
  };

  return (
    <div
      role="tablist"
      aria-label="组合构建模式"
      className="inline-flex items-center rounded-lg border border-border bg-muted/60 p-1"
    >
      {MODES.map(({ value, label, icon: Icon }) => {
        const active = value === mode;
        return (
          <a
            key={value}
            href={hrefFor(value)}
            role="tab"
            aria-selected={active}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            {label}
          </a>
        );
      })}
    </div>
  );
}
