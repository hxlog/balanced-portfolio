import { cacheLife, cacheTag } from "next/cache";
import type { Asset, BacktestResult, CryptoCorrelationResponse } from "./api";
import { apiBase, readSessionClaims, readSessionToken } from "./session-server";

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

/** /crypto 相关性看板 — 供 /crypto 首屏 SSR。
 *
 * 后端读预计算表 (bp_crypto_corr_daily / bp_crypto_price_daily / bp_crypto_meta),
 * 请求路径永不计算 (原 27s build_all_correlations 已移到 bp_ingest 调度任务)。
 * 失效: 后端 ingest/调度任务重算后 POST /api/revalidate/crypto (内部令牌) 失效该 tag,
 * 或等 cacheLife("hours") TTL 兜底。 */
export async function getCachedCryptoCorrelation(): Promise<CryptoCorrelationResponse> {
  "use cache";
  cacheLife("hours");
  cacheTag("crypto");
  // 失败时 throw (不缓存 null): "use cache" 不缓存 throw 的结果,
  // 避免部署/重启时 FastAPI 未就绪致 stale null 缓存 1h (曾致 /crypto「获取数据失败」)。
  return await serverFetch<CryptoCorrelationResponse>("/api/crypto/correlation");
}

/** 解析登录用户在 /dashboard 无 id 时的默认组合 id(服务端重定向用)。
 *
 * 管理员(claims.role=admin) → 第一个公共案例(demo);
 * 普通用户 → 第一个自建(非 demo)组合, 无自建则回退第一个 demo;
 * 无 session / 接口失败时返回 null, 由调用方回退到 demo。
 * 注意: 不加 "use cache"(结果随用户而异, 且依赖 httpOnly cookie)。
 */
export async function resolveDefaultPortfolioId(): Promise<number | null> {
  const token = await readSessionToken();
  if (!token) return null;
  try {
    const res = await fetch(`${apiBase()}/api/portfolios`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { portfolios?: Array<{ portfolio_id: number; is_demo: boolean }> };
    const list = data?.portfolios ?? [];
    const claims = await readSessionClaims();
    const firstDemo = list.find((p) => p.is_demo);
    if (claims?.role === "admin") {
      return firstDemo ? firstDemo.portfolio_id : null; // 管理员默认公共案例第一
    }
    const firstOwn = list.find((p) => !p.is_demo);
    if (firstOwn) return firstOwn.portfolio_id;
    return firstDemo ? firstDemo.portfolio_id : null;
  } catch {
    return null;
  }
}