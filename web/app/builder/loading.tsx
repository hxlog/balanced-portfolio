import { BuilderPageSkeleton } from "./BuilderSkeleton";

/**
 * /builder 路由级加载骨架：模式条 + 标题 + 步骤条 + 表单卡，与页面真实布局一致，
 * 避免导航瞬间出现全站通用骨架造成布局跳动。
 */
export default function BuilderLoading() {
  return <BuilderPageSkeleton />;
}
