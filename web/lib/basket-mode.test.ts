import { describe, expect, it } from "vitest";
import {
  isModeUrl,
  modeFromQuery,
  modeHref,
  modeSwitchHref,
  modeSwitchPath,
} from "./basket-mode";

describe("modeFromQuery", () => {
  it("parses mode=basket and defaults everything else to quadrant", () => {
    expect(modeFromQuery("mode=basket")).toBe("basket");
    expect(modeFromQuery("?mode=basket&id=3")).toBe("basket");
    expect(modeFromQuery("mode=quadrant")).toBe("quadrant");
    expect(modeFromQuery("id=3")).toBe("quadrant");
    expect(modeFromQuery("")).toBe("quadrant");
    expect(modeFromQuery(new URLSearchParams("mode=basket"))).toBe("basket");
  });
});

describe("modeHref", () => {
  it("sets mode=basket and keeps other params", () => {
    expect(modeHref("/dashboard", "id=12", "basket")).toBe(
      "/dashboard?id=12&mode=basket",
    );
    expect(modeHref("/dashboard", "?id=12&mode=basket", "basket")).toBe(
      "/dashboard?id=12&mode=basket",
    );
  });

  it("removes mode and basket params when switching back to quadrant", () => {
    expect(modeHref("/dashboard", "basket=7&mode=basket&id=12", "quadrant")).toBe(
      "/dashboard?id=12",
    );
    expect(modeHref("/builder", "mode=basket", "quadrant")).toBe("/builder");
  });

  it("keeps copy/edit params across mode switches", () => {
    const href = modeHref("/builder", "copy=5", "basket");
    expect(href).toBe("/builder?copy=5&mode=basket");
  });
});

describe("modeSwitchPath / modeSwitchHref", () => {
  it("returns to the guest-readable /dashboard when leaving the /builder basket page", () => {
    // 历史缺陷：/builder 的四象限页对游客显示「需要登录」，切回四象限必须回 /dashboard。
    expect(modeSwitchPath("/builder", "quadrant")).toBe("/dashboard");
    expect(modeSwitchHref("/builder", "mode=basket&basket=4", "quadrant")).toBe(
      "/dashboard",
    );
  });

  it("keeps /builder when switching to basket and keeps /dashboard otherwise", () => {
    expect(modeSwitchPath("/builder", "basket")).toBe("/builder");
    expect(modeSwitchHref("/builder", "mode=basket", "basket")).toBe(
      "/builder?mode=basket",
    );
    expect(modeSwitchPath("/dashboard", "quadrant")).toBe("/dashboard");
    expect(modeSwitchHref("/dashboard", "mode=basket&id=3", "quadrant")).toBe(
      "/dashboard?id=3",
    );
  });
});

describe("isModeUrl", () => {
  it("reports whether the url matches the requested mode", () => {
    expect(isModeUrl("mode=basket", "basket")).toBe(true);
    expect(isModeUrl("mode=basket", "quadrant")).toBe(false);
    expect(isModeUrl("id=3", "quadrant")).toBe(true);
  });
});
