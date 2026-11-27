import { ValuationDetailShell } from "./ValuationDetailShell";
import { ValuationDetailSkeleton } from "./ValuationDetailSkeleton";

/**
 * /valuation/[code] 路由级 loading：静态壳（容器 + 返回链接）立即出现，
 * 内容区只显示结构一致的骨架，避免整页 loading 与布局跳动（B5）。
 */
export default function ValuationDetailLoading() {
  return (
    <ValuationDetailShell>
      <ValuationDetailSkeleton />
    </ValuationDetailShell>
  );
}
