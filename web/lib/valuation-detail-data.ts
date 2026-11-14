/**
 * `/valuation/[code]` 的服务端数据层。
 *
 * 与 `cached-data.ts` 同一形态：`"use cache"` + `cacheLife("hours")` +
 * `cacheTag("valuation")`。后端重算落库后可通过 `POST /api/revalidate/valuation`
 * 失效同一个 tag；失败时 throw（不缓存 null），由页面 catch 后展示错误态。
 *
 * 请求路径只读后端预计算表，不在 Next 侧做任何计算。
 */

import { cacheLife, cacheTag } from "next/cache";
import { apiBase } from "./session-server";

/** 后端统一响应信封。 */
export interface ValuationEnvelope {
  data: Record<string, unknown>;
  meta: Record<string, unknown>;
}

async function serverFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) {
    throw new Error(`API ${path}: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** 指数详情（画像 + 最新估值 + 分位 + 成分 + 跟踪基金）。 */
export async function getCachedValuationDetail(
  code: string,
): Promise<ValuationEnvelope> {
  "use cache";
  cacheLife("hours");
  cacheTag("valuation");
  return await serverFetch<ValuationEnvelope>(
    `/api/valuation/${encodeURIComponent(code)}`,
  );
}

/** 估值历史序列 + 区间统计。 */
export async function getCachedValuationHistory(
  code: string,
  metric = "pe_ttm",
  windowKey = "5y",
): Promise<ValuationEnvelope> {
  "use cache";
  cacheLife("hours");
  cacheTag("valuation");
  const params = new URLSearchParams({ metric, window: windowKey });
  return await serverFetch<ValuationEnvelope>(
    `/api/valuation/${encodeURIComponent(code)}/history?${params.toString()}`,
  );
}
