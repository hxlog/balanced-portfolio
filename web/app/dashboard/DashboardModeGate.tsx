"use client";

import { Suspense, useCallback, useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  CenteredPageContainer,
  PageModeHeader,
} from "@/app/builder/PageModeHeader";
import { modeFromQuery, modeHref, type PageMode } from "@/lib/basket-mode";
import DashboardClient from "./DashboardClient";
import { DashboardBaskets } from "./DashboardBaskets";
import {
  BasketBoardSkeleton,
  DashboardContentSkeleton,
} from "./DashboardSkeleton";

/**
 * Dashboard 顶层模式 shell：与 /builder 共用同一组「四象限组合 / 一篮子资产」切换按钮。
 *
 * 局部 shell（需求 P2-1：切换响应 ≤300ms）：
 * - 模式条状态同步更新 → pill 立刻高亮；
 * - 内容区用 React transition 低优先级切换，旧内容保留到新内容可渲染（避免空窗）；
 * - URL 用原生 history.pushState 更新（Next 会同步 useSearchParams），不发 RSC 请求；
 * - Link prefetch 仍然预热两种模式的页面，中键/新标签打开依旧是完整、可分享的 URL。
 *
 * 布局对齐（需求 P2-1）：四象限模式内容列左侧有 TOC，模式条容器因此预留同样的
 * TOC 留白；一篮子模式也保留该留白，切换时模式条不水平跳动。
 *
 * 服务端 mode 参数仍决定首屏渲染与 demo 数据预取；客户端状态只负责后续切换。
 */
export function DashboardModeGate({
  mode: initialMode,
  initialDemo,
}: {
  mode: PageMode;
  initialDemo: Parameters<typeof DashboardClient>[0]["initialDemo"];
}) {
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  // 模式条（同步、即时反馈）与内容区（transition、低优先级）分开，让 pill 永远先响应。
  const [mode, setMode] = useState<PageMode>(initialMode);
  const [contentMode, setContentMode] = useState<PageMode>(initialMode);
  const [, startTransition] = useTransition();

  // URL → 本地状态：浏览器前进/后退、外部链接、以及我们自己的 pushState 后都走这里。
  useEffect(() => {
    const next = modeFromQuery(searchParams);
    setMode(next);
    startTransition(() => setContentMode(next));
  }, [searchParams]);

  const handleSelect = useCallback(
    (next: PageMode) => {
      if (next === mode) return;
      setMode(next);
      startTransition(() => setContentMode(next));
      if (typeof window !== "undefined") {
        window.history.pushState(null, "", modeHref("/dashboard", query, next));
      }
    },
    [mode, query],
  );

  return (
    <>
      <CenteredPageContainer reserveToc className="pt-6">
        <PageModeHeader
          mode={mode}
          basePath="/dashboard"
          onSelect={handleSelect}
          ariaLabel="Dashboard 视图模式"
          trailing={
            mode === "basket" ? (
              <Button asChild size="sm" className="h-8">
                <Link href="/builder?mode=basket" prefetch>
                  新建篮子
                </Link>
              </Button>
            ) : null
          }
        />
      </CenteredPageContainer>

      <Suspense
        fallback={
          contentMode === "basket" ? (
            <CenteredPageContainer reserveToc className="pt-4 pb-12">
              <BasketBoardSkeleton />
            </CenteredPageContainer>
          ) : (
            <DashboardContentSkeleton />
          )
        }
      >
        {contentMode === "basket" ? (
          <CenteredPageContainer reserveToc className="pt-4 pb-12">
            <DashboardBaskets />
          </CenteredPageContainer>
        ) : (
          <DashboardClient initialDemo={initialDemo} />
        )}
      </Suspense>
    </>
  );
}
