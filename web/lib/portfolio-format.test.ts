import { describe, expect, it } from "vitest";
import { formatPortfolioUpdatedDate } from "./portfolio-format";

describe("formatPortfolioUpdatedDate", () => {
  it("优先 result_updated_at，其次 data_as_of_date", () => {
    expect(
      formatPortfolioUpdatedDate({
        result_updated_at: "2026-11-27T21:10:00+08:00",
        data_as_of_date: "2026-11-26",
      }),
    ).toBe("2026-11-27");
    expect(
      formatPortfolioUpdatedDate({
        result_updated_at: null,
        data_as_of_date: "2026-11-26",
      }),
    ).toBe("2026-11-26");
  });

  it("列表接口缺失字段时返回 null（前端不显示日期、不阻塞渲染）", () => {
    expect(formatPortfolioUpdatedDate({})).toBeNull();
    expect(formatPortfolioUpdatedDate({ result_updated_at: null, data_as_of_date: null })).toBeNull();
    expect(formatPortfolioUpdatedDate({ result_updated_at: "", data_as_of_date: "" })).toBeNull();
    expect(formatPortfolioUpdatedDate({ result_updated_at: "   " })).toBeNull();
  });

  it("日期串/时间戳都只取日期部分，不做时区换算", () => {
    expect(formatPortfolioUpdatedDate({ data_as_of_date: "2026-11-26" })).toBe("2026-11-26");
    expect(formatPortfolioUpdatedDate({ result_updated_at: "2026-11-27T00:30:00+08:00" })).toBe(
      "2026-11-27",
    );
    expect(formatPortfolioUpdatedDate({ result_updated_at: "2026-11-27T23:30:00Z" })).toBe(
      "2026-11-27",
    );
  });

  it("非法值降级为 null，不抛错", () => {
    expect(formatPortfolioUpdatedDate({ result_updated_at: "not-a-date" })).toBeNull();
    expect(
      formatPortfolioUpdatedDate({
        result_updated_at: "not-a-date",
        data_as_of_date: "2026-11-20",
      }),
    ).toBe("2026-11-20");
  });
});
