"use client";

import { RouteError } from "@/components/ui/error-state";

export default function CffexError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <RouteError
      error={error}
      reset={reset}
      title="股指期货看板加载失败"
      description="看板数据组装时发生错误。请重试；若持续失败，行情服务可能正在更新。"
    />
  );
}
