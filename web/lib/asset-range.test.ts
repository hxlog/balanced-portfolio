import { describe, expect, it } from "vitest";

import {
  NO_DATA_LABEL,
  RANGE_TONE_CLASS,
  formatDateCN,
  formatRangeCN,
  hasNoData,
  rangeTone,
} from "./asset-range";

describe("formatDateCN", () => {
  it("月/日不补零, 与用户给的示例一致", () => {
    expect(formatDateCN("2020-01-04")).toBe("2020年1月4日");
    expect(formatDateCN("2026-09-25")).toBe("2026年9月25日");
    expect(formatDateCN("2026-12-31")).toBe("2026年12月31日");
  });

  it("空值与不可解析格式返回 null", () => {
    expect(formatDateCN(null)).toBeNull();
    expect(formatDateCN(undefined)).toBeNull();
    expect(formatDateCN("")).toBeNull();
    expect(formatDateCN("2026/09/25")).toBeNull();
    expect(formatDateCN("not-a-date")).toBeNull();
  });

  it("容忍后端带时间戳的 ISO(截断取日期部分)", () => {
    expect(formatDateCN("2026-09-25T00:00:00")).toBe("2026年9月25日");
  });
});

describe("formatRangeCN", () => {
  it("完整区间", () => {
    expect(formatRangeCN("2020-01-04", "2026-09-25")).toBe("2020年1月4日 - 2026年9月25日");
  });

  it("同一天两端", () => {
    expect(formatRangeCN("2026-09-25", "2026-09-25")).toBe("2026年9月25日 - 2026年9月25日");
  });

  it("首日为 NULL(50 号之前的老行)降级为只显示截止日, 不显示 'null'", () => {
    expect(formatRangeCN(null, "2026-09-25")).toBe("2026年9月25日");
  });

  it("只有首日时只显示首日", () => {
    expect(formatRangeCN("2020-01-04", null)).toBe("2020年1月4日");
  });

  it("两者皆无返回 null(调用方显示 NO_DATA_LABEL)", () => {
    expect(formatRangeCN(null, null)).toBeNull();
    expect(formatRangeCN(undefined, undefined)).toBeNull();
    expect(formatRangeCN("垃圾", null)).toBeNull();
  });
});

describe("rangeTone", () => {
  it("无清洗数据(nodata)优先于滞后与未覆盖", () => {
    // 无数据时后端也算不出 covered_at_start(false), 但不能报「未覆盖」—— 那是两回事
    expect(rangeTone({ lastDate: null, isLagging: true, coveredAtStart: false })).toBe("nodata");
    expect(rangeTone({ lastDate: undefined })).toBe("nodata");
  });

  it("滞后优先于未覆盖", () => {
    expect(
      rangeTone({ lastDate: "2026-09-25", isLagging: true, coveredAtStart: false }),
    ).toBe("lagging");
  });

  it("未覆盖", () => {
    expect(
      rangeTone({ lastDate: "2026-09-25", isLagging: false, coveredAtStart: false }),
    ).toBe("uncovered");
  });

  it("正常", () => {
    expect(
      rangeTone({ lastDate: "2026-09-25", isLagging: false, coveredAtStart: true }),
    ).toBe("none");
  });

  it("调用点缺字段时不误判", () => {
    // /builder 拿不到 coveredAtStart → 不得因 undefined 就报未覆盖
    expect(rangeTone({ lastDate: "2026-09-25", isLagging: false })).toBe("none");
    // covered_at_start 为 null(字段存在但后端没算出来)同样不报
    expect(rangeTone({ lastDate: "2026-09-25", coveredAtStart: null })).toBe("none");
    // 只有 lastDate 有值、firstDate 缺失(老库)仍算有数据
    expect(rangeTone({ lastDate: "2026-09-25", firstDate: null })).toBe("none");
  });

  it("hasNoData 只看截止日", () => {
    expect(hasNoData(null)).toBe(true);
    expect(hasNoData(undefined)).toBe(true);
    expect(hasNoData("")).toBe(true);
    expect(hasNoData("2026-09-25")).toBe(false);
  });

  it("色调映射: 滞后红 / 未覆盖琥珀 / 无数据与正常灰(不挪用涨跌色)", () => {
    expect(RANGE_TONE_CLASS.lagging).toBe("text-destructive");
    expect(RANGE_TONE_CLASS.uncovered).toBe("text-warning");
    expect(RANGE_TONE_CLASS.nodata).toBe("text-muted-foreground");
    expect(RANGE_TONE_CLASS.none).toBe("text-muted-foreground");
    // design-system: 涨跌色只给方向性涨跌用, 这里任何时候都不该出现
    for (const cls of Object.values(RANGE_TONE_CLASS)) {
      expect(cls).not.toContain("text-up");
      expect(cls).not.toContain("text-down");
    }
  });

  it("占位文案", () => {
    expect(NO_DATA_LABEL).toBe("暂无行情数据");
  });
});
