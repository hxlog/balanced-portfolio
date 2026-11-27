/**
 * 页面顶层「四象限 / 一篮子」模式切换的 URL 工具（纯函数，便于单测）。
 *
 * 需求：模式切换不得丢失其它 URL 参数（id / copy / basket 等），且切回四象限时
 * 必须清掉只在 basket 模式有意义的 `mode` / `basket`，避免刷新后落回篮子页。
 */

export type PageMode = "quadrant" | "basket";

/** 从 query 解析模式（缺失/未知值一律按四象限）。 */
export function modeFromQuery(query: string | URLSearchParams): PageMode {
  const get = (key: string): string | null =>
    typeof query === "string"
      ? new URLSearchParams(query).get(key)
      : query.get(key);
  return get("mode") === "basket" ? "basket" : "quadrant";
}

/**
 * 生成切换模式后的 URL（保持其余 query 原样）。
 *
 * @param basePath 页面路径，如 /dashboard、/builder
 * @param currentQuery 当前 query，可带或不带前导 `?`
 */
export function modeHref(
  basePath: string,
  currentQuery: string,
  next: PageMode,
): string {
  const params = new URLSearchParams(currentQuery);
  if (next === "basket") {
    params.set("mode", "basket");
  } else {
    params.delete("mode");
    params.delete("basket");
  }
  const qs = params.toString();
  return basePath + (qs ? "?" + qs : "");
}

/** 供局部 shell 判断「URL 里的模式是否与本地状态一致」。 */
export function isModeUrl(currentQuery: string, mode: PageMode): boolean {
  return modeFromQuery(currentQuery) === mode;
}

/**
 * 模式切换的目标页面。
 *
 * /builder 的四象限模式对游客会渲染「需要登录」门禁（仅白名单可建组合），而 /dashboard
 * 的四象限回测看板游客可读。因此从 /builder 的篮子页点「四象限组合」必须回 /dashboard：
 * 历史缺陷是落到 /builder 的登录提示，用户以为「切回 dashboard 却被要求登录」。
 */
export function modeSwitchPath(fromPath: string, next: PageMode): string {
  if (next === "quadrant" && fromPath === "/builder") return "/dashboard";
  return fromPath;
}

/** 结合目标页面与当前 query 生成模式切换 href（供 Link 的新标签/中键打开）。 */
export function modeSwitchHref(
  fromPath: string,
  currentQuery: string,
  next: PageMode,
): string {
  return modeHref(modeSwitchPath(fromPath, next), currentQuery, next);
}
