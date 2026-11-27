/**
 * 一篮子构建器的加载映射：把「已保存 basket 的成分」与「资产池（/api/assets）」合并成
 * 可渲染的 BasketItem，并把保存参数还原成表单值（纯函数，便于单测）。
 *
 * 关键缺陷背景：原 BasketBuilder 只用页面传入的 `initialAssets`（恒为 []）做映射，
 * 资产池从未加载 → 资产池弹窗恒空、已保存篮子的资产名恒为代码。
 * 修复后由调用方并行请求资产池与 basket，再用这里的两步映射补上名称/类别。
 */

import type { Asset } from "./api";
import {
  basketItemFromAsset,
  basketKey,
  type BasketItem,
  type BasketRecord,
} from "./basket-types";

export interface BasketAssetRef {
  symbol: string;
  source: string;
}

/** 资产池按 `symbol@source` 精确匹配。 */
export function findPoolAsset(
  pool: readonly Asset[],
  ref: BasketAssetRef,
): Asset | undefined {
  return pool.find(
    (asset) => asset.symbol === ref.symbol && asset.source === ref.source,
  );
}

/** 资产池有该标的时直接用其名称/类别；否则退化为代码 + 未接入态。 */
export function basketItemFromRecordAsset(
  ref: BasketAssetRef,
  pool: readonly Asset[],
): BasketItem {
  const hit = findPoolAsset(pool, ref);
  if (hit) return basketItemFromAsset(hit);
  return {
    key: basketKey(ref.symbol, ref.source),
    symbol: ref.symbol,
    source: ref.source,
    name: ref.symbol,
    inPool: false,
    hasData: false,
  };
}

/** 已保存篮子的成分 → 构建器条目（保持后端原顺序）。 */
export function basketItemsFromRecord(
  record: Pick<BasketRecord, "assets">,
  pool: readonly Asset[],
): BasketItem[] {
  return (record.assets ?? []).map((ref) =>
    basketItemFromRecordAsset(ref, pool),
  );
}

export interface BasketFormSnapshot {
  lookbackDays: number;
  bandPct: number;
  riskFreePct: number;
  start: string | null;
  end: string | null;
}

export const BASKET_FORM_DEFAULTS: BasketFormSnapshot = {
  lookbackDays: 156,
  bandPct: 5,
  riskFreePct: 0,
  start: null,
  end: null,
};

function finiteOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/**
 * `bp_basket.params` → 构建器表单值。
 * 存储口径：`lookback_days` 为交易日；`rebalance_band` / `risk_free` 为小数，
 * 表单展示为百分数（与保存时 `band = bandPct / 100` 互逆）。
 */
export function basketFormFromRecord(
  record: Pick<BasketRecord, "params">,
  defaults: BasketFormSnapshot = BASKET_FORM_DEFAULTS,
): BasketFormSnapshot {
  const params = (record.params ?? {}) as Record<string, unknown>;
  const start =
    typeof params.start === "string" && params.start !== ""
      ? params.start
      : null;
  const end =
    typeof params.end === "string" && params.end !== "" ? params.end : null;
  return {
    lookbackDays: Math.max(
      2,
      Math.round(finiteOr(params.lookback_days, defaults.lookbackDays)),
    ),
    bandPct: finiteOr(params.rebalance_band, defaults.bandPct / 100) * 100,
    riskFreePct:
      finiteOr(params.risk_free, defaults.riskFreePct / 100) * 100,
    start,
    end,
  };
}
