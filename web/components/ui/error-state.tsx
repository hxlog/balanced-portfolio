"use client";

import * as React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "./button";

/** 路由级错误边界 UI（各路由 error.tsx 共用），保留导航/页脚，不整页白屏。 */
export function RouteError({
  error,
  reset,
  title = "页面加载失败",
  description,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  title?: string;
  description?: React.ReactNode;
}) {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-24">
      <div role="alert" className="w-full max-w-md space-y-4 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <AlertTriangle className="h-6 w-6" aria-hidden="true" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {description ?? "页面渲染时发生错误。可以重试，或返回首页后再进入。"}
        </p>
        {error?.digest ? (
          <p className="font-mono text-xs text-muted-foreground">错误码 {error.digest}</p>
        ) : null}
        <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
          <Button onClick={() => reset()}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            重试
          </Button>
          <Button asChild variant="outline">
            <a href="/">返回首页</a>
          </Button>
        </div>
      </div>
    </div>
  );
}

/** 页内局部错误（区块请求失败），带重试按钮；不替换整页内容。 */
export function InlineErrorState({
  title = "数据加载失败",
  message,
  onRetry,
  className,
}: {
  title?: string;
  message?: React.ReactNode;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-destructive/20 bg-destructive/5 px-6 py-10 text-center",
        className,
      )}
    >
      <AlertTriangle className="h-5 w-5 text-destructive" aria-hidden="true" />
      <div className="text-sm font-medium text-destructive">{title}</div>
      {message ? (
        <p className="max-w-lg text-xs leading-relaxed text-muted-foreground">{message}</p>
      ) : null}
      {onRetry ? (
        <Button size="sm" variant="outline" className="mt-1" onClick={onRetry}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          重试
        </Button>
      ) : null}
    </div>
  );
}

/** 页内非阻断提示（数据滞后/部分不可用等），使用 warning 语义色。 */
export function InlineNotice({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-warning",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
}
