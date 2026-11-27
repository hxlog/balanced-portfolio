"use client";

/**
 * /valuation 路由错误态（含 /valuation/[code]）。
 *
 * 只覆盖本路由段：展示可读错误 + 重试按钮 + 返回首页入口，
 * 不改变全局视觉（沿用 border/bg-card/语义色与 Button 原语）。
 */
import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ValuationError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("valuation route error:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex min-h-[60vh] w-full max-w-2xl flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="size-8 text-warning" />
        <h1 className="text-lg font-semibold">估值页面暂时加载失败</h1>
        <p className="max-w-md text-sm text-muted-foreground">
          可能是后端接口暂不可用。可重试本页，或先返回指数估值首页查看其他数据。
        </p>
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
          <Button size="sm" onClick={reset}>
            重试
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/valuation">返回指数估值</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
