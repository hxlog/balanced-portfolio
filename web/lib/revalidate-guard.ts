/**
 * `/api/revalidate` 的调用许可 —— 决定谁能失效哪个 SSR 缓存 tag。
 *
 * 背景: `CreateAssetDialog` 保存成功后要调 `/api/revalidate` 失效 `/builder` 的
 * `assets` 缓存, 否则刚新增的标的不出现在选择器里(要等 cacheLife("hours") TTL)。
 * 但新增资产的权限是 `require_asset_editor`(超管 **或** `can_manage_assets` 用户),
 * 而旧实现只放行超管 —— 普通资产编辑者保存后缓存失效 403 被静默吞掉, 表现为
 * 「我明明加成功了, 但列表里搜不到」。
 *
 * 故许可口径与**创建资产**对齐: 能建的人就能失效 assets 缓存。
 * 但 tag 收紧 —— 非超管只能失效 `assets`, 不能借这个口子去冲 `crypto` / `demo-result`。
 */

export type RevalidateProfile =
  | { role?: string; can_manage_assets?: boolean }
  | null
  | undefined;

/** 非超管可失效的 tag 白名单。 */
export const ASSET_EDITOR_TAGS: readonly string[] = ["assets"];

export function canRevalidateTag(
  profile: RevalidateProfile,
  tag: string,
): boolean {
  if (profile?.role === "admin") return true;
  return profile?.can_manage_assets === true && ASSET_EDITOR_TAGS.includes(tag);
}
