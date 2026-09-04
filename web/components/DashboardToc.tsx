"use client";

import { useEffect, useState } from "react";

export type TocItem = { id: string; label: string };

/**
 * 竖向 Table of Contents(模仿 Next.js / OpenAI 文档侧栏):
 * - 桌面端 sticky 左侧栏, 点击平滑滚动到对应区块并高亮当前区块;
 * - 用 IntersectionObserver 侦测当前阅读位置, 无手动高亮状态。
 * 区块须有匹配的 id 且带 scroll-mt 以避开 sticky 顶栏。
 */
export function DashboardToc({ items }: { items: TocItem[] }) {
  const [active, setActive] = useState<string>("");

  useEffect(() => {
    const els = items
      .map((it) => document.getElementById(it.id))
      .filter((el): el is HTMLElement => el != null);
    if (els.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive(entry.target.id);
          }
        }
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 },
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  const jump = (id: string) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <nav
      aria-label="目录"
      className="hidden lg:block sticky top-24 self-start w-44 shrink-0 text-sm"
    >
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2 px-2">
        本页目录
      </div>
      <ul className="space-y-0.5 border-l border-border">
        {items.map((it) => {
          const isActive = active === it.id;
          return (
            <li key={it.id}>
              <button
                type="button"
                onClick={() => jump(it.id)}
                className={`w-full text-left text-[13px] leading-6 py-1 px-3 rounded-md cursor-pointer transition-colors ${
                  isActive
                    ? "text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/60"
                }`}
              >
                {it.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}