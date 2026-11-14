"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { LayoutGrid, PieChart } from "lucide-react";
import { cn } from "@/lib/utils";

export type BuilderMode = "quadrant" | "basket";

const MODES: { value: BuilderMode; label: string; icon: typeof LayoutGrid }[] = [
  { value: "quadrant", label: "四象限组合", icon: LayoutGrid },
  { value: "basket", label: "一篮子资产", icon: PieChart },
];

/**
 * /builder 的顶层模式切换。
 *
 * `mode=basket` 写入 URL 以保持可分享；切回四象限时删除该参数，
 * 同时保留 `id` / `copy` 等既有参数，避免打断编辑流。
 */
export function ModeSwitch({ mode }: { mode: BuilderMode }) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const switchTo = (next: BuilderMode) => {
    if (next === mode) return;
    const params = new URLSearchParams(searchParams.toString());
    if (next === "basket") params.set("mode", "basket");
    else params.delete("mode");
    const qs = params.toString();
    router.replace(`/builder${qs ? `?${qs}` : ""}`, { scroll: false });
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
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => switchTo(value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            {label}
          </button>
        );
      })}
    </div>
  );
}
