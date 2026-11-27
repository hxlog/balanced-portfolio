import { describe, expect, it } from "vitest";
import {
  DEMO_BASKET_BADGE,
  basketAccess,
  basketCopyGuard,
  basketOpenLabel,
  basketSaveGuard,
  basketSummaryText,
  basketUpdatedDate,
  basketViewerFromAuth,
  isDemoBasket,
  mergeBasketScopes,
  splitBasketBoard,
  type BasketViewer,
} from "./basket-demo";
import type { BasketRecord } from "./basket-types";

const GUEST: BasketViewer = basketViewerFromAuth({});
const USER: BasketViewer = basketViewerFromAuth({ userId: 7 });
const ADMIN: BasketViewer = basketViewerFromAuth({ userId: 1, isSuperAdmin: true });

function record(overrides: Partial<BasketRecord> & { basket_id: number }): BasketRecord {
  return {
    owner_user_id: null,
    name: "篮子 " + overrides.basket_id,
    description: null,
    method: "risk_parity",
    assets: [],
    params: {},
    latest_result: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-20T00:00:00Z",
    is_demo: false,
    display_order: null,
    ...overrides,
  };
}

const demo = (id: number, order: number | null = null) =>
  record({ basket_id: id, is_demo: true, display_order: order, owner_user_id: 1 });
const own = (id: number, updated = "2026-11-20T00:00:00Z") =>
  record({ basket_id: id, owner_user_id: 7, updated_at: updated });
const others = (id: number) => record({ basket_id: id, owner_user_id: 99 });

describe("isDemoBasket", () => {
  it("only treats explicit true as demo (旧后端缺字段按非示例)", () => {
    expect(isDemoBasket({ is_demo: true })).toBe(true);
    expect(isDemoBasket({ is_demo: false })).toBe(false);
    expect(isDemoBasket({})).toBe(false);
    expect(isDemoBasket(null)).toBe(false);
  });
});

describe("basketAccess", () => {
  it("guest can view demo but not copy/edit and sees read-only badge", () => {
    const access = basketAccess(demo(1), GUEST);
    expect(access.canView).toBe(true);
    expect(access.canCopy).toBe(false);
    expect(access.canEdit).toBe(false);
    expect(access.canDelete).toBe(false);
    expect(access.readOnly).toBe(true);
    expect(access.demoBadge).toBe(DEMO_BASKET_BADGE);
  });

  it("logged-in non-admin can copy demo but not edit it", () => {
    const access = basketAccess(demo(1), USER);
    expect(access.canView).toBe(true);
    expect(access.canCopy).toBe(true);
    expect(access.canEdit).toBe(false);
    expect(access.canDelete).toBe(false);
    expect(access.readOnly).toBe(true);
  });

  it("admin can edit/delete demo", () => {
    const access = basketAccess(demo(1), ADMIN);
    expect(access.canEdit).toBe(true);
    expect(access.canDelete).toBe(true);
    expect(access.readOnly).toBe(false);
  });

  it("owner can edit own non-demo basket", () => {
    const access = basketAccess(own(2), USER);
    expect(access.canView).toBe(true);
    expect(access.canEdit).toBe(true);
    expect(access.canCopy).toBe(true);
    expect(access.canDelete).toBe(true);
    expect(access.readOnly).toBe(false);
    expect(access.demoBadge).toBeNull();
  });

  it("hides other users' private baskets from normal users", () => {
    const access = basketAccess(others(3), USER);
    expect(access.canView).toBe(false);
    expect(access.canEdit).toBe(false);
    expect(access.canCopy).toBe(false);
  });

  it("admin can view/edit other users' baskets", () => {
    const access = basketAccess(others(3), ADMIN);
    expect(access.canView).toBe(true);
    expect(access.canEdit).toBe(true);
  });
});

describe("splitBasketBoard", () => {
  it("splits demo/own, filters invisible rows and sorts each group", () => {
    const board = splitBasketBoard(
      [
        demo(1, 2),
        demo(2, 0),
        own(10, "2026-11-01T00:00:00Z"),
        own(11, "2026-11-25T00:00:00Z"),
        others(12),
      ],
      USER,
    );
    expect(board.demos.map((r) => r.basket_id)).toEqual([2, 1]);
    expect(board.mine.map((r) => r.basket_id)).toEqual([11, 10]);
  });

  it("keeps all visible non-demo rows for admin and sorts demos by display_order", () => {
    const board = splitBasketBoard([demo(1, 1), demo(2, 0), others(3)], ADMIN);
    expect(board.demos.map((r) => r.basket_id)).toEqual([2, 1]);
    expect(board.mine.map((r) => r.basket_id)).toEqual([3]);
  });

  it("tolerates missing display_order and invalid dates", () => {
    const board = splitBasketBoard(
      [
        demo(3, null),
        demo(1, null),
        own(9, "not-a-date"),
      ],
      USER,
    );
    expect(board.demos.map((r) => r.basket_id)).toEqual([1, 3]);
    expect(board.mine).toHaveLength(1);
  });
});

describe("mergeBasketScopes", () => {
  it("dedupes by basket_id and lets the later list win", () => {
    const merged = mergeBasketScopes(
      [demo(1), demo(2)],
      [record({ basket_id: 2, name: "mine-2" }), own(3)],
    );
    expect(merged).toHaveLength(3);
    const hit = merged.find((r) => r.basket_id === 2);
    expect(hit?.name).toBe("mine-2");
    expect(hit?.is_demo).toBe(false);
  });

  it("ignores empty and invalid lists", () => {
    expect(mergeBasketScopes(null, undefined)).toEqual([]);
    expect(mergeBasketScopes([record({ basket_id: Number.NaN })], [])).toEqual([]);
  });
});

describe("basketUpdatedDate / basketSummaryText", () => {
  it("formats updated_at as YYYY-MM-DD", () => {
    expect(basketUpdatedDate(record({ basket_id: 1, updated_at: "2026-11-26T08:30:00Z" }))).toMatch(
      /^2026-11-2[56]$/,
    );
    expect(basketUpdatedDate(record({ basket_id: 1, updated_at: "broken" }))).toBe("—");
  });

  it("summarizes latest_result metrics and treats non-numbers as absent", () => {
    expect(
      basketSummaryText({
        annualized_return: 0.0821,
        max_drawdown: -0.1355,
        sharpe: 1.234,
      }),
    ).toBe("年化 8.21% · 回撤 -13.55% · 夏普 1.23");
    expect(basketSummaryText({ annualized_return: "0.1" })).toBe("");
    expect(basketSummaryText(null)).toBe("");
  });
});

describe("write guards", () => {
  it("requires login before saving", () => {
    const guard = basketSaveGuard(null, GUEST);
    expect(guard.allowed).toBe(false);
    expect(guard.needLogin).toBe(true);
  });

  it("blocks non-admin from saving a demo basket, allows admin", () => {
    expect(basketSaveGuard(demo(1), USER).allowed).toBe(false);
    expect(basketSaveGuard(demo(1), USER).needLogin).toBe(false);
    expect(basketSaveGuard(demo(1), ADMIN).allowed).toBe(true);
  });

  it("allows saving own basket and new basket when logged in", () => {
    expect(basketSaveGuard(own(2), USER).allowed).toBe(true);
    expect(basketSaveGuard(null, USER).allowed).toBe(true);
  });

  it("requires login to copy", () => {
    expect(basketCopyGuard(GUEST).allowed).toBe(false);
    expect(basketCopyGuard(GUEST).needLogin).toBe(true);
    expect(basketCopyGuard(USER).allowed).toBe(true);
  });
});

describe("basketOpenLabel", () => {
  it("shows 查看 for read-only and 打开 for editable", () => {
    expect(basketOpenLabel(basketAccess(demo(1), GUEST))).toBe("查看");
    expect(basketOpenLabel(basketAccess(own(2), USER))).toBe("打开");
  });
});
