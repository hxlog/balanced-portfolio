import { cacheLife, cacheTag } from "next/cache";
import type { Asset, BacktestResult } from "./api";
import { apiBase } from "./session-server";

async function serverFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) {
    throw new Error(`API ${path}: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function safeServerFetch<T>(path: string): Promise<T | null> {
  try {
    return await serverFetch<T>(path);
  } catch {
    return null;
  }
}

/** 可选资产清单 — 供 Builder 预渲染；变更频率低。 */
export async function getCachedAssets(): Promise<Asset[]> {
  "use cache";
  cacheLife("hours");
  cacheTag("assets");
  const data = await safeServerFetch<{ assets: Asset[] }>("/api/assets");
  return data?.assets ?? [];
}

/** 示例组合回测结果 — 供 Dashboard 访客首屏；回测完成后需等 TTL 或手动 revalidateTag。 */
export async function getCachedDemoResult(
  portfolioId?: number | null,
  method?: string | null,
  benchmark?: string | null,
): Promise<BacktestResult | null> {
  "use cache";
  cacheLife("minutes");
  cacheTag("demo-result");
  const params = new URLSearchParams();
  if (portfolioId != null) params.set("portfolio_id", String(portfolioId));
  if (method) params.set("method", method);
  if (benchmark) params.set("benchmark", benchmark);
  const qs = params.toString();
  try {
    return await serverFetch<BacktestResult>(
      `/api/portfolios/demo${qs ? `?${qs}` : ""}`,
    );
  } catch {
    return null;
  }
}