/**
 * Binance FAPI 只读代理 Worker（P5）。
 *
 * 背景：生产服务器无法直连 Binance（timeout），由本 Worker 中转无需签名的
 * 公开端点（合约发现 + 5 分钟微观数据）。Worker 不接触任何 API Key/Secret，
 * 只做白名单转发。
 *
 * 请求形态：
 *   GET https://<worker>/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT
 *
 * 安全边界：
 *   - `path` 必须精确命中 ALLOWED_PATHS（防 SSRF / 私有端点）；
 *   - 除 premiumIndex 外必须带 symbol；
 *   - 每 IP 每 60 秒最多 120 次（实例内固定窗口，见 README 的限制说明）；
 *   - CORS 仅允许 https://xushilu.com（可用 ALLOWED_ORIGIN 覆盖）。
 *
 * 缓存：`caches.default` 按上游 URL 缓存 5 分钟；上游错误不缓存。
 */

import type { ExecutionContext } from "@cloudflare/workers-types";

export const BINANCE_BASE = "https://fapi.binance.com";
export const DEFAULT_ALLOWED_ORIGIN = "https://xushilu.com";
export const CACHE_SECONDS = 300;
export const RATE_LIMIT_PER_MINUTE = 120;

const EXCHANGE_INFO = "/fapi/v1/exchangeInfo";
const TICKER_24H = "/fapi/v1/ticker/24hr";
const PREMIUM_INDEX = "/fapi/v1/premiumIndex";
const OPEN_INTEREST = "/fapi/v1/openInterest";
const GLOBAL_LONG_SHORT = "/futures/data/globalLongShortAccountRatio";
const TAKER_LONG_SHORT = "/futures/data/takerlongshortRatio";
const OI_HIST = "/futures/data/openInterestHist";

/**
 * 可转发的公开、无签名端点。
 *
 * exchangeInfo / ticker/24hr 是 `fetch_contracts()` 筛选 Top 30 USDT 永续
 * 的必需输入；生产服务器无法直连 Binance，故必须一并经本 Worker 转发。
 */
export const ALLOWED_PATHS: ReadonlySet<string> = new Set([
  EXCHANGE_INFO,
  TICKER_24H,
  PREMIUM_INDEX,
  OPEN_INTEREST,
  GLOBAL_LONG_SHORT,
  TAKER_LONG_SHORT,
  OI_HIST,
]);

/** 这些端点的上游 API 要求 symbol 参数。 */
const SYMBOL_REQUIRED_PATHS: ReadonlySet<string> = new Set([
  OPEN_INTEREST,
  GLOBAL_LONG_SHORT,
  TAKER_LONG_SHORT,
  OI_HIST,
]);

export interface Env {
  /** 覆盖默认 CORS 允许源（可选，默认 https://xushilu.com）。 */
  ALLOWED_ORIGIN?: string;
}

/** 只依赖 match/put 的最小缓存接口，便于离线单测注入。 */
export interface CacheLike {
  match(request: Request): Promise<Response | undefined>;
  put(request: Request, response: Response): Promise<void>;
}

export interface HandlerDeps {
  limiter?: FixedWindowRateLimiter;
  cache?: CacheLike;
  fetchImpl?: typeof fetch;
  now?: () => number;
}

export interface RateLimitDecision {
  allowed: boolean;
  remaining: number;
  /** 仅 allowed=false 时有意义：建议客户端等待的秒数。 */
  retryAfter: number;
}

/**
 * 实例内固定窗口限流器。
 *
 * Cloudflare Worker 的 isolate 可能横向扩展，因此这是「每实例」限流而非全局
 * 精确配额；对公开只读代理足以挡住误用/脚本滥用。需要严格全局限流时应改用
 * Cloudflare Rate Limiting 规则或 Durable Object（见 README）。
 */
export class FixedWindowRateLimiter {
  private readonly limit: number;
  private readonly windowMs: number;
  private readonly buckets = new Map<string, { start: number; count: number }>();

  constructor(limit: number = RATE_LIMIT_PER_MINUTE, windowMs: number = 60_000) {
    this.limit = limit;
    this.windowMs = windowMs;
  }

  allow(key: string, now: number = Date.now()): RateLimitDecision {
    const bucket = this.buckets.get(key);
    if (!bucket || now - bucket.start >= this.windowMs) {
      this.buckets.set(key, { start: now, count: 1 });
      this.sweep(now);
      return { allowed: true, remaining: this.limit - 1, retryAfter: 0 };
    }
    if (bucket.count < this.limit) {
      bucket.count += 1;
      return { allowed: true, remaining: this.limit - bucket.count, retryAfter: 0 };
    }
    const retryAfter = Math.max(
      1,
      Math.ceil((bucket.start + this.windowMs - now) / 1000),
    );
    return { allowed: false, remaining: 0, retryAfter };
  }

  /** 防止被大量随机 IP 撑爆内存：超过 1 万键时清理过期桶。 */
  private sweep(now: number): void {
    if (this.buckets.size <= 10_000) return;
    for (const [key, bucket] of this.buckets) {
      if (now - bucket.start >= this.windowMs) this.buckets.delete(key);
    }
  }
}

export function isAllowedPath(path: string): boolean {
  return ALLOWED_PATHS.has(path);
}

export function pathRequiresSymbol(path: string): boolean {
  return SYMBOL_REQUIRED_PATHS.has(path);
}

/** 把 `?path=` 与其余 query 重组成上游 URL（path 参数本身不透传）。 */
export function buildUpstreamUrl(path: string, params: URLSearchParams): string {
  if (!isAllowedPath(path)) {
    throw new Error(`path not allowed: ${path}`);
  }
  const forwarded = new URLSearchParams(params);
  forwarded.delete("path");
  const query = forwarded.toString();
  return `${BINANCE_BASE}${path}${query ? `?${query}` : ""}`;
}

export function corsHeaders(
  origin: string | null,
  allowedOrigin: string = DEFAULT_ALLOWED_ORIGIN,
): Record<string, string> {
  const headers: Record<string, string> = {
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
  if (origin !== null && origin === allowedOrigin) {
    headers["Access-Control-Allow-Origin"] = allowedOrigin;
  }
  return headers;
}

function jsonError(
  status: number,
  code: string,
  headers: Record<string, string>,
  extra: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify({ error: { code } }), {
    status,
    headers: {
      ...headers,
      ...extra,
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

async function withCors(
  response: Response,
  cors: Record<string, string>,
): Promise<Response> {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(cors)) headers.set(key, value);
  return new Response(response.body, { status: response.status, headers });
}

function defaultCache(): CacheLike | undefined {
  // Node 单测环境没有 caches；Worker runtime 恒有 caches.default。
  if (typeof caches === "undefined") return undefined;
  return caches.default as unknown as CacheLike;
}

export async function handleRequest(
  request: Request,
  env: Env = {},
  ctx?: ExecutionContext,
  deps: HandlerDeps = {},
): Promise<Response> {
  const allowedOrigin = env.ALLOWED_ORIGIN || DEFAULT_ALLOWED_ORIGIN;
  const cors = corsHeaders(request.headers.get("Origin"), allowedOrigin);

  // 预检不消耗限频额度。
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }
  if (request.method !== "GET") {
    return jsonError(405, "method_not_allowed", cors);
  }

  // 限频先于参数校验：无效请求同样消耗额度，避免绕过限流刷 Worker。
  const limiter = deps.limiter ?? defaultLimiter;
  const clientIp = request.headers.get("CF-Connecting-IP") || "unknown";
  const now = deps.now ? deps.now() : Date.now();
  const decision = limiter.allow(clientIp, now);
  if (!decision.allowed) {
    return jsonError(429, "rate_limited", cors, {
      "Retry-After": String(decision.retryAfter),
    });
  }

  const url = new URL(request.url);
  const path = url.searchParams.get("path");
  if (!path) {
    return jsonError(400, "missing_path", cors);
  }
  if (!isAllowedPath(path)) {
    return jsonError(403, "path_not_allowed", cors);
  }
  if (pathRequiresSymbol(path) && !url.searchParams.get("symbol")) {
    return jsonError(400, "missing_symbol", cors);
  }

  const upstreamUrl = buildUpstreamUrl(path, url.searchParams);
  const cache = deps.cache ?? defaultCache();
  const cacheKey = new Request(upstreamUrl, { method: "GET" });
  if (cache) {
    try {
      const hit = await cache.match(cacheKey);
      if (hit) return withCors(hit, cors);
    } catch {
      // 缓存故障不阻断代理，继续回源。
    }
  }

  const fetchImpl = deps.fetchImpl ?? fetch;
  let upstream: Response;
  try {
    upstream = await fetchImpl(upstreamUrl, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  } catch {
    return jsonError(502, "upstream_unreachable", cors);
  }

  if (!upstream.ok) {
    // 上游错误原样返回，不写缓存（避免把 429/5xx 固化 5 分钟）。
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        ...cors,
        "Content-Type":
          upstream.headers.get("Content-Type") || "application/json; charset=utf-8",
      },
    });
  }

  const response = new Response(upstream.body, {
    status: 200,
    headers: {
      ...cors,
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
    },
  });

  if (cache) {
    // 缓存写失败只记在平台日志里，不影响本次响应。
    const put = cache.put(cacheKey, response.clone()).catch(() => undefined);
    if (ctx && typeof ctx.waitUntil === "function") {
      ctx.waitUntil(put);
    } else {
      await put;
    }
  }

  return response;
}

const defaultLimiter = new FixedWindowRateLimiter();

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<Response> {
    return handleRequest(request, env, ctx);
  },
};
