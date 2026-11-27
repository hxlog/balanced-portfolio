import * as React from "react";
import { Inbox } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 统一空态：表格/列表/面板共用，保证文案层级与间距一致。
 * 纯展示组件，无状态；Server / Client 组件都可直接使用。
 */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  compact = false,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  /** 用于 <td> 内嵌的紧凑形态（无外边框、垂直内边距更小）。 */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-1.5 py-8" : "gap-2 rounded-xl border border-dashed border-border bg-card/40 px-6 py-12",
        className,
      )}
    >
      <Icon className={cn("text-muted-foreground/60", compact ? "h-5 w-5" : "h-8 w-8")} />
      <div className={cn("font-medium", compact ? "text-sm text-muted-foreground" : "text-base")}>
        {title}
      </div>
      {description ? (
        <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : null}
      {action}
    </div>
  );
}
