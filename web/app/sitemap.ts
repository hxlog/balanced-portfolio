import type { MetadataRoute } from "next";

/**
 * 站点地图：静态路由 + 521 个指数估值详情页。
 *
 * 注意：sitemap 规范要求 <loc> 必须是绝对 URL；此前用相对路径会被搜索引擎忽略。
 * 详情页列表在请求期从 FastAPI 读取（失败时退化为只含静态路由，不影响其余页面收录）。
 */
const SITE_URL = (process.env.BP_SITE_URL || "https://xushilu.com").replace(/\/$/, "");

const STATIC_ROUTES: Array<{ path: string; priority: number; freq: "daily" | "weekly" | "monthly" }> = [
  { path: "/", priority: 1, freq: "weekly" },
  { path: "/valuation", priority: 0.9, freq: "daily" },
  { path: "/crypto-futures", priority: 0.8, freq: "daily" },
  { path: "/crypto", priority: 0.7, freq: "weekly" },
  { path: "/cffex", priority: 0.8, freq: "daily" },
  { path: "/dashboard", priority: 0.7, freq: "weekly" },
  { path: "/builder", priority: 0.6, freq: "monthly" },
  { path: "/otc-pricing", priority: 0.5, freq: "monthly" },
  { path: "/otc-derivatives-pricing", priority: 0.5, freq: "monthly" },
  { path: "/methodology", priority: 0.5, freq: "monthly" },
];

async function fetchIndexCodes(): Promise<string[]> {
  const base = process.env.BP_API_BASE || "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${base}/api/valuation/indices?limit=1000`, {
      cache: "no-store",
    });
    if (!response.ok) return [];
    const payload = (await response.json()) as { data?: Array<{ index_code?: string }> };
    return (payload.data ?? [])
      .map((row) => String(row.index_code ?? ""))
      .filter((code) => code.length > 0);
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path}`,
    lastModified: now,
    changeFrequency: route.freq,
    priority: route.priority,
  }));

  const codes = await fetchIndexCodes();
  const detailEntries: MetadataRoute.Sitemap = codes.map((code) => ({
    url: `${SITE_URL}/valuation/${encodeURIComponent(code)}`,
    lastModified: now,
    changeFrequency: "daily" as const,
    priority: 0.6,
  }));

  return [...staticEntries, ...detailEntries];
}
