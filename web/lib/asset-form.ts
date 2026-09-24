/**
 * 「新增/更新投资品」表单的共享逻辑 —— /admin/assets 与 /builder 的新增资产对话框
 * 必须完全同口径, 因此口径只在这里定义一次:
 *   - buildExtraParams: 「测试什么就保存什么」, probe 与落库共用同一份 extra_params;
 *   - ASSET_CREATE_DEFAULTS / validateAssetInput: 表单初值与校验;
 *   - ProbeFailure: probe 结论分类, 决定能否走「仍要保存」。
 */

import type { Asset } from "./api";

export interface AssetFormState {
  symbol: string;
  source: string;
  name: string;
  category: string;
  start_date: string;
  adjust: string;
}

export const ASSET_CREATE_DEFAULTS: AssetFormState = {
  symbol: "",
  source: "cn_index_em",
  name: "",
  category: "index",
  start_date: "2017-01-01",
  adjust: "hfq",
};

/**
 * 构造与保存落库口径一致的 extra_params(probe 透传用,「测试什么就保存什么」):
 * ETF 携带所选复权(落库为 extra_params.adjust), 中债国债固定财富口径(ingest 默认), 其余源为空。
 */
export function buildExtraParams(
  source: string,
  category?: string | null,
  adjust?: string | null,
): { adjust?: string; indicator?: string } {
  if (category === "etf" && adjust) return { adjust };
  if (source === "bond_csi_treasury") return { indicator: "财富" };
  return {};
}

/** 保存前的本地校验: 返回第一条错误文案, 全部通过返回 null。 */
export function validateAssetInput(form: AssetFormState): string | null {
  if (!form.source) return "请选择数据源";
  if (!form.symbol.trim()) return "请填写代码 (symbol)";
  if (!form.name.trim()) return "请填写名称 (name)";
  return null;
}

/** probe 结论: ok=读到数据; unreachable=接口可达但本次被反爬/限频挡住; invalid=真实错误。 */
export type ProbeKind = "ok" | "unreachable" | "invalid";

export interface ProbeFailure {
  message: string;
  probeKind: ProbeKind | null;
  /** 仅当 probeKind === "unreachable" 时为 true —— 前端据此给出「仍要保存」出口。 */
  canSaveAnyway: boolean;
}

/**
 * 从 api.ts req() 抛出的 Error 还原 probe 结论。
 * req() 会把 detail 原样挂到 error.detail 上(见 web/lib/api.ts), 因此这里读它;
 * 拿不到结构化 detail(网络层错误等)时退化为纯文案。
 */
export function parseProbeFailure(e: unknown): ProbeFailure {
  const detail = (e as { detail?: unknown } | null)?.detail;
  const message = e instanceof Error ? e.message : String(e);
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; probe_kind?: string; can_save_anyway?: boolean };
    return {
      message: d.message || message,
      probeKind: (d.probe_kind as ProbeKind) ?? null,
      canSaveAnyway: d.probe_kind === "unreachable" && d.can_save_anyway !== false,
    };
  }
  return { message, probeKind: null, canSaveAnyway: false };
}

/** 资产已落库但清洗表还没有数据 —— builder 列表里据此打「待拉取」徽章。 */
export function isAwaitingData(a: Pick<Asset, "last_clean_date">): boolean {
  return !a.last_clean_date;
}
