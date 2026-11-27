/**
 * 一篮子资产的「示例 / 我的」分组、只读权限与徽标文案（纯函数，便于单测）。
 *
 * 后端契约（ddl 78 + bp_api/baskets.py）：
 * - 每行可能带 `is_demo`（bool）与 `display_order`（int）；旧后端/旧库没有这两列；
 * - 示例篮子匿名可读、登录用户可复制，但只有管理员可编辑（PATCH/DELETE）；
 * - 旧后端匿名列表恒为空，因此所有函数都必须容忍空数组与缺失字段。
 */

import type { BasketRecord } from "./basket-types";

/** 示例篮子的只读徽标文案（需求：示例显示「示例 · 只读 · 可复制」）。 */
export const DEMO_BASKET_BADGE = "示例 · 只读 · 可复制";
/** 示例分组副标题。 */
export const DEMO_BASKET_SECTION_HINT = "匿名可查看；登录后可复制为自己的篮子再编辑";
/** 前端已知的登录态切片（与 web/lib/auth 解耦，便于单测）。 */
export interface BasketViewer {
  userId: number | null;
  isSuperAdmin: boolean;
}

export interface BasketAccess {
  isDemo: boolean;
  /** 匿名/本人/管理员可见。 */
  canView: boolean;
  /** 仅管理员可编辑示例；普通用户只能编辑自己的非示例篮子。 */
  canEdit: boolean;
  /** 复制需要登录；可读者（匿名看示例）在登录后才可复制。 */
  canCopy: boolean;
  canDelete: boolean;
  /** 只读 = 可看但不可编辑（匿名看示例、普通用户看示例）。 */
  readOnly: boolean;
  /** 示例徽标文案；非示例为 null。 */
  demoBadge: string | null;
}

export function basketViewerFromAuth(auth: {
  userId?: number | null;
  isSuperAdmin?: boolean | null;
}): BasketViewer {
  return {
    userId: auth.userId ?? null,
    isSuperAdmin: Boolean(auth.isSuperAdmin),
  };
}

export function isLoggedIn(viewer: BasketViewer): boolean {
  return viewer.userId != null;
}

/** 缺失 is_demo（旧后端）一律按非示例处理，不用 owner_user_id 猜测。 */
export function isDemoBasket(
  record: Pick<BasketRecord, "is_demo"> | null | undefined,
): boolean {
  return record?.is_demo === true;
}

function isOwnBasket(record: BasketRecord, viewer: BasketViewer): boolean {
  return viewer.userId != null && record.owner_user_id === viewer.userId;
}

/**
 * 单条篮子的访问矩阵，与后端 `_can_view` / `_can_edit` 同口径：
 * - 查看：示例对所有人开放；非示例仅 owner 或管理员；
 * - 编辑/删除：管理员任意；普通用户仅自己的非示例篮子；
 * - 复制：必须登录（后端 require_user），且对可读者开放。
 */
export function basketAccess(record: BasketRecord, viewer: BasketViewer): BasketAccess {
  const demo = isDemoBasket(record);
  const own = isOwnBasket(record, viewer);
  const canView = demo || own || viewer.isSuperAdmin;
  const canEdit = viewer.isSuperAdmin || (own && !demo);
  const canCopy = isLoggedIn(viewer) && canView;
  const canDelete = viewer.isSuperAdmin || (own && !demo);
  return {
    isDemo: demo,
    canView,
    canEdit,
    canCopy,
    canDelete,
    readOnly: canView && !canEdit,
    demoBadge: demo ? DEMO_BASKET_BADGE : null,
  };
}

export interface BasketBoard {
  demos: BasketRecord[];
  mine: BasketRecord[];
}

/** 按 basket_id 去重；后出现的覆盖先出现的（scoped 并行请求的合并）。 */
export function mergeBasketScopes(
  demoRows: readonly BasketRecord[] | null | undefined,
  mineRows: readonly BasketRecord[] | null | undefined,
): BasketRecord[] {
  const byId = new Map<number, BasketRecord>();
  for (const list of [demoRows, mineRows]) {
    for (const record of list ?? []) {
      if (!record || !Number.isFinite(record.basket_id)) continue;
      byId.set(record.basket_id, record);
    }
  }
  return [...byId.values()];
}

function updatedAtMs(record: BasketRecord): number {
  const raw = record.updated_at;
  const ms = raw ? Date.parse(raw) : Number.NaN;
  return Number.isFinite(ms) ? ms : 0;
}

function displayOrder(record: BasketRecord): number {
  const raw = record.display_order;
  return typeof raw === "number" && Number.isFinite(raw) ? raw : Number.POSITIVE_INFINITY;
}

/** 示例按 display_order 升序（缺失排最后），再按 basket_id；「我的」按 updated_at 倒序。 */
export function splitBasketBoard(
  records: readonly BasketRecord[],
  viewer: BasketViewer,
): BasketBoard {
  const visible = mergeBasketScopes(records, []).filter(
    (record) => basketAccess(record, viewer).canView,
  );
  const demos = visible
    .filter((record) => isDemoBasket(record))
    .sort(
      (a, b) =>
        displayOrder(a) - displayOrder(b) ||
        a.basket_id - b.basket_id,
    );
  const mine = visible
    .filter((record) => !isDemoBasket(record))
    .sort(
      (a, b) => updatedAtMs(b) - updatedAtMs(a) || a.basket_id - b.basket_id,
    );
  return { demos, mine };
}

/** 列表卡片上的更新日期（YYYY-MM-DD）；解析失败回退「—」。 */
export function basketUpdatedDate(record: BasketRecord): string {
  const raw = record.updated_at;
  if (!raw) return "—";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * 列表卡片摘要：优先读服务端重算后的 latest_result；
 * 缺字段时保持空串，由调用方决定「尚未回测」。
 */
export function basketSummaryText(
  latestResult: Record<string, unknown> | null | undefined,
): string {
  const result = latestResult ?? {};
  const parts: string[] = [];
  const num = (key: string): number | null => {
    const value = result[key];
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  };
  const annualized = num("annualized_return");
  if (annualized != null) parts.push("年化 " + (annualized * 100).toFixed(2) + "%");
  const drawdown = num("max_drawdown");
  if (drawdown != null) parts.push("回撤 " + (drawdown * 100).toFixed(2) + "%");
  const sharpe = num("sharpe");
  if (sharpe != null) parts.push("夏普 " + sharpe.toFixed(2));
  return parts.join(" · ");
}

export interface BasketWriteGuard {
  allowed: boolean;
  /** true = 需要先登录；false = 只是只读（复制后可编辑）。 */
  needLogin: boolean;
  message: string;
}

/** 保存前守卫：游客先登录；非管理员不能保存示例（只能复制）。 */
export function basketSaveGuard(
  record: BasketRecord | null | undefined,
  viewer: BasketViewer,
): BasketWriteGuard {
  if (!isLoggedIn(viewer)) {
    return { allowed: false, needLogin: true, message: "请先登录后保存篮子" };
  }
  if (isDemoBasket(record) && !viewer.isSuperAdmin) {
    return {
      allowed: false,
      needLogin: false,
      message: "示例篮子只读，请先复制为自己的篮子再编辑",
    };
  }
  return { allowed: true, needLogin: false, message: "" };
}

/** 复制前守卫：后端复制接口要求登录。 */
export function basketCopyGuard(viewer: BasketViewer): BasketWriteGuard {
  if (!isLoggedIn(viewer)) {
    return {
      allowed: false,
      needLogin: true,
      message: "请先登录后复制示例篮子",
    };
  }
  return { allowed: true, needLogin: false, message: "" };
}

/** 卡片上可编辑/可删除动作的文案：示例对非管理员只展示「查看」。 */
export function basketOpenLabel(access: BasketAccess): string {
  return access.readOnly ? "查看" : "打开";
}
