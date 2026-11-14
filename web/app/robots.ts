import type { MetadataRoute } from "next";

const SITE_URL = (process.env.BP_SITE_URL || "https://xushilu.com").replace(/\/$/, "");

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/valuation", "/valuation/", "/crypto", "/crypto-futures", "/cffex", "/methodology"],
        disallow: ["/admin", "/api/", "/builder", "/dashboard"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
