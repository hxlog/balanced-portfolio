import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const routes = ["/", "/dashboard", "/cffex", "/otc-derivatives-pricing", "/methodology"];
  return routes.map((path) => ({
    url: path,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: path === "/" ? 1 : 0.7,
  }));
}
