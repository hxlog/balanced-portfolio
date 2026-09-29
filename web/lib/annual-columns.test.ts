import { describe, expect, it } from "vitest";
import { annualColumns, annualLabel, ANNUAL_YEAR_RE } from "./annual-columns";

describe("annualColumns", () => {
  it("用户要的列顺序: YTD → 各年降序 → 年化", () => {
    // 后端实际返回的键集(见 metrics.annual_returns), 回测区间 2020-01-02 起、2026 年今
    const out = annualColumns({
      ytd: 0.1182,
      2026: 0.1182,
      2025: 0.1444,
      2024: 0.0913,
      2023: -0.0429,
      2022: -0.1382,
      2021: -0.0035,
      2020: 0.3203,
      annualized: 0.0592,
    });
    expect(out).toEqual([
      "ytd",
      "2025",
      "2024",
      "2023",
      "2022",
      "2021",
      "2020",
      "annualized",
    ]);
  });

  it("当年不出现在年份列里(ytd 与它同值, 列出来只是重复)", () => {
    const out = annualColumns({ ytd: 0.1, 2026: 0.1, 2025: 0.2, annualized: 0.05 });
    expect(out).not.toContain("2026");
    expect(out.filter((k) => k === "ytd")).toHaveLength(1);
    // 只裁掉「最新那一年」, 更早的年份一个不少
    expect(out).toEqual(["ytd", "2025", "annualized"]);
  });

  it("年序按数值倒排而非字符串序(否则 0999 类键会乱)", () => {
    expect(annualColumns({ 2024: 1, 2025: 1, 1999: 1 })).toEqual([
      "2025",
      "2024",
      "1999",
    ]);
  });

  it("非年份键(如 annualized/ytd)不得混进年份列", () => {
    const out = annualColumns({ ytd: 1, 2025: 1, 2024: 1, annualized: 1 });
    // 有 ytd 时最新年份被它代表 → 年份列只剩 2024; ytd/annualized 不在其中
    expect(out).toEqual(["ytd", "2024", "annualized"]);
    expect(out.filter((k) => ANNUAL_YEAR_RE.test(k))).toEqual(["2024"]);
  });

  it("缺 ytd(老结果体)时照常列年份, 不裁剪", () => {
    expect(annualColumns({ 2025: 1, 2024: 1 })).toEqual(["2025", "2024"]);
  });

  it("没有年份键 → 空数组(调用方据此整块不渲染)", () => {
    expect(annualColumns({})).toEqual([]);
    expect(annualColumns({ ytd: 1, annualized: 1 })).toEqual([]);
    expect(annualColumns(null)).toEqual([]);
    expect(annualColumns(undefined)).toEqual([]);
  });

  it("仅一年也应正常成列(不越界)", () => {
    expect(annualColumns({ ytd: 1, 2026: 1 })).toEqual(["ytd"]);
    expect(annualColumns({ 2026: 1 })).toEqual(["2026"]);
  });
});

describe("annualLabel", () => {
  it("年份原样展示, ytd/annualized 走中文名", () => {
    expect(annualLabel("2025")).toBe("2025");
    expect(annualLabel("ytd")).toBe("YTD");
    expect(annualLabel("annualized")).toBe("年化");
  });
});
