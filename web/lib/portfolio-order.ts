/**
 * 「调整组合顺序」可排集合的判定 —— 与后端 `PATCH /api/portfolios/order` 同口径。
 *
 * 服务端的权威规则(repositories.reorder_portfolios):
 *   - 示例组合的展示顺序是**全局**的, 只有管理员能改, 否则 403;
 *   - 非示例组合走个人顺序表, 只有 owner 自己可排, 别人的计入 `skipped` 且不落库。
 *
 * 前端必须把这条规则镜像到**可见集合**上, 而不是只镜像到提交那一步: 旧实现把
 * 别人的组合也列进拖拽列表, 拖完保存服务端静默跳过 —— 用户白拖一场还以为是成功了。
 */

export type SortablePortfolio = {
  portfolio_id: number;
  is_demo: boolean;
  owner_user_id?: number | null;
};

export function isSortablePortfolio(
  p: SortablePortfolio,
  opts: { isSuperAdmin: boolean; userId: number | null },
): boolean {
  return p.is_demo ? opts.isSuperAdmin : p.owner_user_id === opts.userId;
}

export function selectSortablePortfolios<T extends SortablePortfolio>(
  portfolios: readonly T[],
  opts: { isSuperAdmin: boolean; userId: number | null },
): T[] {
  return portfolios.filter((p) => isSortablePortfolio(p, opts));
}
