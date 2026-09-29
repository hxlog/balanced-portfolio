/** 年度收益表的列推导(纯函数, 供 /dashboard 使用, 单测锁死)。 */

export const ANNUAL_LABELS: Record<string, string> = {
  ytd: "YTD",
  annualized: "年化",
};

/** 年份键形如 `2025`; `ytd` / `annualized` 是特殊列, 不是年份。 */
export const ANNUAL_YEAR_RE = /^\d{4}$/;

export const annualLabel = (key: string): string => ANNUAL_LABELS[key] ?? key;

/**
 * 由 `annual_returns`/`annual_vols` 的键集推出表头顺序: `YTD → 各年降序 → 年化`。
 *
 * **当年不出现在年份列里**: `ytd` 就是「今年那段」的年化值, 后端两者按构造必然相等
 * (见 `bp_api/quant/metrics.py:annual_returns` 的 `out["ytd"]`), 两个都列会得到一列
 * 完全重复的数字 —— 用户要的是 `YTD 2025 2024 2023 年化`, 当年由 YTD 承担。
 *
 * 缺 `ytd`(老结果体)时不做裁剪, 各年原样列出; 没有任何年份键则返回空数组,
 * 调用方据此整块不渲染。
 */
export function annualColumns(
  annual?: Record<string, number | null> | null,
): string[] {
  if (!annual) return [];
  const years = Object.keys(annual)
    .filter((k) => ANNUAL_YEAR_RE.test(k))
    .sort((a, b) => Number(b) - Number(a));
  if (years.length === 0) return [];
  const keys: string[] = [];
  if ("ytd" in annual) {
    keys.push("ytd");
    years.shift(); // 当年已由 YTD 列代表
  }
  keys.push(...years);
  if ("annualized" in annual) keys.push("annualized");
  return keys;
}
