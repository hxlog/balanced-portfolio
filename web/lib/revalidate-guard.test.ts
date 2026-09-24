/**
 * `/api/revalidate` 的许可判定 —— 与「能否新增资产」同口径。
 *
 * 新增资产的鉴权是 `require_asset_editor`(超管 **或** `bp_user.can_manage_assets`),
 * 但 `/api/revalidate` 旧实现只放行超管。于是普通资产编辑者在 /builder 里新增标的
 * 保存成功、缓存却失效失败(403 被调用方静默吞掉), 表现为「加进去了但列表里搜不到」。
 * 这里把两者对齐, 同时收窄 tag: 非超管只能失效 assets。
 */

import { describe, expect, it } from "vitest";
import { ASSET_EDITOR_TAGS, canRevalidateTag } from "./revalidate-guard";

const ADMIN = { role: "admin", can_manage_assets: true };
const EDITOR = { role: "user", can_manage_assets: true };
const PLAIN = { role: "user", can_manage_assets: false };

describe("canRevalidateTag", () => {
  it("超级管理员可以失效任何 tag", () => {
    for (const tag of ["assets", "crypto", "demo-result"]) {
      expect(canRevalidateTag(ADMIN, tag)).toBe(true);
    }
  });

  it("资产编辑权用户可以失效 assets —— 与「能新增资产」同口径", () => {
    expect(canRevalidateTag(EDITOR, "assets")).toBe(true);
  });

  it("资产编辑权用户不能借道失效 crypto / demo-result", () => {
    expect(canRevalidateTag(EDITOR, "crypto")).toBe(false);
    expect(canRevalidateTag(EDITOR, "demo-result")).toBe(false);
  });

  it("无资产编辑权的普通用户一律拒绝", () => {
    for (const tag of ["assets", "crypto"]) {
      expect(canRevalidateTag(PLAIN, tag)).toBe(false);
    }
  });

  it("未登录(profile=null/undefined)一律拒绝", () => {
    expect(canRevalidateTag(null, "assets")).toBe(false);
    expect(canRevalidateTag(undefined, "assets")).toBe(false);
  });

  it("白名单只含 assets", () => {
    expect([...ASSET_EDITOR_TAGS]).toEqual(["assets"]);
  });
});
