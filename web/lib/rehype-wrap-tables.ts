import type { Plugin } from "unified";
import { visit } from "unist-util-visit";

/** rehype 插件: 把 markdown <table> 包进 <div class="overflow-x-auto ..."> 横滚 wrapper。
 *  移动端宽表横滚而非裁切; <table> 保持 display:table 不破坏布局。
 *  AST 层包装, 不用 React 组件覆盖(避免 MDX 组件递归 / Turbopack 兼容问题)。 */
export const rehypeWrapTables: Plugin<[], any> = () => {
  return (tree) => {
    visit(tree, "element", (node: any, index, parent: any) => {
      // 包裹任何未被 div 包裹的 <table>(parent 可能是 root 或非 div 元素)。
      const parentIsDiv =
        parent && parent.type === "element" && parent.tagName === "div";
      if (
        node.tagName === "table" &&
        !parentIsDiv && // 不重复包装(已在 div 内)
        typeof index === "number"
      ) {
        parent.children[index] = {
          type: "element",
          tagName: "div",
          properties: { className: "overflow-x-auto max-w-full" },
          children: [node],
        };
      }
    });
  };
};
