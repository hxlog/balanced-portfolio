import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";
import GitHubSlugger from "github-slugger";
import * as React from "react";
import { DocsToc } from "@/components/docs-toc";

/**
 * Markdown 文档渲染的共享组件与读取工具(服务端)。
 * page.tsx 用 renderDoc() 取 frontmatter + 正文 + TOC，用 compileMDX 渲染正文。
 */

// ---------------------------------------------------------------------
// Prose: Vercel/OpenAI 风的 typography 容器
// ---------------------------------------------------------------------
export function Prose({ children }: { children: React.ReactNode }) {
  return (
    <article
      className={
        "prose prose-zinc dark:prose-invert max-w-none " +
        "prose-headings:text-foreground prose-headings:font-semibold prose-headings:tracking-tight " +
        "prose-h1:text-4xl prose-h1:mb-4 prose-h1:mt-0 " +
        "prose-h2:mt-12 prose-h2:text-2xl prose-h2:border-b prose-h2:border-border prose-h2:pb-2 prose-h2:scroll-mt-24 " +
        "prose-h3:mt-8 prose-h3:text-xl prose-h3:scroll-mt-24 " +
        "prose-h4:text-base " +
        "prose-p:text-muted-foreground prose-p:leading-relaxed " +
        "prose-li:text-muted-foreground prose-li:leading-relaxed " +
        "prose-a:text-primary prose-a:no-underline hover:prose-a:underline " +
        "prose-strong:text-foreground prose-strong:font-medium " +
        "prose-code:text-foreground prose-code:bg-muted prose-code:rounded prose-code:px-1.5 prose-code:py-0.5 " +
        "prose-code:before:content-none prose-code:after:content-none " +
        "prose-pre:bg-transparent prose-pre:p-0 prose-pre:m-0 prose-pre:border-0 " +
        "prose-th:bg-muted/40 prose-th:font-medium prose-th:text-foreground prose-th:p-3 " +
        "prose-td:text-muted-foreground prose-td:p-3 " +
        "prose-blockquote:border-l-primary prose-blockquote:text-muted-foreground prose-blockquote:not-italic " +
        "prose-hr:border-border"
      }
    >
      {children}
    </article>
  );
}

// MDX 共用组件: 供 docs/methodology 的 compileMDX components 复用。
// 表格的横滚 wrapper 由 rehype 插件(lib/rehype-wrap-tables)在 AST 层包, 不用组件覆盖。
export const mdxComponents = {
  QuadrantGrid,
  Callout,
};

// ---------------------------------------------------------------------
// QuadrantGrid: 达利欧四象限 2x2 彩色卡片
// ---------------------------------------------------------------------
const QUADRANTS: { key: string; label: string; assets: string; tone: string }[] = [
  { key: "overheat", label: "过热（通胀↑ 增长↑）", assets: "国内宽基、商品", tone: "text-up" },
  { key: "stagflation", label: "滞胀（通胀↑ 增长↓）", assets: "黄金、商品、海外宽基、红利", tone: "text-weak" },
  { key: "recovery", label: "复苏（通胀↓ 增长↑）", assets: "国内宽基、商品、红利、债券", tone: "text-primary" },
  { key: "recession", label: "衰退（通胀↓ 增长↓）", assets: "红利、债券、海外宽基、黄金", tone: "text-down" },
];

export function QuadrantGrid() {
  return (
    <div className="grid grid-cols-2 gap-px bg-border rounded-xl overflow-hidden border border-border not-prose my-6">
      {QUADRANTS.map((q) => (
        <div key={q.key} className="bg-card p-6 space-y-2">
          <div className={`text-sm font-medium ${q.tone}`}>{q.label}</div>
          <div className="text-sm text-muted-foreground">{q.assets}</div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------
// Callout: Vercel/OpenAI 风提示框
// ---------------------------------------------------------------------
type CalloutType = "info" | "warning" | "tip";
const CALLOUT_STYLE: Record<CalloutType, { bar: string; title: string }> = {
  info: { bar: "bg-primary", title: "说明" },
  warning: { bar: "bg-amber-500", title: "注意" },
  tip: { bar: "bg-emerald-500", title: "提示" },
};

export function Callout({
  type = "info",
  title,
  children,
}: {
  type?: CalloutType;
  title?: string;
  children?: React.ReactNode;
}) {
  const s = CALLOUT_STYLE[type];
  return (
    <div className="not-prose my-6 flex gap-3 rounded-lg border border-border bg-card p-4">
      <div className={`w-1 shrink-0 rounded ${s.bar}`} />
      <div className="flex-1 text-sm">
        <div className="font-medium text-foreground mb-1">{title ?? s.title}</div>
        <div
          className={
            "prose prose-sm prose-zinc dark:prose-invert max-w-none " +
            "prose-p:mt-0 prose-p:text-muted-foreground prose-p:leading-relaxed " +
            "prose-li:text-muted-foreground " +
            "prose-code:text-foreground prose-code:bg-muted prose-code:rounded prose-code:px-1 prose-code:py-0.5 " +
            "prose-code:before:content-none prose-code:after:content-none " +
            "prose-a:text-primary prose-a:no-underline hover:prose-a:underline"
          }
        >
          {children}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// DocsLayout: 左侧正文 + 右侧 TOC
// ---------------------------------------------------------------------
export function DocsLayout({
  children,
  toc,
}: {
  children: React.ReactNode;
  toc: { id: string; title: string }[];
}) {
  return (
    <div className="mx-auto max-w-screen">
      <div className="relative flex items-start gap-16 mx-auto px-4 sm:px-6 py-8 sm:py-12 max-w-6xl">
        <div className="min-w-0 flex-1 mx-auto">{children}</div>
        {toc.length > 0 && <DocsToc items={toc} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// renderDoc: 读取 content/${file}.mdx, 解析 frontmatter, 生成 TOC
// ---------------------------------------------------------------------
export function renderDoc(file: string): {
  frontmatter: { title?: string; description?: string };
  content: string;
  toc: { id: string; title: string }[];
} {
  const full = path.join(process.cwd(), "content", `${file}.mdx`);
  const raw = fs.readFileSync(full, "utf8");
  const { data, content } = matter(raw);
  const toc = extractToc(content);
  return { frontmatter: data as { title?: string; description?: string }, content, toc };
}

/** 扫描源码中的 `## ` 二级标题(跳过 fenced 代码块), 用 github-slugger 生成 id(与 rehype-slug 一致)。 */
function extractToc(md: string): { id: string; title: string }[] {
  const slugger = new GitHubSlugger();
  const lines = md.split("\n");
  let inFence = false;
  const toc: { id: string; title: string }[] = [];
  for (const line of lines) {
    if (/^\s*(`{3,}|~{3,})/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^##\s+(.+?)\s*$/.exec(line);
    if (m) {
      const title = m[1].replace(/`/g, "").trim();
      toc.push({ id: slugger.slug(title), title });
    }
  }
  return toc;
}
