/**
 * 加密合约看板服务端数据层。
 *
 * 与 `web/lib/cached-data.ts` 同模式：`"use cache"` + `cacheLife` + `cacheTag`，
 * 失败时 throw（Next 不缓存 throw），由 page.tsx 捕获后渲染错误态，避免 500。
 *
 * 注意：这里刻意用 60s 档而不是 `cacheLife("hours")` —— 后端快照每 5 分钟一批、
 * API Redis TTL 60s，页面每 60s `router.refresh()`；用 hours 会让「5 分钟更新」
 * 冻结一小时。tag 用独立的 `crypto-futures`，避免与 /crypto 相关性看板的
 * `crypto` tag 互相打穿（见 docs/index-valuation/09-product-spec.md 5.3）。
 */
import { cacheLife, cacheTag } from "next/cache";
import { apiBase } from "./session-server";
import { normalizeContract, normalizeSummary } from "./crypto-futures-format";
import type {
  CryptoFuturesApiEnvelope,
  CryptoFuturesContract,
  CryptoFuturesSummary,
} from "./crypto-futures-types";

const REQUEST_TIMEOUT_MS = 10_000;
export const CRYPTO_FUTURES_CONTRACTS_LIMIT = 30;

async function serverFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`API ${path} 返回 ${response.status}`);
  }
  return (await response.json()) as T;
}

/** 顶部 4 张汇总卡。 */
export async function getCachedCryptoFuturesSummary(): Promise<CryptoFuturesSummary> {
  "use cache";
  cacheLife({ stale: 30, revalidate: 60, expire: 3600 });
  cacheTag("crypto-futures");

  const body = await serverFetch<CryptoFuturesApiEnvelope<unknown>>(
    "/api/crypto/futures/summary",
  );
  const summary = normalizeSummary(body?.data);
  if (!summary) throw new Error("crypto futures summary: empty payload");
  return summary;
}

/** 合约榜（后端已按 OI 倒序返回；客户端仍会再排一次作为防御）。 */
export async function getCachedCryptoFuturesContracts(
  limit = CRYPTO_FUTURES_CONTRACTS_LIMIT,
): Promise<CryptoFuturesContract[]> {
  "use cache";
  cacheLife({ stale: 30, revalidate: 60, expire: 3600 });
  cacheTag("crypto-futures");

  const safeLimit = Math.min(60, Math.max(1, Math.trunc(limit)));
  const body = await serverFetch<CryptoFuturesApiEnvelope<unknown[]>>(
    `/api/crypto/futures/contracts?limit=${safeLimit}`,
  );
  if (!Array.isArray(body?.data)) {
    throw new Error("crypto futures contracts: invalid payload");
  }
  return body.data
    .map(normalizeContract)
    .filter((contract): contract is CryptoFuturesContract => contract !== null);
}
