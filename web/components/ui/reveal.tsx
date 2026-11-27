import * as React from "react";

import { cn } from "@/lib/utils";

const REVEAL_DURATION_MS = 200;
const REVEAL_STAGGER_MS = 50;

/**
 * 区块入场动画的统一 class：淡入 + 4px 上移，200ms（150–250ms 区间），
 * prefers-reduced-motion 下直接呈现。实现复用 tw-animate-css（globals.css 已 @import），
 * 因此不需要改全局 CSS / 色板。
 *
 * 两种用法：
 * 1. 包裹容器：<Reveal delay={60}>...</Reveal>
 * 2. 已有元素（如 Card）直接拼 class：className={cn("...", REVEAL_CLASS)} style={revealStyle(60)}
 */
const REVEAL_CLASS =
  "animate-in fade-in-0 slide-in-from-bottom-1 fill-mode-both ease-out duration-200 motion-reduce:animate-none";

/** 入场延迟的内联样式；delay<=0 返回 undefined，避免覆盖调用方 style。 */
function revealStyle(delay = 0): React.CSSProperties | undefined {
  return delay > 0 ? { animationDelay: `${delay}ms` } : undefined;
}

type RevealTag = "div" | "section" | "article" | "header" | "aside" | "li" | "ul";

/** 页面区块入场包装；通过 delay 做区块先后顺序（默认 50ms 一档）。 */
export function Reveal({
  as = "div",
  delay = 0,
  className,
  style,
  children,
  ...rest
}: React.HTMLAttributes<HTMLElement> & {
  as?: RevealTag;
  delay?: number;
}) {
  const Comp = as as React.ElementType;
  return (
    <Comp
      className={cn(REVEAL_CLASS, className)}
      style={{ ...revealStyle(delay), ...style }}
      {...rest}
    >
      {children}
    </Comp>
  );
}

/** 区块内第 index 个元素的级联延迟（默认 50ms 一档，封顶 ~250ms）。 */
export function revealDelay(index: number, base = 0, step = REVEAL_STAGGER_MS): number {
  return base + Math.min(index, 5) * step;
}

export { REVEAL_CLASS, REVEAL_DURATION_MS, REVEAL_STAGGER_MS, revealStyle };
