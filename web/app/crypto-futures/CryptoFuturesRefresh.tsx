"use client";

import { useEffect, useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const CRYPTO_FUTURES_REFRESH_MS = 60_000;

/**
 * 每 60 秒刷新 RSC 数据。router.refresh() 只重新拉取服务端组件树，
 * 不触发 window.location.reload()，保留当前 ?symbol= 与页面滚动位置。
 */
export function CryptoFuturesAutoRefresh({
  intervalMs = CRYPTO_FUTURES_REFRESH_MS,
}: {
  intervalMs?: number;
}) {
  const router = useRouter();

  useEffect(() => {
    const timer = window.setInterval(() => {
      router.refresh();
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [router, intervalMs]);

  return null;
}

/** 错误态下的「立即重试」，与自动刷新共用同一条 RSC 刷新路径。 */
export function CryptoFuturesRefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      <RefreshCw
        className={cn("mr-1.5 h-3.5 w-3.5", pending && "animate-spin")}
        aria-hidden="true"
      />
      {pending ? "刷新中…" : "立即重试"}
    </Button>
  );
}
