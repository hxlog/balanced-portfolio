"use client";

import { RouteError } from "@/components/ui/error-state";

export default function CryptoError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <RouteError
      error={error}
      reset={reset}
      title="加密货币看板加载失败"
      description="看板数据组装时发生错误。请重试；预计算行情表可能正在重算。"
    />
  );
}
