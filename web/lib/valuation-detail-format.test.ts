import { describe, expect, it } from "vitest";
import {
  TE_WARNING_THRESHOLD_PCT,
  formatAumYi,
  formatPercentileValue,
  formatTrackerMeta,
  formatUpdatedAtCompact,
  hasUsablePercentile,
  percentileLabel,
  percentileTone,
  percentileUnavailableText,
  sumTrackerFundScale,
  trackerFundScale,
  trackingErrorClass,
  trackingErrorTone,
} from "./valuation-detail-format";
import type { PercentileSummary } from "./valuation-detail-types";

function summary(overrides: Partial<PercentileSummary> = {}): PercentileSummary {
  return {
    pct: 42.1,
    mean: 12.2,
    sd: 0.8,
    p20: 11,
    p50: 12,
    p80: 13,
    min: 10,
    max: 14,
    sample_size: 200,
    ...overrides,
  };
}

describe("跟踪误差 TE 告警", () => {
  it("阈值常量为 5%（百分数点）", () => {
    expect(TE_WARNING_THRESHOLD_PCT).toBe(5);
  });

  it("TE>5% 告警，<=5% 正常，缺失单独标记", () => {
    expect(trackingErrorTone(4.31)).toBe("normal");
    expect(trackingErrorTone(5)).toBe("normal");
    expect(trackingErrorTone(5.01)).toBe("warning");
    expect(trackingErrorTone(50.57)).toBe("warning");
    expect(trackingErrorTone(null)).toBe("missing");
    expect(trackingErrorTone(Number.NaN)).toBe("missing");
  });

  it("告警使用 warning 语义色，不误用涨跌色", () => {
    expect(trackingErrorClass(6.2)).toContain("text-warning");
    expect(trackingErrorClass(4.31)).toBe("");
    expect(trackingErrorClass(null)).toContain("text-muted-foreground");
  });
});

describe("跟踪基金右上角元信息", () => {
  it("拼接「规模合计 · 数据截至 · 更新于」", () => {
    const text = formatTrackerMeta({
      totalAum: 127.4035e9,
      asOf: "2026-11-23",
      updatedAt: "2026-11-27T21:10:00+08:00",
    });
    expect(text).toBe("规模合计 1,274.04 亿元 · 数据截至 2026-11-23 · 更新于 2026-11-27 21:10");
  });

  it("缺失字段用占位符而不是 0 / 今天", () => {
    const text = formatTrackerMeta({ totalAum: null, asOf: null, updatedAt: null });
    expect(text).toBe("规模合计 — · 数据截至 — · 更新于 —");
  });

  it("formatUpdatedAtCompact 截断到分钟", () => {
    expect(formatUpdatedAtCompact("2026-11-27T21:10:45+08:00")).toBe("2026-11-27 21:10");
    expect(formatUpdatedAtCompact(null)).toBe("—");
  });
});

describe("基金规模与分位格式化（回归覆盖）", () => {
  it("元 -> 亿元保留 2 位；缺失占位", () => {
    expect(formatAumYi(2.5e8)).toBe("2.50");
    expect(formatAumYi(null)).toBe("—");
  });

  it("0~100 分位直接加 %，不再 ×100", () => {
    expect(formatPercentileValue(42.1, 1)).toBe("42.1%");
    expect(formatPercentileValue(null)).toBe("—");
  });

  it("分位语气/标签使用唯一阈值（<30 success / 30~70 primary / >70 destructive）", () => {
    expect(percentileTone(20)).toContain("text-success");
    expect(percentileTone(50)).toContain("text-primary");
    expect(percentileTone(80)).toContain("text-destructive");
    // 边界 30 / 70 归入中性，避免两套阈值（<=30 vs <30）造成同值不同色
    expect(percentileTone(30)).toContain("text-primary");
    expect(percentileTone(70)).toContain("text-primary");
    expect(percentileTone(null)).toContain("text-muted-foreground");
    expect(percentileLabel(20)).toBe("低估");
    expect(percentileLabel(50)).toBe("中性");
    expect(percentileLabel(80)).toBe("高估");
    expect(percentileLabel(30)).toBe("中性");
    expect(percentileLabel(70)).toBe("中性");
    expect(hasUsablePercentile(summary())).toBe(true);
    expect(hasUsablePercentile(summary({ sample_size: 119 }))).toBe(false);
    expect(percentileUnavailableText(summary({ sample_size: 60 }))).toContain("样本不足");
    expect(percentileUnavailableText(null)).toBe("暂无分位统计");
  });
});

describe("跟踪基金规模口径", () => {
  it("fund_scale 优先、缺失回退 aum；合计与逐行同口径", () => {
    expect(trackerFundScale({ fund_scale: 5e9, aum: 4e9 })).toBe(5e9);
    expect(trackerFundScale({ fund_scale: null, aum: 4e9 })).toBe(4e9);
    expect(trackerFundScale({ fund_scale: null, aum: null })).toBeNull();
    expect(trackerFundScale({ fund_scale: Number.NaN, aum: 4e9 })).toBeNull();

    const funds = [
      { fund_scale: 5e9, aum: 4e9 },
      { fund_scale: null, aum: 2e9 },
      { fund_scale: null, aum: null },
    ];
    expect(sumTrackerFundScale(funds)).toBe(7e9);
    // 与逐行 trackerFundScale 相加一致（不再只累加 aum）
    expect(sumTrackerFundScale(funds)).toBe(
      funds.reduce((sum, fund) => sum + (trackerFundScale(fund) ?? 0), 0),
    );
    expect(sumTrackerFundScale([])).toBeNull();
    expect(sumTrackerFundScale([{ fund_scale: null, aum: null }])).toBeNull();
  });
});
