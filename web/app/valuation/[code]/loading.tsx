import { ValuationDetailSkeleton } from "./ValuationDetailSkeleton";

/** /valuation/[code] 路由级 loading：直接复用结构一致的骨架屏，避免布局跳动。 */
export default function ValuationDetailLoading() {
  return <ValuationDetailSkeleton />;
}
