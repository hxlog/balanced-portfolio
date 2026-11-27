"use client";

import { RouteError } from "@/components/ui/error-state";

export default function OtcPricingError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <RouteError
      error={error}
      reset={reset}
      title="场外衍生品定价页加载失败"
      description="定价页初始化时发生错误。请重试；你的簿记数据不会丢失。"
    />
  );
}
