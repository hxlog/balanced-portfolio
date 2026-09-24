/**
 * 「调整组合顺序」可排判定 —— 必须与后端 `reorder_portfolios` 的权限口径逐条对齐,
 * 否则前端会列出拖不动的项(服务端静默 skip), 用户白拖一场还以为保存成功了。
 */

import { describe, expect, it } from "vitest";
import { isSortablePortfolio, selectSortablePortfolios } from "./portfolio-order";

const DEMO = { portfolio_id: 1, is_demo: true, owner_user_id: null };
const MINE = { portfolio_id: 6, is_demo: false, owner_user_id: 2 };
const OTHERS = { portfolio_id: 5, is_demo: false, owner_user_id: 3 };
const ADMIN_OWN = { portfolio_id: 8, is_demo: false, owner_user_id: 1 };

const ALICE = { isSuperAdmin: false, userId: 2 };
const ADMIN = { isSuperAdmin: true, userId: 1 };

describe("isSortablePortfolio", () => {
  it("普通用户排不了示例组合 —— 那是全局顺序, 服务端会 403", () => {
    expect(isSortablePortfolio(DEMO, ALICE)).toBe(false);
  });

  it("普通用户排不了别人的组合 —— 服务端只会 skipped, 不落库", () => {
    expect(isSortablePortfolio(OTHERS, ALICE)).toBe(false);
  });

  it("普通用户可以排自己的非示例组合", () => {
    expect(isSortablePortfolio(MINE, ALICE)).toBe(true);
  });

  it("管理员可以排示例组合(全局生效)", () => {
    expect(isSortablePortfolio(DEMO, ADMIN)).toBe(true);
  });

  it("管理员排不了别人的自建组合 —— 个人顺序表只存自己的", () => {
    expect(isSortablePortfolio(MINE, ADMIN)).toBe(false);
    expect(isSortablePortfolio(OTHERS, ADMIN)).toBe(false);
  });

  it("管理员自己的自建组合仍可排", () => {
    expect(isSortablePortfolio(ADMIN_OWN, ADMIN)).toBe(true);
  });

  it("未登录(userId=null)时排不了任何非示例组合", () => {
    expect(isSortablePortfolio(MINE, { isSuperAdmin: false, userId: null })).toBe(false);
  });
});

describe("selectSortablePortfolios", () => {
  const ALL = [DEMO, ADMIN_OWN, MINE, OTHERS];

  it("普通用户只看到自己创建的那一个(示例与他人均不可见)", () => {
    expect(selectSortablePortfolios(ALL, ALICE).map((p) => p.portfolio_id)).toEqual([6]);
  });

  it("管理员看到 demo + 自己的, 看不到别人的", () => {
    expect(selectSortablePortfolios(ALL, ADMIN).map((p) => p.portfolio_id)).toEqual([1, 8]);
  });

  it("顺序保持入参顺序 —— 拖拽初始态直接用列表顺序", () => {
    const reversed = [...ALL].reverse();
    expect(selectSortablePortfolios(reversed, ADMIN).map((p) => p.portfolio_id)).toEqual([8, 1]);
  });

  it("空列表不炸", () => {
    expect(selectSortablePortfolios([], ADMIN)).toEqual([]);
  });
});
