"use client";

/**
 * 页面顶层模式条 + 居中容器（/dashboard 与 /builder 共用）。
 *
 * 需求（P2-1）：抽 PageModeHeader / 居中容器，整行真正居中；Dashboard 带 TOC 时
 * 与内容列对齐、切换模式不水平跳动。
 *
 * 对齐口径（与 DashboardClient 的内容布局逐像素同源）：
 * - 外层 max-w-[1600px] + px-4 sm:px-6（DashboardClient 用 sm:p-6，故 sm 起两者一致）；
 * - 内容列左侧 = TOC 宽 w-44(11rem) + flex gap-6(1.5rem) = 12.5rem；
 * - 模式条容器在 lg 起加同样的左侧留白，于是它的水平中心 == 内容列中心，
 *   且四象限/一篮子两种模式都保留这段留白 → 切换时不水平跳动。
 */
import type { ReactNode } from "react";
import { ModeSwitch, type BuilderMode } from "./ModeSwitch";
import { cn } from "@/lib/utils";

/** Dashboard 内容列相对外层的左侧偏移：TOC(11rem) + gap(1.5rem)。 */
export const TOC_GUTTER_CLASS = "lg:pl-[12.5rem]";

export function PageModeHeader({
  mode,
  basePath = "/builder",
  onSelect,
  hrefFor,
  trailing,
  className,
  ariaLabel,
}: {
  mode: BuilderMode;
  basePath?: string;
  /** 局部 shell：由调用方接管切换；不传则 Link 软导航。 */
  onSelect?: (next: BuilderMode) => void;
  /** 每个模式的目标 href（如 /builder 篮子页的四象限 pill 指向 /dashboard）。 */
  hrefFor?: (next: BuilderMode) => string;
  /** 右侧附加操作（如「新建篮子」）；绝对定位在右侧，保证 pill 真正居中。 */
  trailing?: ReactNode;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div className={cn("w-full", className)}>
      <div className="relative flex min-h-9 w-full items-center justify-center">
        <ModeSwitch
          mode={mode}
          basePath={basePath}
          onSelect={onSelect}
          hrefFor={hrefFor}
          ariaLabel={ariaLabel}
        />
        {trailing ? (
          <div className="absolute inset-y-0 right-0 hidden items-center gap-2 sm:flex">
            {trailing}
          </div>
        ) : null}
      </div>
      {trailing ? (
        <div className="mt-3 flex justify-center gap-2 sm:hidden">{trailing}</div>
      ) : null}
    </div>
  );
}

/**
 * 居中页面容器：统一 max-width 与左右内边距，可选为 Dashboard 的 TOC 预留左侧留白。
 * 供 page.tsx（服务端）/ 客户端组件复用；不透传任意 DOM 属性，保持窄接口。
 */
export function CenteredPageContainer({
  children,
  reserveToc = false,
  className,
}: {
  children: ReactNode;
  /** Dashboard 专用：lg 起预留 TOC 占位，使模式条/内容列与四象限模式对齐。 */
  reserveToc?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mx-auto w-full max-w-[1600px] px-4 sm:px-6",
        className,
      )}
    >
      <div className={cn(reserveToc && TOC_GUTTER_CLASS)}>{children}</div>
    </div>
  );
}
