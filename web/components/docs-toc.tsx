"use client";

import * as React from "react";

/**
 * 右侧目录: sticky, IntersectionObserver 高亮当前可视节。
 * 与 rehype-slug 同源的 github-slugger 保证 id 一致(由 renderDoc 生成)。
 */
export function DocsToc({ items }: { items: { id: string; title: string }[] }) {
  const [active, setActive] = React.useState<string>(items[0]?.id ?? "");
  React.useEffect(() => {
    if (items.length === 0) return;
    const headings = items
      .map((i) => document.getElementById(i.id))
      .filter((el): el is HTMLElement => !!el);
    if (headings.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-100px 0px -70% 0px", threshold: [0, 1] }
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [items]);

  return (
    <aside className="hidden xl:block w-56 shrink-0 sticky top-24 self-start">
      <nav className="text-sm">
        <div className="font-medium text-muted-foreground mb-2">本页内容</div>
        <ul className="space-y-3 border-border">
          {items.map((it) => (
            <li key={it.id}>
              <a
                href={`#${it.id}`}
                className={
                  "block pl-3 -ml-px border-l-2 transition-colors" +
                  (active === it.id
                    ? "border-primary text-foreground font-medium"
                    : "border-transparent text-muted-foreground hover:text-foreground")
                }
              >
                {it.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
