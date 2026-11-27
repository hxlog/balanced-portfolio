"use client";

import { RouteError } from "@/components/ui/error-state";

export default function AdminError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <RouteError
      error={error}
      reset={reset}
      title="管理后台加载失败"
      description="页面初始化时发生错误。请重试；若为权限问题，请确认当前账号仍具备管理权限。"
    />
  );
}
