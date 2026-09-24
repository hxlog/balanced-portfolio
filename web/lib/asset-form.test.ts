/**
 * 资产新增表单的共享口径测试 —— /admin/assets 与 /builder 新增对话框共用同一份,
 * 因此这里钉住的是「测试什么就保存什么」与「限频时能否保存」两条契约。
 */

import { describe, expect, it } from "vitest";
import {
  ASSET_CREATE_DEFAULTS,
  buildExtraParams,
  isAwaitingData,
  parseProbeFailure,
  validateAssetInput,
} from "./asset-form";

describe("buildExtraParams", () => {
  it("ETF 携带所选复权, 与落库 extra_params.adjust 同口径", () => {
    expect(buildExtraParams("etf_em", "etf", "hfq")).toEqual({ adjust: "hfq" });
    expect(buildExtraParams("etf_em", "etf", "qfq")).toEqual({ adjust: "qfq" });
  });

  it("非 ETF 类目不带 adjust —— 复权只对 ETF 有意义", () => {
    expect(buildExtraParams("etf_em", "index", "hfq")).toEqual({});
    expect(buildExtraParams("cn_index_em", "index", "hfq")).toEqual({});
  });

  it("中债国债固定财富口径(与 ingest 默认一致)", () => {
    expect(buildExtraParams("bond_csi_treasury", "bond", null)).toEqual({ indicator: "财富" });
  });

  it("ETF 但未选复权时返回空对象, 不传 undefined 键", () => {
    expect(buildExtraParams("etf_em", "etf", "")).toEqual({});
    expect(buildExtraParams("etf_em", "etf", null)).toEqual({});
  });
});

describe("validateAssetInput", () => {
  it("数据源/代码/名称齐全时通过", () => {
    expect(
      validateAssetInput({ ...ASSET_CREATE_DEFAULTS, symbol: "510300", name: "沪深300ETF" }),
    ).toBeNull();
  });

  it("缺名称、缺代码、代码只有空白都拦下", () => {
    expect(validateAssetInput({ ...ASSET_CREATE_DEFAULTS, symbol: "510300" })).toContain("名称");
    expect(validateAssetInput({ ...ASSET_CREATE_DEFAULTS, name: "甲" })).toContain("代码");
    expect(validateAssetInput({ ...ASSET_CREATE_DEFAULTS, symbol: "   ", name: "甲" })).toContain("代码");
  });

  it("缺数据源时给出可读文案", () => {
    expect(validateAssetInput({ ...ASSET_CREATE_DEFAULTS, source: "", symbol: "1", name: "甲" })).toContain("数据源");
  });
});

describe("parseProbeFailure", () => {
  it("从结构化 detail 还原 unreachable 并给出保存出口", () => {
    const err = Object.assign(new Error("源 etf_em 及降级链均无法拉取 510300"), {
      detail: {
        message: "源 etf_em 及降级链均无法拉取 510300",
        probe_kind: "unreachable",
        can_save_anyway: true,
      },
    });
    const out = parseProbeFailure(err);
    expect(out.probeKind).toBe("unreachable");
    expect(out.canSaveAnyway).toBe(true);
    expect(out.message).toContain("无法拉取");
  });

  it("invalid 时不给出保存出口", () => {
    const err = Object.assign(new Error("未知 source: nope"), {
      detail: { message: "未知 source: nope", probe_kind: "invalid", can_save_anyway: false },
    });
    const out = parseProbeFailure(err);
    expect(out.probeKind).toBe("invalid");
    expect(out.canSaveAnyway).toBe(false);
  });

  it("plain Error(网络层失败) 退化为纯文案, 不给出口", () => {
    const out = parseProbeFailure(new Error("Failed to fetch"));
    expect(out.message).toBe("Failed to fetch");
    expect(out.probeKind).toBeNull();
    expect(out.canSaveAnyway).toBe(false);
  });

  it("can_save_anyway 显式为 false 时即使 kind 是 unreachable 也不放行", () => {
    const err = Object.assign(new Error("x"), {
      detail: { message: "x", probe_kind: "unreachable", can_save_anyway: false },
    });
    expect(parseProbeFailure(err).canSaveAnyway).toBe(false);
  });
});

describe("isAwaitingData", () => {
  it("无清洗日 = 待拉取(新建资产或限频期间)", () => {
    expect(isAwaitingData({ last_clean_date: null })).toBe(true);
    expect(isAwaitingData({ last_clean_date: undefined })).toBe(true);
  });

  it("已有清洗日 = 数据就绪", () => {
    expect(isAwaitingData({ last_clean_date: "2026-09-24" })).toBe(false);
  });
});
