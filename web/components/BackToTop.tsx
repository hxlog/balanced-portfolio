"use client";

import { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";

/**
 * 回到顶部按钮: 页面滚动超过阈值(默认 400px)时淡入, 点击平滑滚回顶部。
 * 挂在根布局, 全站所有页面生效。使用 IntersectionObserver 不可行的场景
 * (纯文档滚动) 直接监听 window.scroll。
 */
export function BackToTop({ threshold = 400 }: { threshold?: number }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > threshold);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);

  if (!visible) return null;

  return (
    <button
      type="button"
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      aria-label="回到顶部"
      title="回到顶部"
      className="fixed bottom-6 right-6 z-50 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-background/80 backdrop-blur text-muted-foreground shadow-sm transition-all hover:bg-accent hover:text-foreground hover:scale-105"
    >
      <ArrowUp className="h-4 w-4" />
    </button>
  );
}