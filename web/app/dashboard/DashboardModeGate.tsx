"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ModeSwitch } from "@/app/builder/ModeSwitch";
import DashboardClient from "./DashboardClient";
import { DashboardBaskets } from "./DashboardBaskets";

/**
 * Dashboard 顶层模式：与 /builder 共用同一组「四象限组合 / 一篮子资产」切换按钮。
 * - 四象限组合：原有回测看板（DashboardClient）；
 * - 一篮子资产：已保存篮子的管理列表（DashboardBaskets），不再单独展示在页面顶部。
 * 模式由服务端根据 ?mode= 解析后传入，避免客户端二次判断造成旧内容闪烁。
 */
export function DashboardModeGate({
  mode,
  initialDemo,
}: {
  mode: "quadrant" | "basket";
  initialDemo: Parameters<typeof DashboardClient>[0]["initialDemo"];
}) {
  return (
    <>
      <div className="mx-auto w-full max-w-[1600px] px-4 pt-6 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ModeSwitch mode={mode} basePath="/dashboard" />
          {mode === "basket" ? (
            <Button asChild size="sm" className="h-8">
              <Link href="/builder?mode=basket">新建篮子</Link>
            </Button>
          ) : null}
        </div>
      </div>
      {mode === "basket" ? (
        <div className="mx-auto w-full max-w-[1600px] px-4 pb-12 pt-4 sm:px-6 lg:px-8">
          <DashboardBaskets />
        </div>
      ) : (
        <DashboardClient initialDemo={initialDemo} />
      )}
    </>
  );
}
