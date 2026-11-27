import { DashboardPageSkeleton } from "./DashboardSkeleton";

/**
 * /dashboard 路由级加载骨架：任何进入本页的导航先显示与页面同布局的卡片骨架，
 * 而不是全站兜底骨架或纯文本「加载中」（页面内部的数据加载另有局部 skeleton）。
 */
export default function DashboardLoading() {
  return <DashboardPageSkeleton mode="quadrant" />;
}
