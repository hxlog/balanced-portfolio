import type { Metadata } from "next";
import type { PluggableList } from "unified";
import { cacheLife } from "next/cache";
import { compileMDX } from "next-mdx-remote/rsc";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeSlug from "rehype-slug";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import rehypePrettyCode from "rehype-pretty-code";
import { rehypeWrapTables } from "@/lib/rehype-wrap-tables";
import { renderDoc, Prose, DocsLayout, mdxComponents } from "@/components/mdx";

const remarkPlugins: PluggableList = [remarkGfm, remarkMath];
const rehypePlugins: PluggableList = [
  rehypeSlug,
  [rehypeAutolinkHeadings, { behavior: "wrap" }],
  [rehypeKatex, { strict: false, throwOnError: false }],
  [
    rehypePrettyCode,
    {
      theme: { light: "github-light", dark: "github-dark" },
      keepBackground: false,
    },
  ],
  rehypeWrapTables,
];

export function generateMetadata(): Metadata {
  const { frontmatter: fm } = renderDoc("methodology");
  return {
    title: fm.title ?? "方法论",
    description: fm.description,
    alternates: { canonical: "/methodology" },
    openGraph: {
      title: fm.title ?? "方法论 | Balanced Portfolio",
      description: fm.description,
      url: "/methodology",
      type: "article",
    },
  };
}

export default async function MethodologyPage() {
  "use cache";
  cacheLife("max");
  const { content, toc } = renderDoc("methodology");
  const { content: rendered } = await compileMDX({
    source: content,
    options: { mdxOptions: { remarkPlugins, rehypePlugins } },
    components: mdxComponents,
  });
  return (
    <DocsLayout toc={toc}>
      <Prose>{rendered}</Prose>
    </DocsLayout>
  );
}
